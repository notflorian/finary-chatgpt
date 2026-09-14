"""Independent version bindings and semantic dispatch at the supported boundaries."""

import socket
from copy import deepcopy
from subprocess import CalledProcessError

import pytest
from fastapi.testclient import TestClient
from mcp_artifacts import CONTRACT, SCHEMA, WORKFLOW, validator
from mcp_snapshots import snapshot
from mcp_workbooks import empty_book, failure, prepare, writes
from pydantic import ValidationError

from app import main, mcp_auth
from app.mcp_models import McpSnapshotV1
from app.mcp_optional import ReadContext


def test_canonical_routing_metadata_agrees_with_supported_api(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected client construction, network or OAuth-state access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(main, "NativeMcpClient", forbidden)
    monkeypatch.setattr(mcp_auth, "OAuthStore", forbidden)
    monkeypatch.setattr(mcp_auth, "authorized_http", forbidden)
    implemented = CONTRACT["implemented"]
    major = "v" + implemented["api_schema"].split(".")[0]
    versioned_routing = {
        key for key in CONTRACT["provider_interfaces"]["routing"]
        if key.startswith("v") and key[1:].isdigit()
    }
    assert versioned_routing == {major}
    route = implemented["canonical_route"]
    assert route == CONTRACT["providers"]["finary_official_mcp"]["route"] == "/v1/snapshot"
    assert route.split("/")[1] == major
    with TestClient(main.app) as client:
        document = client.get("/openapi.json").json()
    assert document["paths"][route]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/McpSnapshotV1"}


def test_distinct_version_bindings_and_renamed_model_dispatch():
    assert CONTRACT["contract_version"] == "1.0.0"
    assert SCHEMA["schema_version"] == "1.0"
    assert McpSnapshotV1.contract_name == "snapshot_v1"
    assert "snapshot_v3" not in CONTRACT["$defs"]
    value = snapshot()
    assert value["schema_version"] == "1.0"
    assert value["provenance"]["source_contract_version"] == "1.0.0"
    # Valid structure with contradictory currency evidence must reach semantic validation.
    value["positions"][0]["current_value"]["amount_eur"] = "91.00"
    assert validator("#/$defs/snapshot_v1").is_valid(value)
    with pytest.raises(ValidationError, match="semantic validation"):
        McpSnapshotV1.model_validate(value)
    with pytest.raises(CalledProcessError):
        prepare(value)
    fetch = next(n for n in WORKFLOW["nodes"] if n["name"] == "Fetch MCP Snapshot")
    assert "/v1/snapshot" in fetch["parameters"]["url"]


@pytest.mark.parametrize(
    "field,version",
    [
        ("schema_version", "3.0"),
        ("schema_version", "2.0"),
        ("source_contract_version", "2.0.0"),
        ("source_contract_version", "9.0.0"),
    ],
)
def test_unsupported_snapshot_and_optional_versions_are_rejected(field, version):
    value = snapshot()
    target = value if field == "schema_version" else value["provenance"]
    target[field] = version
    with pytest.raises(ValidationError):
        McpSnapshotV1.model_validate(value)
    with pytest.raises(CalledProcessError):
        prepare(value)
    context = {"observation_id": value["observation_id"], "generated_at": value["generated_at"]}
    ReadContext.model_validate(context)
    with pytest.raises(ValidationError):
        ReadContext.model_validate({**context, field: version})


def test_success_and_failure_telemetry_share_supported_versions():
    book = empty_book()
    named = prepare(book=book)
    success = writes(named)[-1]["rows"][0]
    failed = failure(named, book)[0]
    assert success["status"] in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
    assert failed["status"] == "FAILED"
    for terminal in (success, failed):
        assert terminal["workbook_schema"] == "1.0"
        assert terminal["api_schema"] == "1.0"
        assert terminal["source_contract_version"] == "1.0.0"
    assert book == empty_book()


@pytest.mark.parametrize("version", ["4.0", "3.0", "2.1"])
def test_current_label_does_not_accept_unsupported_control(version):
    book = empty_book()
    before = deepcopy(book)
    book["writer_control"][0]["workbook_schema"] = version
    with pytest.raises(CalledProcessError):
        prepare(book=book)
    book["writer_control"][0]["workbook_schema"] = "1.0"
    assert book == before
    prepare(book=book)
