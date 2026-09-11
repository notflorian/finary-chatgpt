"""Reference interpretation of complete physical v3 workbook reads.

The caller supplies a coherent read of all tables. Successful membership checks
cannot make sequential Google reads atomic. Never combine this selection with
live MCP detail or replace official overview figures with detail sums.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.mcp_validation import CONTRACT, validate, validate_collection_context, validate_money

TABLES = CONTRACT["workbook_migration"]["tables"]
COUNTS = TABLES["sync_runs"]["count_columns"]
CHILD_KEYS = {
    "account_ownership": ("account_key", "owner_key"),
    "source_connections": ("connection_key",),
    "position_rates": ("position_key", "source_field"),
    "official_allocation_categories": ("category",),
    "official_allocation_types": ("category", "holding_type"),
    "portfolio_members": ("member_ordinal",),
    "source_warnings": ("code", "entity_key"),
    "unsupported_details": ("account_key", "holding_type", "reason"),
}


def require(value: bool) -> None:
    if not value:
        raise ValueError("Workbook observation is not independently validated")


def instant(value: Any) -> datetime:
    require(isinstance(value, str))
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() is not None)
    return result


def blank(value: Any) -> Any:
    return None if value == "" else value


def normalized(table: str, row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    definition = TABLES[table]
    for column, pointer in definition["column_bindings"].items():
        require(column in row)
        parts = pointer.split("/")[1:]
        target = result
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = blank(row[column])
    validate(definition["row_schema"].split("/")[-1], result)
    return result


def unique(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    keys = [tuple(row.get(field) for field in fields) for row in rows]
    require(len(keys) == len(set(keys)))


def compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = (
        "provider",
        "source_contract_version",
        "scope",
        "ownership_basis",
        "metric",
        "currency",
    )
    return all(
        left.get(field) is not None and left.get(field) == right.get(field) for field in fields
    )


def observation(
    workbook: dict[str, list[dict[str, Any]]], terminal: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    require(now.utcoffset() is not None)
    require(terminal.get("status") in {"SUCCESS", "SUCCESS_WITH_WARNINGS"})
    require(terminal.get("provider") == "finary_official_mcp")
    require(terminal.get("schema_version") == terminal.get("workbook_schema") == "3.0")
    require(terminal.get("source_contract_version") == "1.0.0")
    run_id, observation_id = terminal["run_id"], terminal["observation_id"]
    require(sum(r.get("run_id") == run_id for r in workbook["sync_runs"]) == 1)
    require(sum(r.get("observation_id") == observation_id for r in workbook["sync_runs"]) == 1)
    members: dict[str, list[dict[str, Any]] | None] = {}
    for table, column in COUNTS.items():
        rows = workbook[table]
        key = (
            "history_key"
            if table == "positions_history"
            else "daily_key"
            if table == "portfolio_daily"
            else "observation_id"
            if table == "observations"
            else "account_key"
            if table == "accounts_current"
            else "position_key"
            if table == "positions_current"
            else "liability_key"
            if table == "liabilities_current"
            else "row_key"
        )
        unique(rows, (key,))
        selected = [r for r in rows if r.get("observation_id") == observation_id]
        require(
            all(
                r.get("run_id") == run_id
                and r.get("provider", "finary_official_mcp") == "finary_official_mcp"
                for r in selected
            )
        )
        expected = blank(terminal.get(column))
        if expected is None:
            require(not selected)
            members[table] = None
            continue
        require(type(expected) is int and expected >= 0)
        if table.endswith("_current"):
            active = [r for r in selected if r.get("is_active") in (True, "TRUE")]
            require(all(r.get("is_active") in (True, False, "TRUE", "FALSE") for r in selected))
            # Current rows may have moved on. Historical membership must never
            # borrow their later balances or metadata.
            members[table] = active if len(active) == expected else None
        else:
            require(len(selected) == expected)
            members[table] = selected
    require(members["observations"] is not None and len(members["observations"]) == 1)
    require(members["portfolio_daily"] is not None and len(members["portfolio_daily"]) == 1)
    observation_rows, daily_rows = members["observations"], members["portfolio_daily"]
    if observation_rows is None or daily_rows is None:
        raise ValueError("Observation context is unavailable")
    context = normalized("observations", observation_rows[0])
    require(context["run_id"] == run_id and context["observation_id"] == observation_id)
    overview = normalized("portfolio_daily", daily_rows[0])
    validate_collection_context(context)
    # Reuse the contract's overview/coverage implications. Native detail
    # valuation cannot be re-proven from current rows that have since changed.
    import json

    from jsonschema import Draft202012Validator

    implications = [
        rule
        for rule in CONTRACT["$defs"]["snapshot_v3"]["allOf"]
        if "account_valuation" not in json.dumps(rule)
        and "holding_valuation" not in json.dumps(rule)
    ]
    require(
        Draft202012Validator({"allOf": implications, "$defs": CONTRACT["$defs"]}).is_valid(
            {
                **context,
                "overview": overview,
                "unsupported_details": [
                    normalized("unsupported_details", row)
                    for row in members["unsupported_details"] or []
                ],
            }
        )
    )
    completed = instant(terminal["completed_at"])
    require(instant(context["generated_at"]) <= completed <= now)
    from urllib.parse import quote

    detail: dict[str, list[dict[str, Any]] | None] = {}
    for table, fields in CHILD_KEYS.items():
        child_rows = members[table]
        if child_rows is None:
            detail[table] = None
            continue
        parsed = [normalized(table, row) for row in child_rows]
        unique(parsed, fields)
        for row, value in zip(child_rows, parsed, strict=True):
            parts = [
                "~null"
                if value[field] is None
                else "~value" + quote(value[field], safe="-._~")
                if field == "entity_key"
                else quote(str(value[field]), safe="-._~")
                for field in fields
            ]
            require(row["row_key"] == observation_id + ":" + table + ":" + ":".join(parts))
        detail[table] = parsed
    for money in (
        overview["gross_assets"],
        overview["financial_assets"],
        overview["reported_liabilities"],
        overview["reported_net_worth"],
    ):
        validate_money(money, context["provenance"]["currency"])
    for table in (
        "official_allocation_categories",
        "official_allocation_types",
        "portfolio_members",
    ):
        for row in detail[table] or []:
            for value in row.values():
                if isinstance(value, dict) and "amount" in value:
                    validate_money(value, context["provenance"]["currency"])
    history = members["positions_history"]
    positions = (
        [normalized("positions_history", row) for row in history] if history is not None else None
    )
    for row in history or []:
        require(
            row["history_key"]
            == f"mcp:history:{context['snapshot_date']}:{observation_id}:{row['position_key']}"
        )
        require(
            row["snapshot_date"] == context["snapshot_date"]
            and row["generated_at"] == context["generated_at"]
        )
    accounts = members["accounts_current"]
    current = accounts is not None and members["positions_current"] is not None
    if current:
        account_values = [normalized("accounts_current", row) for row in accounts or []]
        current_positions = [
            normalized("positions_current", row) for row in members["positions_current"] or []
        ]
        # Use the production semantic validator to validate the complete current
        # observation, including diagnostics, ownership and native valuation.
        snapshot = {
            "schema_version": "3.0",
            **context,
            "overview": overview,
            "accounts": account_values,
            "debt_details": [],
            "positions": current_positions,
            "ownership": detail["account_ownership"] or [],
            "connections": detail["source_connections"] or [],
            "position_rates": detail["position_rates"] or [],
            "allocation_categories": detail["official_allocation_categories"] or [],
            "allocation_types": detail["official_allocation_types"] or [],
            "members": detail["portfolio_members"] or [],
            "warnings": detail["source_warnings"] or [],
            "unsupported_details": detail["unsupported_details"] or [],
        }
        snapshot.pop("run_id")
        from app.mcp_models import McpSnapshotV3

        McpSnapshotV3.model_validate(snapshot)
        require(current_positions == positions)
    return {
        "context": context,
        "overview": overview,
        "detail": detail,
        "positions": positions,
        "accounts": [normalized("accounts_current", r) for r in accounts]
        if current and accounts is not None
        else None,
        "current_complete": current,
        "dated_fallback": not current,
        "stale": now - completed > timedelta(hours=48),
        "completed_at": terminal["completed_at"],
        "performance_available": False,
    }


def select(workbook: dict[str, list[dict[str, Any]]], *, now: datetime) -> dict[str, Any]:
    candidates = [
        r
        for r in workbook["sync_runs"]
        if r.get("status") in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
        and r.get("provider") == "finary_official_mcp"
    ]
    unique(candidates, ("completed_at",))
    candidates.sort(key=lambda r: instant(r["completed_at"]), reverse=True)
    for index, terminal in enumerate(candidates):
        try:
            result = observation(workbook, terminal, now=now)
            result["dated_fallback"] |= index > 0
            result["series_break"] = True
            for prior in candidates[index + 1 :]:
                try:
                    previous = observation(workbook, prior, now=now)
                    result["series_break"] = not compatible(
                        result["context"]["provenance"], previous["context"]["provenance"]
                    )
                    break
                except (ValueError, KeyError, TypeError):
                    continue
            return result
        except (ValueError, KeyError, TypeError):
            continue
    raise ValueError("No independently validated MCP workbook observation")
