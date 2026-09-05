"""Executable specification of the published consumer rules.

Test-only: this module is not deployed in n8n or automatically run by ChatGPT.
Input is a complete read of physical rows, excluding headers and wholly empty
rows. No current-table prefiltering or key-based deduplication is permitted.
Sequential reads do not become a transaction by passing these checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

Row = dict[str, Any]
Workbook = dict[str, list[Row]]
SUCCESS = {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
# Match the exported prewrite arithmetic tolerance; copied values and counts
# still require exact equality. Binary floating-point sums are not exact decimals.
AMOUNT_TOLERANCE = Decimal("1e-8")
KEYS = {
    "account_key": re.compile(r"finary:account:[^:\s]+"),
    "position_key": re.compile(r"finary:[^:\s]+:asset:[^:\s]+:[^:\s]+"),
    "liability_key": re.compile(r"finary:liability:[^:\s]+"),
}


def instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value).strip()
    if not NUMBER.fullmatch(text):
        return None
    try:
        parsed = Decimal(text)
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def count(value: Any) -> int | None:
    parsed = number(value)
    if parsed is None or parsed < 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def activity(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in {"TRUE", "FALSE"}:
        return value == "TRUE"
    return None


def identity(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def unique_keys(rows: list[Row], key: str) -> bool:
    values = [row.get(key) for row in rows]
    return all(isinstance(value, str) and KEYS[key].fullmatch(value) for value in values) and len(
        values
    ) == len(set(values))


def terminal(workbook: Workbook, run_id: Any) -> Row | None:
    if not identity(run_id):
        return None
    records = [row for row in workbook["sync_runs"] if row.get("run_id") == run_id]
    if len(records) != 1:
        return None
    row = records[0]
    return row if row.get("status") in SUCCESS and instant(row.get("completed_at")) else None


def latest_success(workbook: Workbook, coverage: str | None = None) -> Row | None:
    candidates = [
        row
        for row in workbook["sync_runs"]
        if row.get("status") in SUCCESS
        and (coverage is None or row.get("liability_coverage") == coverage)
    ]
    if not candidates or any(terminal(workbook, row.get("run_id")) is None for row in candidates):
        return None
    newest = max(instant(row["completed_at"]) for row in candidates)
    latest = [row for row in candidates if instant(row["completed_at"]) == newest]
    # Equal instants never get an invented tie-break based on opaque IDs.
    return latest[0] if len(latest) == 1 else None


def active_members(rows: list[Row], key: str, run: Row, count_field: str) -> list[Row] | None:
    expected = count(run.get(count_field))
    if expected is None or not unique_keys(rows, key):
        return None
    if any(activity(row.get("is_active")) is None for row in rows):
        return None
    active = [row for row in rows if activity(row["is_active"])]
    if len(active) != expected or any(
        row.get("last_seen_run_id") != run["run_id"] for row in active
    ):
        return None
    # Inactive rows retain their last observation, not their last write ID.
    return active


def validated_daily(workbook: Workbook, row: Row) -> Row | None:
    snapshot_date = row.get("snapshot_date")
    try:
        if not isinstance(snapshot_date, str) or date.fromisoformat(snapshot_date).isoformat() != (
            snapshot_date
        ):
            return None
    except ValueError:
        return None
    if (
        sum(other.get("snapshot_date") == snapshot_date for other in workbook["portfolio_daily"])
        != 1
    ):
        return None
    run = terminal(workbook, row.get("run_id"))
    generated = instant(row.get("generated_at"))
    if run is None or generated is None:
        return None
    if generated.astimezone(ZoneInfo("Europe/Paris")).date().isoformat() != snapshot_date:
        return None
    coverage = row.get("liability_coverage")
    if coverage not in {"COMPLETE", "PARTIAL", "UNAVAILABLE"} or coverage != run.get(
        "liability_coverage"
    ):
        return None
    gross = number(row.get("gross_assets_eur"))
    if gross is None or gross != number(run.get("gross_assets_eur")):
        return None
    for field in ("liabilities_eur", "net_worth_eur"):
        if coverage == "COMPLETE":
            if number(row.get(field)) is None or number(row[field]) != number(run.get(field)):
                return None
        elif row.get(field) not in (None, "") or run.get(field) not in (None, ""):
            return None
    if (
        coverage == "COMPLETE"
        and abs(gross - number(row["liabilities_eur"]) - number(row["net_worth_eur"]))
        > AMOUNT_TOLERANCE
    ):
        return None
    return run


def validated_history(workbook: Workbook, daily: Row, run: Row) -> list[Row] | None:
    same_date = [
        row
        for row in workbook["positions_history"]
        if row.get("snapshot_date") == daily["snapshot_date"]
    ]
    # Check physical keys before filtering membership: a duplicate cannot hide
    # behind a foreign run ID. Distinct retained keys from older runs are valid.
    if not unique_keys(same_date, "position_key") or any(
        row.get("history_key") != f"{daily['snapshot_date']}:{row.get('position_key')}"
        for row in same_date
    ):
        return None
    history = [row for row in same_date if row.get("run_id") == run["run_id"]]
    expected = count(run.get("positions_count"))
    if expected is None or len(history) != expected:
        return None
    if any(instant(row.get("generated_at")) != instant(daily["generated_at"]) for row in history):
        return None
    return history


@dataclass
class AssetSelection:
    latest_success_run_id: str | None
    run_id: str | None = None
    source: str = "unavailable"
    current_complete: bool = False
    accounts: list[Row] | None = None
    positions: list[Row] | None = None
    daily: Row | None = None
    history: list[Row] | None = None
    snapshot_date: str | None = None
    completed_at: str | None = None
    dated_fallback: bool = False
    stale: bool | None = None
    # A validated aggregate can survive unavailable position detail, and can
    # belong to a newer run than an explicitly dated historical fallback.
    aggregate_run_id: str | None = None
    aggregate_daily: Row | None = None


def select_assets(workbook: Workbook, *, now: datetime) -> AssetSelection:
    if now.utcoffset() is None:
        raise ValueError("Selection requires a timezone-aware observation time")
    latest = latest_success(workbook)
    result = AssetSelection(latest["run_id"] if latest else None)
    daily_states = []
    for daily in workbook["portfolio_daily"]:
        run = validated_daily(workbook, daily)
        if run is not None:
            daily_states.append((daily, run, validated_history(workbook, daily, run)))
    # Business dates have canonical YYYY-MM-DD format; IDs never set order.
    daily_states.sort(key=lambda state: state[0]["snapshot_date"], reverse=True)
    if daily_states:
        result.aggregate_daily, aggregate_run, _ = daily_states[0]
        result.aggregate_run_id = aggregate_run["run_id"]

    if latest is not None:
        accounts = active_members(
            workbook["accounts_current"], "account_key", latest, "accounts_count"
        )
        positions = active_members(
            workbook["positions_current"], "position_key", latest, "positions_count"
        )
        if accounts is not None and positions is not None:
            account_keys = {row["account_key"] for row in accounts}
            references_valid = all(row.get("account_key") in account_keys for row in positions)
            history_state = next(
                (state for state in daily_states if state[1]["run_id"] == latest["run_id"]), None
            )
            history = history_state[2] if history_state else None
            membership_matches = history is None or (
                {row["position_key"] for row in positions}
                == {row["position_key"] for row in history}
            )
            if references_valid and membership_matches:
                result.source = "current"
                result.current_complete = True
                result.accounts, result.positions = accounts, positions
                result.history = history
                result.daily = history_state[0] if history_state else None
                result.run_id = latest["run_id"]
                result.completed_at = latest["completed_at"]
                # With no daily row, do not invent a business date from a run ID.
                result.snapshot_date = result.daily["snapshot_date"] if result.daily else None

    if not result.current_complete:
        state = next((state for state in daily_states if state[2] is not None), None)
        if state:
            result.daily, run, result.history = state
            result.positions = result.history
            result.run_id = run["run_id"]
            result.completed_at = run["completed_at"]
            result.snapshot_date = result.daily["snapshot_date"]
            result.source = "history"
            result.dated_fallback = True
            # No current account metadata, region, or balance enrichment.
    if result.completed_at:
        result.stale = now - instant(result.completed_at) > timedelta(hours=48)
    return result


@dataclass
class LiabilitySelection:
    reference_run_id: str | None
    complete: bool = False
    rows: list[Row] | None = None
    completed_at: str | None = None
    snapshot_at: str | None = None
    snapshot_date: str | None = None
    liabilities_eur: Any = None


def select_liabilities(workbook: Workbook) -> LiabilitySelection:
    run = latest_success(workbook, "COMPLETE")
    result = LiabilitySelection(run["run_id"] if run else None)
    if run is None:
        return result
    rows = active_members(
        workbook["liabilities_current"], "liability_key", run, "liabilities_count"
    )
    if rows is None:
        return result
    total = number(run.get("liabilities_eur"))
    if total is None or any(number(row.get("outstanding_eur")) is None for row in rows):
        return result
    if not rows and total != 0:
        return result
    if (
        abs(sum((number(row["outstanding_eur"]) for row in rows), Decimal(0)) - total)
        > AMOUNT_TOLERANCE
    ):
        return result
    observations = {instant(row.get("last_seen_at")) for row in rows}
    if rows and (None in observations or len(observations) != 1):
        return result
    result.complete, result.rows = True, rows
    result.completed_at, result.liabilities_eur = run["completed_at"], run["liabilities_eur"]
    if rows:
        result.snapshot_at = rows[0]["last_seen_at"]
    else:
        # A zero count has no active row carrying generated_at. A matching daily
        # row can supply it; started_at is never relabeled as snapshot time.
        daily = next(
            (
                row
                for row in workbook["portfolio_daily"]
                if (
                    row.get("run_id") == run["run_id"]
                    and validated_daily(workbook, row) is not None
                )
            ),
            None,
        )
        result.snapshot_at = daily["generated_at"] if daily else None
    if result.snapshot_at:
        result.snapshot_date = (
            instant(result.snapshot_at).astimezone(ZoneInfo("Europe/Paris")).date().isoformat()
        )
    return result
