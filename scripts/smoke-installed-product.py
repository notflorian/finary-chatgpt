"""Runtime-only installed-product checks. Run with Python -I outside the checkout."""

import argparse
import importlib.metadata
import importlib.util
import json
import os
import socket
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path
from typing import get_args
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def require(value, message):
    if not value:
        raise AssertionError(message)


def installed_files(reference, prefix):
    site = Path(sysconfig.get_path("purelib")).resolve()
    require(site.is_relative_to(prefix.resolve()), "Unexpected installation prefix")
    dist = importlib.metadata.distribution("finary-bridge")
    metadata = next(p for p in dist.files if str(p).endswith('.dist-info/METADATA'))
    require(Path(dist.locate_file(metadata)).resolve().is_relative_to(site),
            "Distribution metadata outside intended installation")
    spec = importlib.util.find_spec("app")
    expected = Path(dist.locate_file("app/__init__.py")).resolve()
    require(spec is not None and Path(spec.origin).resolve() == expected
            and expected.is_relative_to(site), "Application import outside intended installation")
    direct = dist.read_text("direct_url.json")
    require(not direct or not json.loads(direct).get("dir_info", {}).get("editable"),
            "Editable installation is not a release artifact")
    require(dist.metadata.get("License-Expression") == "MIT", "Missing MIT license metadata")
    require(dist.metadata.get_all("License-File") == ["LICENSE"], "Missing license notice metadata")
    notice = next((p for p in dist.files if str(p).endswith('.dist-info/licenses/LICENSE')), None)
    require(notice is not None and Path(dist.locate_file(notice)).is_file(),
            "Missing installed license notice")
    require(Path(dist.locate_file(notice)).read_bytes() == (reference / "LICENSE").read_bytes(),
            "License notice differs from authoritative source")
    for packaged, canonical in (("mcp-contract.json", "finary-mcp-contract.json"),
                                 ("workbook-schema.json", "google-sheets-schema.json")):
        resource = expected.parent / packaged
        require(resource.is_file(), "Missing packaged contract resource: " + packaged)
        require(resource.read_bytes() == (reference / canonical).read_bytes(),
                "Packaged contract differs from canonical resource")
    names = {d.metadata['Name'].lower() for d in importlib.metadata.distributions()}
    require(not names.intersection({"pytest", "pytest-xdist", "mypy", "ruff", "build",
                                    "types-jsonschema"}), "Development dependencies leaked")
    require(not any('/tests/' in str(p) or '/fixtures/' in str(p) or '/scripts/' in str(p)
                    for p in dist.files), "Support files shipped in application")
    print(json.dumps({"module": str(expected), "metadata": str(dist.locate_file(metadata)),
                      "dependencies": sorted(names)}), flush=True)
    return dist


def guards(marker, state):
    def forbidden(kind):
        # Persist attempted access even when the application catches the exception.
        with marker.open("a") as stream:
            stream.write(kind + "\n")
        raise AssertionError("Forbidden product access: " + kind)

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            forbidden(event)
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if path.is_relative_to(state):
                forbidden("OAuth state file access")

    def profile(frame, event, arg):
        if event != "call":
            return
        module = frame.f_globals.get("__name__", "")
        name = frame.f_code.co_qualname
        if ((module == "app.mcp_client" and name == "NativeMcpClient.__init__")
                or (module == "app.mcp_auth"
                    and (name.startswith("OAuthStore.") or name == "authorized_http"))):
            forbidden(module + "." + name)

    sys.addaudithook(audit)
    sys.setprofile(profile)
    threading.setprofile(profile)


