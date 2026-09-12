"""Production schema and semantic validation for normalized MCP observations."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar
from urllib.parse import quote
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, model_validator

CONTRACT: dict[str, Any] = json.loads(files("app").joinpath("mcp-contract.json").read_text())
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(TypeError, ValueError))
def aware_timestamp(value: object) -> bool:
    return isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None


@lru_cache
def schema_validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {"$ref": f"#/$defs/{name}", "$defs": CONTRACT["$defs"]}, format_checker=FORMATS
    )


def validate(name: str, value: Any) -> None:
    """Never include validation paths, input values or upstream messages in failures."""
    try:
        valid = schema_validator(name).is_valid(value)
    except (ValueError, TypeError, RecursionError):
        valid = False
    if not valid:
        raise ValueError("MCP contract validation failed") from None


def key(template: str, **components: str) -> str:
    for value in components.values():
        validate("id", value)
    return str(
        CONTRACT["identity"][template].format(
            **{f"E({name})": quote(value, safe="-._~") for name, value in components.items()}
        )
    )


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("MCP semantic validation failed")


def unique(rows: list[dict[str, Any]], *columns: str) -> None:
    identities = [tuple(row[column] for column in columns) for row in rows]
    require(len(set(identities)) == len(identities))


def validate_money(value: dict[str, Any], view_currency: str | None = None) -> None:
    amount, eur, currency = value["amount"], value["amount_eur"], value["currency"]
    basis = value["eur_basis"]
    if view_currency is not None:
        require(currency == view_currency)
    if amount is None:
        require(eur is None and basis == "UNAVAILABLE")
        return
    require(currency is not None)
    if currency == "EUR":
        require(eur is not None and basis == "SOURCE_EUR")
        require(Decimal(amount) == Decimal(eur))
    elif view_currency is not None:
        require(eur is None and basis == "UNAVAILABLE")


def validate_position(position: dict[str, Any]) -> None:
    """Validate retained position semantics without borrowing current account data."""
    components = {name: position[name] for name in ("holding_type", "holding_id")}
    require(position["source_asset_id"] == key("source_asset_id", **components))
    template = CONTRACT["identity"]["position_key"].replace(
        CONTRACT["identity"]["account_key"], "{account_key}", 1
    )
    expected = template.format(
        account_key=position["account_key"],
        **{f"E({name})": quote(value, safe="-._~") for name, value in components.items()},
    )
    require(position["position_key"] == expected)
    for field in ("current_value", "buying_price"):
        validate_money(position[field])
        require(position[field]["eur_basis"] != "SOURCE_CONVERSION")


def validate_collection_context(value: dict[str, Any]) -> None:
    """Validate the collection window independently of retained detail availability."""
    p = value["provenance"]
    generated = datetime.fromisoformat(value["generated_at"])
    start, end = (
        datetime.fromisoformat(p[f"collection_{part}_at"]) for part in ("started", "ended")
    )
    require(start <= end <= generated)
    require(
        (end - start).total_seconds()
        <= CONTRACT["transport_policy"]["limits"]["collection_timeout_seconds"]
    )
    require(
        generated.astimezone(ZoneInfo("Europe/Paris")).date().isoformat() == value["snapshot_date"]
    )


def validate_snapshot(value: dict[str, Any]) -> None:
    """Cross-record rules complement the packaged JSON Schema, never detail sums."""
    validate_collection_context(value)
    p = value["provenance"]
    table_keys = {
        "accounts": ("account_key",),
        "connections": ("connection_key",),
        "ownership": ("account_key", "owner_key"),
        "positions": ("holding_type", "holding_id"),
        "position_rates": ("position_key", "source_field"),
        "members": ("member_ordinal",),
        "allocation_categories": ("category",),
        "allocation_types": ("category", "holding_type"),
        "warnings": ("code", "entity_key"),
        "unsupported_details": ("account_key", "holding_type", "reason"),
    }
    for table, columns in table_keys.items():
        unique(value[table], *columns)
    accounts = {row["account_key"]: row for row in value["accounts"]}
    connections = {row["connection_key"] for row in value["connections"]}
    for account in accounts.values():
        require(
            account["account_key"] == key("account_key", account_id=account["source_account_id"])
        )
        connection, state = account["connection_key"], account["connection_state"]
        require(
            (state != "NO_CONNECTION" or connection is None)
            and (state != "UNRESOLVED" or connection is not None)
            and (state != "RESOLVED" or connection in connections)
        )
        validate_money(account["native_balance"])
        if account["native_balance"]["eur_basis"] == "SOURCE_CONVERSION":
            require(account["full_value_eur"] is not None)
            require(
                Decimal(account["native_balance"]["amount_eur"])
                == Decimal(account["full_value_eur"])
            )
    for owner in value["ownership"]:
        require(owner["account_key"] in accounts)
        require(accounts[owner["account_key"]]["ownership_evidence"] == "EXPLICIT_ENTRIES")
        require(
            owner["owner_key"]
            == key("owner_key", owner_type=owner["owner_type"], owner_id=owner["owner_source_id"])
        )
    positions = set()
    for position in value["positions"]:
        require(position["account_key"] in accounts)
        validate_position(position)
        positions.add(position["position_key"])
    for rate in value["position_rates"]:
        require(rate["position_key"] in positions)
    for diagnostic in value["unsupported_details"]:
        require(diagnostic["account_key"] in accounts)
    for dimension, rule in CONTRACT["valuation_contracts"].items():
        rows = value[rule["rows"]]
        known = sum(
            row[rule["money_field"]]["amount"] is not None
            and row[rule["money_field"]]["currency"] is not None
            for row in rows
        )
        expected = "UNAVAILABLE"
        if value["coverage"][rule["collection"]] == "COMPLETE":
            expected = "COMPLETE" if known == len(rows) else "PARTIAL" if known else "UNAVAILABLE"
        require(value["coverage"][dimension] == expected)
    for group in [value["overview"], *value["members"]]:
        for name in ("gross_assets", "reported_liabilities", "reported_net_worth"):
            validate_money(group[name], p["currency"])
        debt = group["reported_liabilities"]["amount"]
        require(debt is None or Decimal(debt) >= 0)
    validate_money(value["overview"]["financial_assets"], p["currency"])
    categories = {row["category"] for row in value["allocation_categories"]}
    for allocation in value["allocation_types"]:
        require(allocation["category"] in categories)
    for allocation in value["allocation_categories"] + value["allocation_types"]:
        validate_money(allocation["value"], p["currency"])


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    contract_name: ClassVar[str]

    @model_validator(mode="before")
    @classmethod
    def check_contract(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        validate(cls.contract_name, value)
        if cls.contract_name == "snapshot_v3":
            validate_snapshot(value)
        elif cls.contract_name == "money":
            validate_money(value)
        return value
