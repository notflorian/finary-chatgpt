"""Orchestration service for one normalized portfolio snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.finary_client import FinaryClient, FinaryLiabilityCoverage, FinaryRawLiabilities
from app.models import (
    Account,
    LiabilityCoverage,
    PortfolioSnapshot,
    PortfolioSnapshotV2,
    Position,
    SnapshotCoverage,
)
from app.normalizer import (
    SnapshotNormalizationError,
    calculate_gross_assets_eur,
    normalize_accounts,
    normalize_liabilities,
    normalize_liabilities_v2,
    normalize_positions,
)


def _paris_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Europe/Paris"))


@dataclass(frozen=True, slots=True)
class _NormalizedAssets:
    accounts: tuple[Account, ...]
    positions: tuple[Position, ...]
    gross_assets_eur: float
    raw_liabilities: FinaryRawLiabilities


class SnapshotService:
    """Retrieve adapter data and build the stable downstream contract."""

    def __init__(
        self,
        client: FinaryClient,
        *,
        clock: Callable[[], datetime] = _paris_now,
    ) -> None:
        self._client = client
        self._clock = clock

    def get_snapshot(self) -> PortfolioSnapshot:
        """Build a validated snapshot or propagate sanitized application errors."""

        assets = self._get_normalized_assets()

        try:
            liabilities = normalize_liabilities(assets.raw_liabilities)
            liabilities_eur = sum(
                liability.outstanding_eur for liability in liabilities
            )

            return PortfolioSnapshot(
                generated_at=self._clock(),
                gross_assets_eur=assets.gross_assets_eur,
                liabilities_eur=liabilities_eur,
                net_worth_eur=assets.gross_assets_eur - liabilities_eur,
                accounts=assets.accounts,
                positions=assets.positions,
                liabilities=liabilities,
            )
        except ValidationError:
            raise SnapshotNormalizationError(
                "normalized snapshot model validation failed"
            ) from None

    def get_snapshot_v2(self) -> PortfolioSnapshotV2:
        """Build a coverage-aware v2 snapshot from the same normalized assets."""

        assets = self._get_normalized_assets()

        try:
            liabilities = normalize_liabilities_v2(assets.raw_liabilities)
            coverage = _liability_coverage(assets.raw_liabilities)
            liabilities_eur = (
                sum(liability.outstanding_eur for liability in liabilities)
                if coverage is LiabilityCoverage.COMPLETE
                else None
            )
            net_worth_eur = (
                assets.gross_assets_eur - liabilities_eur
                if liabilities_eur is not None
                else None
            )

            return PortfolioSnapshotV2(
                generated_at=self._clock(),
                coverage=SnapshotCoverage(liabilities=coverage),
                gross_assets_eur=assets.gross_assets_eur,
                liabilities_eur=liabilities_eur,
                net_worth_eur=net_worth_eur,
                accounts=assets.accounts,
                positions=assets.positions,
                liabilities=liabilities,
            )
        except ValidationError:
            raise SnapshotNormalizationError(
                "normalized snapshot model validation failed"
            ) from None

    def _get_normalized_assets(self) -> _NormalizedAssets:
        """Retrieve once and normalize the version-independent asset state."""

        self._client.authenticate()
        raw_accounts = self._client.get_accounts()
        raw_positions = self._client.get_positions()
        raw_liabilities = self._client.get_liabilities()
        try:
            accounts = normalize_accounts(raw_accounts)
            account_keys = {account.account_key for account in accounts}
            positions = normalize_positions(raw_positions, account_keys=account_keys)
            gross_assets_eur = calculate_gross_assets_eur(raw_accounts, accounts)
        except ValidationError:
            raise SnapshotNormalizationError(
                "normalized snapshot model validation failed"
            ) from None
        return _NormalizedAssets(
            accounts=accounts,
            positions=positions,
            gross_assets_eur=gross_assets_eur,
            raw_liabilities=raw_liabilities,
        )


def _liability_coverage(raw: FinaryRawLiabilities) -> LiabilityCoverage:
    return {
        FinaryLiabilityCoverage.COMPLETE: LiabilityCoverage.COMPLETE,
        FinaryLiabilityCoverage.PARTIAL: LiabilityCoverage.PARTIAL,
        FinaryLiabilityCoverage.UNAVAILABLE: LiabilityCoverage.UNAVAILABLE,
    }[raw.coverage]