def serve(args):
    guards(args.marker, Path(os.environ["FINARY_MCP_STATE_PATH"]).parent)
    dist = installed_files(args.reference, args.prefix)
    import uvicorn
    from app import main
    from app.config import SERVICE_NAME, SERVICE_VERSION
    from app.mcp_models import McpSnapshotV1
    from app.mcp_validation import CONTRACT
    from app.mcp_workbook import SCHEMA, google_create, initialize

    site = Path(sysconfig.get_path("purelib")).resolve()
    for name, module in tuple(sys.modules.items()):
        if name == "app" or name.startswith("app."):
            require(Path(module.__file__).resolve().is_relative_to(site), "Checkout module loaded")
    require(dist.version == SERVICE_VERSION == CONTRACT["implemented"]["application_version"]
            == "1.0.0", "Application version mismatch")
    require(SERVICE_NAME == "finary-bridge", "Service name mismatch")
    require(CONTRACT["contract_version"] == "1.0.0"
            == CONTRACT["providers"]["finary_official_mcp"]["source_contract_version"],
            "Source contract version mismatch")
    require(SCHEMA["schema_version"] == CONTRACT["implemented"]["workbook_schema"] == "1.0",
            "Workbook version mismatch")
    require(CONTRACT["implemented"]["api_schema"] == "1.0"
            in get_args(McpSnapshotV1.model_fields["schema_version"].annotation), "API version mismatch")
    inventory = initialize("synthetic-artifact-writer", 1)
    require(list(inventory["sheets"]) == list(SCHEMA["sheets"]), "Workbook order mismatch")
    for name, definition in SCHEMA["sheets"].items():
        require(inventory["sheets"][name]["headers"]
                == [column["name"] for column in definition["columns"]], "Header mismatch")
    require(inventory["sheets"]["writer_control"]["rows"][0]["state"] == "PAUSED",
            "Initializer must be PAUSED")
    require(inventory["sheets"]["README"]["rows"] == SCHEMA["readme_entries"], "Metadata mismatch")
    body = google_create(inventory)
    require([s["properties"]["title"] for s in body["sheets"]] == list(SCHEMA["sheets"]),
            "Google create order mismatch")
    for index, sheet in enumerate(body["sheets"]):
        name = sheet["properties"]["title"]
        require(sheet["properties"]["index"] == index, "Google sheet index mismatch")
        rows = sheet["data"][0]["rowData"]
        decoded = [[next(iter(c.get("userEnteredValue", {}).values()), "")
                    for c in row["values"]] for row in rows]
        original = inventory["sheets"][name]
        require(decoded == [original["headers"], *[
            [row.get(col, "") for col in original["headers"]] for row in original["rows"]]],
            "Google create cell mismatch")
    uvicorn.run(main.app, host="127.0.0.1", port=args.port, loop="asyncio",
                log_level="error", access_log=False)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(port, path, headers=None):
    opener = build_opener(NoRedirect, ProxyHandler({}))
    try:
        response = opener.open(Request(f"http://127.0.0.1:{port}{path}", headers=headers or {}),
                               timeout=2)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, json.load(response)


def health(port, process=None):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process is not None:
            require(process.poll() is None, "Installed server exited before health")
        try:
            status, _, body = request(port, "/health")
            require(status == 200 and body == {
                "status": "ok", "service": "finary-bridge", "version": "1.0.0"},
                "Unexpected health response")
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.1)
    raise AssertionError("Installed server health timed out")


def smoke(args):
    installed_files(args.reference, args.prefix)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    for protected in (False, True):
        environment = {"PATH": os.environ.get("PATH", os.defpath),
                       "FINARY_MCP_STATE_PATH": str(Path.cwd() / "forbidden-state/oauth.json")}
        if protected:
            environment["FINARY_BRIDGE_API_KEY"] = "synthetic-smoke-key"
        process = subprocess.Popen([
            sys.executable, "-I", str(Path(__file__).resolve()), "--serve",
            "--reference", str(args.reference), "--prefix", str(args.prefix),
            "--marker", str(args.marker), "--port", str(port),
        ], env=environment)
        try:
            health(port, process)
            status, _, document = request(port, "/openapi.json")
            routes = {"/health", "/v1/snapshot", "/v1/budget", "/v1/spending-search", "/v1/goals"}
            require(status == 200 and set(document["paths"]) == routes, "OpenAPI route mismatch")
            require(document["info"]["version"] == "1.0.0", "OpenAPI version mismatch")
            for route in routes - {"/health"}:
                if protected:
                    for headers in ({}, {"X-API-Key": "incorrect-synthetic-key"}):
                        status, _, body = request(port, route, headers)
                        require(status == 401 and body == {"error": {
                            "code": "BRIDGE_AUTH_FAILED", "message": "Bridge authentication failed",
                            "retryable": False}}, "Authentication response changed")
                for major in (0, 2, 3, 99):
                    for suffix in ("", "/"):
                        status, headers, _ = request(port, route.replace("/v1/", f"/v{major}/")
                                                     + suffix, {"X-API-Key": "synthetic-smoke-key"})
                        require(status == 404 and "Location" not in headers,
                                "Unsupported API major accepted or redirected")
            require(not args.marker.exists(), "No-access sentinel was triggered")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        require(not args.marker.exists(), "No-access sentinel triggered during shutdown")
    print("INSTALLED_PRODUCT_VALIDATED", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--prefix", type=Path, default=Path(sys.prefix))
    parser.add_argument("--marker", type=Path, default=Path.cwd() / "forbidden-access.log")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--normal-health", action="store_true")
    args = parser.parse_args()
    if args.normal_health:
        health(args.port)
        print("IMAGE_DEFAULT_STARTUP_VALIDATED")
    elif args.serve:
        serve(args)
    else:
        smoke(args)
