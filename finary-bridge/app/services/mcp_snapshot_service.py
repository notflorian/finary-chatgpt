"""Authoritative observation assembly, separate from legacy detail-sum semantics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.mcp_adapter import McpAdapter
from app.mcp_client import McpFailure, NativeMcpClient
from app.mcp_models import McpSnapshotV3


def paris_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Paris"))


class McpSnapshotService:
    def __init__(
        self,
        client: NativeMcpClient,
        *,
        clock: Callable[[], datetime] = paris_now,
        page_limit: int = 100,
    ) -> None:
        self.client, self.clock, self.page_limit = client, clock, page_limit

    async def snapshot(self) -> McpSnapshotV3:
        started = self.clock()
        async with self.client.session(("get_portfolio_overview",)) as session:
            adapter = McpAdapter(session, page_limit=self.page_limit)
            official = await adapter.overview()
            detail = await adapter.detail(self.clock())
        ended = self.clock()
        generated = self.clock()
        overview = official.overview
        if overview.source_completeness == "assets_only":
            debt_valuation, quality = "UNAVAILABLE", "ASSETS_ONLY"
        elif overview.unvalued_liability_count:
            debt_valuation, quality = "PARTIAL", "REPORTED_UNVALUED_DEBT"
            detail.warn("UNVALUED_DEBT")
        else:
            debt_valuation, quality = "COMPLETE", "REPORTED_COMPLETE"
        accounts = [a.model_dump() for a in detail.accounts]
        positions = [p.model_dump() for p in detail.positions]

        def valuation(rows: list[dict], name: str, retrieval: str) -> str:  # type: ignore[type-arg]
            if retrieval != "COMPLETE":
                return "UNAVAILABLE"
            known = sum(
                row[name]["amount"] is not None and row[name]["currency"] is not None
                for row in rows
            )
            return "COMPLETE" if known == len(rows) else "PARTIAL" if known else "UNAVAILABLE"

        try:
            return McpSnapshotV3.model_validate(
                {
                    "schema_version": "3.0",
                    "observation_id": str(uuid4()),
                    "snapshot_date": generated.astimezone(ZoneInfo("Europe/Paris"))
                    .date()
                    .isoformat(),
                    "generated_at": generated.isoformat(),
                    "provenance": {
                        "provider": "finary_official_mcp",
                        "source_contract_version": "1.0.0",
                        "scope": "household",
                        "ownership_basis": "direct",
                        "metric": "gross_assets",
                        "currency": official.currency,
                        "collection_started_at": started.isoformat(),
                        "collection_ended_at": ended.isoformat(),
                        "atomicity": "COLLECTION_WINDOW",
                        "upstream_as_of": None,
                    },
                    "coverage": {
                        "accounts": detail.accounts_state,
                        "holdings": detail.holdings_state,
                        "debt_detail": "UNAVAILABLE",
                        "debt_detail_basis": "UNVERIFIED",
                        "account_valuation": valuation(
                            accounts, "native_balance", detail.accounts_state
                        ),
                        "holding_valuation": valuation(
                            positions, "current_value", detail.holdings_state
                        ),
                        "debt_valuation": debt_valuation,
                        "overview_quality": quality,
                        "detail_semantics": "UNVERIFIED",
                        "source_freshness": detail.source_freshness,
                    },
                    "overview": overview.model_dump(),
                    "accounts": accounts,
                    "positions": positions,
                    "ownership": [o.model_dump() for o in detail.ownership],
                    "connections": [c.model_dump() for c in detail.connections],
                    "position_rates": [r.model_dump() for r in detail.position_rates],
                    "allocation_categories": [c.model_dump() for c in official.categories],
                    "allocation_types": [t.model_dump() for t in official.types],
                    "members": [m.model_dump() for m in official.members],
                    "debt_details": [],
                    "warnings": [w.model_dump() for w in detail.warnings],
                    "unsupported_details": [d.model_dump() for d in detail.unsupported_details],
                }
            )
        except ValueError:
            raise McpFailure("SNAPSHOT_VALIDATION_FAILED") from None
