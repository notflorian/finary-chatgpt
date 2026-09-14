"""Frozen workbook zero-position lifecycle regressions."""

from copy import deepcopy
from datetime import datetime

import pytest
from test_n8n_workflow import _run_id
from test_n8n_workflow_v2 import (
    _apply_prepared_writes,
    _empty_workbook,
    _known_eur_snapshot,
    _prepare_for_run,
    _run_validation,
)
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from workbook_consumer import select_assets, select_liabilities

NOW = datetime.fromisoformat("2026-08-20T12:00:00+02:00")


def zero_snapshot(coverage="UNAVAILABLE", timestamp="2026-08-20T08:30:00+02:00"):
    snapshot = _known_eur_snapshot(timestamp)
    snapshot.update(positions=[], liabilities=[], gross_assets_eur=100.0)
    snapshot["accounts"][0]["market_value_eur"] = 100.0
    snapshot["coverage"] = {"liabilities": coverage, "position_collections": "COMPLETE"}
    snapshot["liabilities_eur"] = 0.0 if coverage == "COMPLETE" else None
    snapshot["net_worth_eur"] = 100.0 if coverage == "COMPLETE" else None
    return snapshot


@pytest.mark.parametrize(
    "evidence", ["absent", "UNAVAILABLE", "PARTIAL", None, True, {}, "complete"]
)
def test_zero_positions_requires_explicit_evidence(workflow, schema, evidence):
    snapshot = zero_snapshot()
    if evidence == "absent":
        del snapshot["coverage"]["position_collections"]
    else:
        snapshot["coverage"]["position_collections"] = evidence
    assert _run_validation(workflow, schema, snapshot)["can_write"] is False


@pytest.mark.parametrize("evidence", ["absent", "UNAVAILABLE", "COMPLETE"])
def test_legacy_nonempty_payload_compatibility(workflow, schema, evidence):
    snapshot = _known_eur_snapshot("2026-08-20T07:30:00+02:00")
    if evidence != "absent":
        snapshot["coverage"]["position_collections"] = evidence
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("coverage", ["COMPLETE", "PARTIAL", "UNAVAILABLE"])
def test_zero_position_lifecycle_and_consumer(workflow, schema, populated, coverage):
    book = _empty_workbook()
    book.update(
        {
            sheet: [{"synthetic_note": sheet}]
            for sheet in (
                "allocation_targets",
                "asset_overrides",
                "cashflows",
            )
        }
    )
    if populated:
        for date in ["2026-08-19", "2026-08-20"]:
            snapshot = _known_eur_snapshot(f"{date}T07:30:00+02:00")
            prepared = _prepare_for_run(workflow, schema, snapshot, book, date)
            _apply_prepared_writes(schema, book, prepared, completed_at=f"{date}T05:31:00Z")
    before = deepcopy(book)
    for index in range(2):
        snapshot = zero_snapshot(coverage, f"2026-08-20T0{8 + index}:30:00+02:00")
        assert _run_validation(workflow, schema, snapshot)["can_write"] is True
        prepared = _prepare_for_run(workflow, schema, snapshot, book, f"zero-{index}")
        assert prepared["history_rows"] == []
        assert all(row["is_active"] is False for row in prepared["position_rows"])
        for old, new in zip(before["positions_current"], prepared["position_rows"], strict=True):
            assert new == {**old, "is_active": False}
        _apply_prepared_writes(
            schema, book, prepared, completed_at=f"2026-08-20T0{6 + index}:31:00Z"
        )
        # A repeated write of the same run is an upsert, never another terminal.
        saved = deepcopy(book)
        _apply_prepared_writes(
            schema, book, prepared, completed_at=f"2026-08-20T0{6 + index}:31:00Z"
        )
        assert book == saved
        state = select_assets(book, now=NOW)
        assert state.source == "current" and state.current_complete
        assert state.positions == state.history == []
        assert state.run_id == _run_id(f"zero-{index}")
        assert state.daily["gross_assets_eur"] == 100
        assert state.accounts[0]["market_value_eur"] == 100
        assert book["positions_history"] == before["positions_history"]
        terminal = book["sync_runs"][-1]
        assert terminal["positions_count"] == 0
        assert terminal["status"] == (
            "SUCCESS_WITH_WARNINGS"
            if coverage != "COMPLETE" or (populated and index == 0)
            else "SUCCESS"
        )
        if coverage != "COMPLETE":
            assert book["liabilities_current"] == before["liabilities_current"]
            assert state.daily["liabilities_eur"] is state.daily["net_worth_eur"] is None
            liability = select_liabilities(book)
            assert liability.complete is populated
            if populated:
                assert liability.reference_run_id == _run_id("2026-08-20")
        else:
            assert select_liabilities(book).liabilities_eur == 0
            assert book["liabilities_current"] == [
                {**row, "is_active": False} for row in before["liabilities_current"]
            ]
    for sheet in ("allocation_targets", "asset_overrides", "cashflows"):
        assert book[sheet] == before[sheet]


@pytest.mark.parametrize(
    "anomaly",
    [
        "no_terminal",
        "failed",
        "blank_count",
        "foreign_active",
        "duplicate_inactive",
        "foreign_history_duplicate",
    ],
)
def test_zero_evidence_does_not_hide_inconsistent_workbook(workflow, schema, anomaly):
    book = _empty_workbook()
    populated = _prepare_for_run(
        workflow, schema, _known_eur_snapshot("2026-08-20T07:30:00+02:00"), book, "populated"
    )
    _apply_prepared_writes(schema, book, populated)
    prepared = _prepare_for_run(workflow, schema, zero_snapshot(), book, "zero")
    _apply_prepared_writes(schema, book, prepared, completed_at="2026-08-20T06:31:00Z")
    if anomaly == "no_terminal":
        book["sync_runs"].pop()
    elif anomaly == "failed":
        book["sync_runs"][-1]["status"] = "FAILED"
    elif anomaly == "blank_count":
        book["sync_runs"][-1]["positions_count"] = None
    elif anomaly == "foreign_active":
        book["positions_current"][0]["is_active"] = True
    elif anomaly == "duplicate_inactive":
        book["positions_current"].append(deepcopy(book["positions_current"][0]))
    else:
        book["positions_history"].append(deepcopy(book["positions_history"][0]))
        # Force independent historical fallback to exercise full-date validation.
        book["accounts_current"] = []
    state = select_assets(book, now=NOW)
    assert not state.current_complete
    if anomaly in {"foreign_active", "duplicate_inactive"}:
        assert state.source == "history" and state.positions == []
    else:
        assert state.positions is None
