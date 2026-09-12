"""Official-provider resource parsing and relationships; no raw data leaves this adapter."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.mcp_client import LIMITS, McpFailure, McpSession, checked
from app.mcp_models import (
    McpAccount,
    McpAllocationCategory,
    McpAllocationType,
    McpConnection,
    McpMember,
    McpMoney,
    McpOverview,
    McpOwnership,
    McpPosition,
    McpPositionRate,
    McpUnsupportedDetail,
    McpWarning,
)
from app.mcp_validation import CONTRACT, key


def money(amount: Any, currency: Any, conversion: Any = None) -> dict[str, Any]:
    basis = "UNAVAILABLE"
    eur = None
    if amount is not None and currency == "EUR":
        basis, eur = "SOURCE_EUR", amount
    elif amount is not None and currency is not None and conversion is not None:
        basis, eur = "SOURCE_CONVERSION", conversion
    result = {"amount": amount, "currency": currency, "amount_eur": eur, "eur_basis": basis}
    return McpMoney.model_validate(result).model_dump()


def relation(resource: dict[str, Any], name: str) -> dict[str, str] | None:
    relations = resource.get("relationships", {})
    if not isinstance(relations, dict):
        raise McpFailure()
    entry = relations.get(name)
    if entry is None:
        return None
    if not isinstance(entry, dict) or "data" not in entry:
        raise McpFailure()
    link = entry["data"]
    if link is None:
        return None
    return checked("resource_link", link)  # type: ignore[no-any-return]


class ResourceIndex:
    def __init__(self) -> None:
        self.resources: dict[tuple[str, str], dict[str, Any]] = {}

    def add(self, resources: list[dict[str, Any]]) -> None:
        for resource in resources:
            checked("resource", resource)
            identity = resource["type"], resource["id"]
            previous = self.resources.get(identity)
            if previous is not None and previous != resource:
                raise McpFailure("MCP_INCOMPLETE_COLLECTION")
            self.resources[identity] = resource

    def resolve(self, link: dict[str, str] | None) -> dict[str, Any] | None:
        return self.resources.get((link["type"], link["id"])) if link else None


@dataclass
class Detail:
    accounts: list[McpAccount] = field(default_factory=list)
    ownership: list[McpOwnership] = field(default_factory=list)
    connections: list[McpConnection] = field(default_factory=list)
    positions: list[McpPosition] = field(default_factory=list)
    position_rates: list[McpPositionRate] = field(default_factory=list)
    warnings: list[McpWarning] = field(default_factory=list)
    unsupported_details: list[McpUnsupportedDetail] = field(default_factory=list)
    accounts_state: str = "UNAVAILABLE"
    holdings_state: str = "UNAVAILABLE"
    source_freshness: str = "UNKNOWN"

    def warn(self, code: str, entity: str | None = None) -> None:
        warning = McpWarning.model_validate({"code": code, "entity_key": entity})
        if warning not in self.warnings:
            self.warnings.append(warning)


@dataclass(frozen=True)
class OverviewData:
    currency: str
    overview: McpOverview
    categories: list[McpAllocationCategory]
    types: list[McpAllocationType]
    members: list[McpMember]


class McpAdapter:
    def __init__(self, session: McpSession, *, page_limit: int = 100, concurrency: int = 4) -> None:
        if not 1 <= page_limit <= 1000 or not 1 <= concurrency <= 8:
            raise ValueError("Invalid collection settings")
        self.session = session
        self.limit = page_limit
        self.concurrency = concurrency

    async def overview(self) -> OverviewData:
        raw = await self.session.call("get_portfolio_overview", {})
        view = raw["view"]
        if tuple(view.get(name) for name in ("scope", "ownership", "metric")) != (
            "household",
            "direct",
            "gross_assets",
        ):
            raise McpFailure("MCP_UNSUPPORTED_VIEW")
        try:
            currency = checked("currency", view["currency"])
            balance = raw["balance_sheet"]
            assets_only = balance["completeness"] == "assets_only"
            if assets_only and any(
                balance.get(name) is not None
                for name in ("owned_liabilities_direct", "owned_net_worth_direct")
            ):
                raise McpFailure()
            overview = McpOverview.model_validate(
                {
                    "gross_assets": money(balance["owned_gross_assets_direct"], currency),
                    "financial_assets": money(
                        raw["financial_assets"]["owned_financial_assets_direct"], currency
                    ),
                    "reported_liabilities": money(
                        balance.get("owned_liabilities_direct"), currency
                    ),
                    "reported_net_worth": money(balance.get("owned_net_worth_direct"), currency),
                    "unvalued_liability_count": balance["unvalued_liability_count"],
                    "source_completeness": balance["completeness"],
                    "preferred_wealth_metric": raw.get("preferred_wealth_metric"),
                }
            )
            categories, types = [], []
            for category in raw["allocation_direct"]:
                categories.append(
                    McpAllocationCategory.model_validate(
                        {
                            "category": category["category"],
                            "value": money(category["owned_amount_direct"], currency),
                        }
                    )
                )
                for holding_type in category["by_type"]:
                    types.append(
                        McpAllocationType.model_validate(
                            {
                                "category": category["category"],
                                "holding_type": holding_type["holding_type"],
                                "value": money(holding_type["owned_amount_direct"], currency),
                            }
                        )
                    )
            members = [
                McpMember.model_validate(
                    {
                        "member_ordinal": ordinal,
                        "label": member.get("name"),
                        "gross_assets": money(member["owned_gross_assets_direct"], currency),
                        "reported_liabilities": money(
                            member.get("owned_liabilities_direct"), currency
                        ),
                        "reported_net_worth": money(member.get("owned_net_worth_direct"), currency),
                        "unvalued_liability_count": member["unvalued_liability_count"],
                    }
                )
                for ordinal, member in enumerate(raw["members"])
            ]
            return OverviewData(currency, overview, categories, types, members)
        except (ValueError, KeyError, TypeError):
            raise McpFailure() from None

    async def detail(self, now: datetime) -> Detail:
        result = Detail()
        if "accounts" not in self.session.catalog:
            result.warn("INCOMPLETE_DETAIL")
            return result
        raw = await self.session.call("accounts", {})
        index = ResourceIndex()
        index.add(raw["included"])
        accounts = raw["data"]
        if len(accounts) > LIMITS["max_accounts"]:
            raise McpFailure("MCP_INCOMPLETE_COLLECTION")
        seen: set[str] = set()
        for account in accounts:
            checked("account_observed", account)
            if account["id"] in seen:
                raise McpFailure("MCP_INCOMPLETE_COLLECTION")
            seen.add(account["id"])
        index.add(accounts)
        try:
            for account in accounts:
                self._account(account, index, result, now)
        except (ValidationError, ValueError, TypeError, KeyError):
            raise McpFailure() from None
        result.accounts_state = "COMPLETE"
        result.warn("OWNERSHIP_WORDING_CONFLICT")
        if raw.get("sync_warnings"):
            result.warn("BROKEN_CONNECTION")
        if not result.connections:
            result.source_freshness = (
                "UNKNOWN"
                if any(a.connection_state == "UNRESOLVED" for a in result.accounts)
                else "NOT_APPLICABLE"
            )
        else:
            states = {c.freshness for c in result.connections}
            if any(a.connection_state == "UNRESOLVED" for a in result.accounts):
                states.add("UNKNOWN")
            result.source_freshness = next(
                s for s in ("BROKEN", "STALE", "UNKNOWN", "FRESH") if s in states
            )
        if "holdings" not in self.session.catalog:
            result.warn("INCOMPLETE_DETAIL")
            return result
        semaphore = asyncio.Semaphore(self.concurrency)
        holdings: set[tuple[str, str]] = set()
        record_count = 0

        async def collect(account: McpAccount) -> list[dict[str, Any]]:
            nonlocal record_count
            async with semaphore:
                offset, total = 0, None
                rows = []
                for _ in range(LIMITS["max_pages_per_account"]):
                    page = checked(
                        "holdings_page",
                        await self.session.call(
                            "holdings",
                            {
                                "account_id": account.source_account_id,
                                "limit": self.limit,
                                "offset": offset,
                            },
                        ),
                    )
                    meta, data = page["meta"], page["data"]
                    if total is None:
                        total = meta["total"]
                    end = offset + len(data)
                    if (
                        meta["offset"] != offset
                        or meta["limit"] != self.limit
                        or meta["total"] != total
                        or len(data) > self.limit
                        or end > total
                        or meta["has_more"] != (end < total)
                        or (not data and (offset != 0 or total != 0))
                    ):
                        raise McpFailure("MCP_INCOMPLETE_COLLECTION")
                    index.add(page["included"])
                    for row in data:
                        identity = row["type"], row["id"]
                        if identity in holdings or relation(row, "asset") != {
                            "type": "assets",
                            "id": account.source_account_id,
                        }:
                            raise McpFailure("MCP_INCOMPLETE_COLLECTION")
                        holdings.add(identity)
                        record_count += 1
                        if record_count > LIMITS["max_holdings_per_run"]:
                            raise McpFailure("MCP_INCOMPLETE_COLLECTION")
                    index.add(data)
                    rows.extend(data)
                    offset = end
                    if not meta["has_more"]:
                        return rows
                raise McpFailure("MCP_INCOMPLETE_COLLECTION")

        tasks = [asyncio.create_task(collect(account)) for account in result.accounts]
        try:
            collections = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for account, rows in zip(result.accounts, collections, strict=True):
            unsupported = Counter(
                row["type"]
                for row in rows
                if row["type"] not in CONTRACT["pagination"]["observed_types"]
            )
            for holding_type, count in unsupported.items():
                result.unsupported_details.append(
                    McpUnsupportedDetail.model_validate(
                        {
                            "account_key": account.account_key,
                            "holding_type": holding_type,
                            "count": count,
                            "reason": "UNSUPPORTED_TYPE",
                        }
                    )
                )
        if result.unsupported_details:
            result.holdings_state = "PARTIAL"
            result.warn("UNVERIFIED_DETAIL")
            return result
        try:
            for account, rows in zip(result.accounts, collections, strict=True):
                for row in rows:
                    self._holding(row, account, index, result)
        except (ValueError, TypeError, KeyError):
            raise McpFailure() from None
        result.holdings_state = "COMPLETE"
        result.warn("UNVERIFIED_DETAIL")
        return result

    def _account(
        self, raw: dict[str, Any], index: ResourceIndex, detail: Detail, now: datetime
    ) -> None:
        attributes = raw.get("attributes", {})
        account_key = key("account_key", account_id=raw["id"])
        link = relation(raw, "institution_connection")
        if link and link["type"] != "institution-connections":
            raise McpFailure("MCP_INCOMPLETE_COLLECTION")
        connection = index.resolve(link)
        connection_key = key("connection_key", **link) if link else None
        connection_state = (
            "NO_CONNECTION" if link is None else "RESOLVED" if connection else "UNRESOLVED"
        )
        if link and not connection:
            detail.warn("MISSING_ENRICHMENT", account_key)
        if connection and connection_key not in {c.connection_key for c in detail.connections}:
            values = connection.get("attributes", {})
            institution_link = relation(connection, "institution")
            if institution_link and institution_link["type"] != "institutions":
                raise McpFailure("MCP_INCOMPLETE_COLLECTION")
            institution = index.resolve(institution_link)
            last_success = values.get("last_successful_sync_at")
            # Source status vocabulary is open. A nonempty error establishes a
            # failed connection without copying its message or guessing status names.
            freshness = "UNKNOWN"
            if values.get("error_message"):
                freshness = "BROKEN"
            elif last_success:
                checked("timestamp", last_success)
                at = datetime.fromisoformat(last_success)
                freshness = (
                    "UNKNOWN"
                    if at > now
                    else "STALE"
                    if now - at > timedelta(hours=48)
                    else "FRESH"
                )
            normalized_connection = McpConnection.model_validate(
                {
                    "connection_key": connection_key,
                    "institution_key": key("institution_key", **institution_link)
                    if institution_link and institution
                    else None,
                    "institution_label": institution.get("attributes", {}).get("name")
                    if institution
                    else None,
                    "source_status": values.get("sync_status"),
                    "last_sync_at": values.get("last_sync_at"),
                    "last_successful_sync_at": last_success,
                    "freshness": freshness,
                }
            )
            if normalized_connection not in detail.connections:
                detail.connections.append(normalized_connection)
            if freshness != "FRESH":
                detail.warn(
                    {
                        "BROKEN": "BROKEN_CONNECTION",
                        "STALE": "STALE_SOURCE",
                        "UNKNOWN": "UNKNOWN_FRESHNESS",
                    }[freshness],
                    connection_key,
                )
        owners = attributes.get("owners")
        detail.accounts.append(
            McpAccount.model_validate(
                {
                    "account_key": account_key,
                    "source_account_id": raw["id"],
                    "resource_type": "assets",
                    "label": attributes.get("name"),
                    "account_type": attributes.get("account_type"),
                    "tax_wrapper": None,
                    "native_balance": money(
                        attributes.get("balance"),
                        attributes.get("currency"),
                        attributes.get("full_value_eur"),
                    ),
                    "full_value_eur": attributes.get("full_value_eur"),
                    "direct_owners_value_eur": attributes.get("total_owned_value_eur"),
                    "total_ownership_share": attributes.get("total_owned_share"),
                    "entity_updated_at": attributes.get("updated_at"),
                    "connection_key": connection_key,
                    "connection_state": connection_state,
                    "ownership_evidence": "EXPLICIT_ENTRIES"
                    if owners is not None
                    else "UNAVAILABLE",
                }
            )
        )
        for owner in owners or []:
            detail.ownership.append(
                McpOwnership.model_validate(
                    {
                        "account_key": account_key,
                        "owner_key": key(
                            "owner_key", owner_type=owner["type"], owner_id=owner["id"]
                        ),
                        "owner_type": owner["type"],
                        "owner_source_id": owner["id"],
                        "owner_label": owner.get("name"),
                        "ownership_share": owner.get("ownership_share"),
                        "owner_value_eur": owner.get("owner_value_eur"),
                    }
                )
            )

    def _holding(
        self, raw: dict[str, Any], account: McpAccount, index: ResourceIndex, detail: Detail
    ) -> None:
        kind, identifier, attributes = raw["type"], raw["id"], raw.get("attributes", {})
        position_key = key(
            "position_key",
            account_id=account.source_account_id,
            holding_type=kind,
            holding_id=identifier,
        )
        product_relation = {
            "security-holdings": "security",
            "crypto-holdings": "currency",
            "fiat-holdings": "currency",
            "scpi-holdings": "scpi",
        }.get(kind)
        link = relation(raw, product_relation) if product_relation else None
        expected_type = {"security": "securities", "currency": "currencies", "scpi": "scpis"}.get(
            product_relation or ""
        )
        if link is not None and link["type"] != expected_type:
            raise McpFailure("MCP_INCOMPLETE_COLLECTION")
        product = index.resolve(link)
        product_attributes = product.get("attributes", {}) if product else {}
        quantity_field = "shares" if kind == "scpi-holdings" else "quantity"
        quantity = (
            attributes.get(quantity_field)
            if kind in {"scpi-holdings", "security-holdings", "crypto-holdings"}
            else None
        )
        detail.positions.append(
            McpPosition.model_validate(
                {
                    "position_key": position_key,
                    "source_asset_id": key(
                        "source_asset_id", holding_type=kind, holding_id=identifier
                    ),
                    "account_key": account.account_key,
                    "holding_type": kind,
                    "holding_id": identifier,
                    "label": product_attributes.get("name"),
                    "product_key": key("product_key", **link) if link and product else None,
                    "quantity": quantity,
                    "quantity_unit": "UNKNOWN"
                    if quantity is None
                    else "SHARES"
                    if kind == "scpi-holdings"
                    else "UNITS",
                    "current_value": money(
                        attributes.get("current_value"), attributes.get("current_value_currency")
                    ),
                    "value_ownership_basis": "UNVERIFIED",
                    "buying_price": money(
                        attributes.get("buying_price"), attributes.get("buying_price_currency")
                    ),
                    "buying_price_basis": "UNVERIFIED",
                    "asset_class": {
                        "fiat-holdings": "CASH",
                        "crypto-holdings": "CRYPTO",
                        "scpi-holdings": "SCPI",
                        "fond-euro-holdings": "LIFE_INSURANCE_FUND",
                    }.get(kind, "OTHER"),
                    "entity_updated_at": attributes.get("updated_at"),
                }
            )
        )
        if link and not product:
            detail.warn("MISSING_ENRICHMENT", position_key)
        fields = []
        if kind == "fond-euro-holdings" and "annual_yield" in attributes:
            fields.append(("annual_yield", attributes["annual_yield"], "ANNUAL"))
        if kind == "security-holdings":
            fields.extend(
                (name, product_attributes[name], "UNVERIFIED")
                for name in ("expense_ratio", "subscription_fees_ratio")
                if name in product_attributes
            )
        for name, value, period in fields:
            detail.position_rates.append(
                McpPositionRate.model_validate(
                    {
                        "position_key": position_key,
                        "source_field": name,
                        "value": value,
                        "unit": "UNVERIFIED",
                        "period": period,
                    }
                )
            )
