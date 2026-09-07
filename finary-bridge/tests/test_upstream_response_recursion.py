"""Keep upstream recursion failures inside the real adapter and HTTP boundaries."""

import json
import logging
from copy import deepcopy
from unittest.mock import Mock

import pytest
from curl_cffi.requests.models import Response
from test_finary_client import _credentials, _FakeResponse, _FakeSession, _load_fixture
from test_finary_token_refresh import _Transport
from test_snapshot_api import _request

from app.finary_client import FinaryApiClient, FinaryMalformedResponseError
from app.finary_session_store import FileFinarySessionStore
from app.services.snapshot_service import SnapshotService

SECRET = "synthetic-upstream-recursion-secret"
DETAIL = "synthetic-underlying-recursion-detail"
DECODE_MESSAGE = "Finary returned an undecodable JSON response"
COPY_MESSAGE = "Finary returned an uncopyable result record"
ERROR_ENVELOPE = {
    "error": {
        "code": "FINARY_MALFORMED_RESPONSE",
        "message": "Finary returned a malformed response",
        "retryable": False,
    }
}
FAILURES = [
    ("authentication", "decode"),
    ("holdings_accounts", "decode"),
    ("cryptos", "decode"),
    ("holdings_accounts", "copy"),
    ("cryptos", "copy"),
]


def _payloads():
    payloads = _load_fixture("positions.json")
    payloads["holdings_accounts"] = _load_fixture("accounts.json")
    return payloads


def _failing_client(monkeypatch, operation, boundary, error_type=RecursionError, *, store=None):
    payloads = _payloads()
    failure = Mock(side_effect=error_type(DETAIL))
    copied = []
    session = _FakeSession(entity_payloads=payloads)
    if boundary == "decode":
        response = _FakeResponse({"ignored": SECRET})
        monkeypatch.setattr(response, "json", failure)
        if operation == "authentication":
            session.post_responses.clear()
            session.post_responses.append(response)
        else:
            original_get = session.get

            def get(url, *, timeout):
                ordinary = original_get(url, timeout=timeout)
                return response if url.endswith(f"/{operation}") else ordinary

            monkeypatch.setattr(session, "get", get)
    else:
        # The first record and, for cryptos, the securities collection succeed.
        records = payloads[operation]["result"]
        records.append({**deepcopy(records[0]), "ignored": {"nested": [SECRET]}})

        def copy_record(record):
            if "ignored" in record:
                return failure(record)
            result = deepcopy(record)
            copied.append(record["id"])
            return result

        monkeypatch.setattr("app.finary_client.deepcopy", copy_record)
    client = FinaryApiClient(_credentials(), session_factory=lambda: session, session_store=store)
    return client, session, failure, copied


def _assert_sanitized(caplog, text=""):
    logged = caplog.text + repr([record.__dict__ for record in caplog.records])
    for forbidden in (
        SECRET,
        DETAIL,
        "RecursionError",
        "maximum recursion",
        "Traceback",
        "synthetic-password",
        "synthetic-session",
        "synthetic-cookie",
        "synthetic-token",
    ):
        assert forbidden not in text + logged
    assert all(record.exc_info is None for record in caplog.records)


def _assert_stopped(session, failure, copied, operation, boundary, caplog):
    failure.assert_called_once()
    names = [url.rsplit("/", 1)[-1] for url in session.requested_urls]
    expected = [] if operation == "authentication" else ["holdings_accounts"]
    if operation == "cryptos":
        expected += ["securities", "cryptos"]
    assert names == expected
    if boundary == "copy":
        assert copied == (
            ["account-synthetic-001", "account-synthetic-002"]
            + ([1001, 1002] if operation == "cryptos" else [])
        )
    events = [getattr(record, "event", None) for record in caplog.records]
    assert "finary.positions.retrieved" not in events
    if operation != "cryptos":
        assert "finary.accounts.retrieved" not in events
    _assert_sanitized(caplog)


@pytest.mark.parametrize("operation,boundary", FAILURES)
def test_adapter_translates_recursion(monkeypatch, caplog, operation, boundary):
    client, session, failure, copied = _failing_client(monkeypatch, operation, boundary)
    caplog.set_level(logging.INFO)
    with pytest.raises(FinaryMalformedResponseError) as caught:
        client.authenticate()
        if operation != "authentication":
            client.get_accounts()
        if operation == "cryptos":
            client.get_positions()
    assert str(caught.value) == (DECODE_MESSAGE if boundary == "decode" else COPY_MESSAGE)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    _assert_stopped(session, failure, copied, operation, boundary, caplog)


@pytest.mark.parametrize("operation,boundary", FAILURES)
@pytest.mark.parametrize("route", ["/v1/snapshot", "/v2/snapshot"])
def test_api_translates_recursion(monkeypatch, caplog, operation, boundary, route):
    client, session, failure, copied = _failing_client(monkeypatch, operation, boundary)
    caplog.set_level(logging.INFO)
    response = _request(route, client, raise_app_exceptions=False)
    assert response.status_code == 502
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ERROR_ENVELOPE
    _assert_sanitized(caplog, response.text)
    _assert_stopped(session, failure, copied, operation, boundary, caplog)


@pytest.mark.parametrize("boundary", ["decode", "copy"])
@pytest.mark.parametrize("method", ["get_snapshot", "get_snapshot_v2"])
def test_service_never_publishes_partial_collection_success(monkeypatch, boundary, method):
    client, session, failure, _ = _failing_client(monkeypatch, "cryptos", boundary)
    clock = Mock(side_effect=AssertionError("Snapshot publication must not be reached"))
    liabilities = Mock(side_effect=AssertionError("Collection retrieval must abort"))
    monkeypatch.setattr(client, "get_liabilities", liabilities)
    service = SnapshotService(client, clock=clock)
    with pytest.raises(FinaryMalformedResponseError):
        getattr(service, method)()
    failure.assert_called_once()
    clock.assert_not_called()
    liabilities.assert_not_called()
    assert len(session.requested_urls) == 3


def test_authentication_recursion_does_not_persist_or_publish(monkeypatch, tmp_path, caplog):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    store = FileFinarySessionStore(directory / "session.json")
    before = store.snapshot()
    client, session, failure, _ = _failing_client(
        monkeypatch, "authentication", "decode", store=store
    )
    publish = Mock(wraps=store.compare_and_swap)
    monkeypatch.setattr(store, "compare_and_swap", publish)
    caplog.set_level(logging.INFO)
    with pytest.raises(FinaryMalformedResponseError):
        client.authenticate()
    failure.assert_called_once()
    publish.assert_not_called()
    assert store.snapshot() == before
    assert not (directory / "session.json").exists()
    assert not client._authenticated
    assert client._token_obtained_at is None
    assert client._token_generation == 0
    assert client._session_state is None
    assert "authorization" not in session.headers
    assert session.requested_urls == []
    assert not any(
        getattr(r, "event", None) == "finary.authentication.succeeded" for r in caplog.records
    )
    _assert_sanitized(caplog)


@pytest.mark.parametrize("proactive", [False, True])
def test_refresh_recursion_preserves_owned_state(monkeypatch, tmp_path, caplog, proactive):
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    before = transport.store.snapshot()
    generation = transport.client._token_generation
    response = _FakeResponse({"jwt": SECRET})
    failure = Mock(side_effect=RecursionError(DETAIL))
    monkeypatch.setattr(response, "json", failure)
    transport.replies.append(response)
    publish = Mock(wraps=transport.store.compare_and_swap)
    monkeypatch.setattr(transport.store, "compare_and_swap", publish)
    if proactive:
        transport.now = 45
    else:
        transport.statuses.append(401)
    caplog.set_level(logging.INFO)
    with pytest.raises(FinaryMalformedResponseError, match=DECODE_MESSAGE):
        transport.client.get_accounts()
    failure.assert_called_once()
    publish.assert_not_called()
    assert transport.store.snapshot() == before
    assert transport.client._token_generation == generation
    assert not transport.client._authenticated
    assert transport.client._token_obtained_at is None
    assert "authorization" not in transport.sessions[-1].headers
    assert transport.refreshes == 2
    assert len(transport.reads) == (0 if proactive else 1)
    assert not any(
        getattr(r, "event", None) == "finary.authentication.session_refreshed"
        for r in caplog.records
    )
    _assert_sanitized(caplog)


@pytest.mark.parametrize("boundary", ["decode", "copy"])
def test_unrelated_runtime_error_is_not_hidden(monkeypatch, boundary):
    client, _, failure, _ = _failing_client(
        monkeypatch, "holdings_accounts", boundary, RuntimeError
    )
    client.authenticate()
    with pytest.raises(RuntimeError) as caught:
        client.get_accounts()
    assert caught.value is failure.side_effect


@pytest.mark.parametrize("operation", ["holdings_accounts", "cryptos"])
def test_valid_nested_records_remain_isolated(operation):
    payloads = _payloads()
    original = payloads[operation]["result"][0]
    original["ignored"] = {"nested": [[SECRET]]}
    session = _FakeSession(entity_payloads=payloads)
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)
    client.authenticate()
    if operation == "holdings_accounts":
        returned = client.get_accounts().records[0]
    else:
        positions = client.get_positions()
        assert positions.has_complete_collection_membership
        returned = next(g for g in positions.groups if g.kind.value == operation).records[0]
    returned["ignored"]["nested"][0].append("synthetic-mutation")
    assert original["ignored"] == {"nested": [[SECRET]]}
    snapshot = SnapshotService(client).get_snapshot_v2()
    assert snapshot.coverage.position_collections == "COMPLETE"
    assert len(snapshot.accounts) == 2 and len(snapshot.positions) == 6
    assert SECRET not in snapshot.model_dump_json()


@pytest.mark.parametrize("location,depth", [("envelope", 12_000), ("record", 500)])
def test_bounded_real_payloads_use_sanitized_boundary(monkeypatch, caplog, location, depth):
    payloads = _payloads()
    account_payload = payloads["holdings_accounts"]
    target = account_payload if location == "envelope" else account_payload["result"][1]
    target["ignored"] = SECRET
    # Concatenation avoids recursive fixture serialization and changes no safety limits.
    raw = json.dumps(account_payload).replace(
        json.dumps(SECRET), "[" * depth + json.dumps(SECRET) + "]" * depth
    )
    response = Response()
    response.status_code = 200
    response.content = raw.encode("utf-8")
    assert len(response.content) < 32_768
    failure_boundary = None
    try:
        decoded = response.json()
    except RecursionError:
        failure_boundary = "decode"
    else:
        nested = decoded if location == "envelope" else decoded["result"][1]
        nested = nested["ignored"]
        for _ in range(depth):
            assert isinstance(nested, list) and len(nested) == 1
            nested = nested[0]
        assert nested == SECRET
        try:
            for record in decoded["result"]:
                deepcopy(dict(record))
        except RecursionError:
            failure_boundary = "copy"
    decoding = "rejected" if failure_boundary == "decode" else "accepted"
    copying = "not reached" if failure_boundary == "decode" else failure_boundary or "accepted"
    print(f"{location}: decoder={decoding}, record-copy={copying}")
    session = _FakeSession(entity_payloads=payloads)
    original_get = session.get

    def get(url, *, timeout):
        ordinary = original_get(url, timeout=timeout)
        return response if url.endswith("/holdings_accounts") else ordinary

    monkeypatch.setattr(session, "get", get)
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)
    client.authenticate()
    if failure_boundary:
        message = DECODE_MESSAGE if failure_boundary == "decode" else COPY_MESSAGE
        with pytest.raises(FinaryMalformedResponseError, match=message):
            client.get_accounts()
    else:
        assert len(client.get_accounts().records) == 2
    caplog.set_level(logging.INFO)
    result = _request("/v2/snapshot", client, raise_app_exceptions=False)
    assert result.headers["content-type"] == "application/json"
    if failure_boundary:
        assert result.status_code == 502
        assert result.json() == ERROR_ENVELOPE
    else:
        assert result.status_code == 200
        assert result.json()["coverage"]["position_collections"] == "COMPLETE"
        assert len(result.json()["accounts"]) == 2
        assert len(result.json()["positions"]) == 6
    _assert_sanitized(caplog, result.text)
