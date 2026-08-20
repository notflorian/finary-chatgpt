"""Orchestration service for one normalized portfolio snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.finary_client import FinaryClient
from app.models import PortfolioSnapshot
from app.normalizer import (
    SnapshotNormalizationError,
    calculate_gross_assets_eur,
    normalize_accounts,
    normalize_liabilities,
    normalize_positions,
)


def _paris_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Europe/Paris"))


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

        self._client.authenticate()
        raw_accounts = self._client.get_accounts()
        raw_positions = self._client.get_positions()
        raw_liabilities = self._client.get_liabilities()

        try:
            accounts = normalize_accounts(raw_accounts)
            account_keys = {account.account_key for account in accounts}
            positions = normalize_positions(raw_positions, account_keys=account_keys)
            liabilities = normalize_liabilities(raw_liabilities)
            gross_assets_eur = calculate_gross_assets_eur(raw_accounts, accounts)
            liabilities_eur = sum(
                liability.outstanding_eur for liability in liabilities
            )

            return PortfolioSnapshot(
                generated_at=self._clock(),
                gross_assets_eur=gross_assets_eur,
                liabilities_eur=liabilities_eur,
                net_worth_eur=gross_assets_eur - liabilities_eur,
                accounts=accounts,
                positions=positions,
                liabilities=liabilities,
            )
        except ValidationError:
            raise SnapshotNormalizationError(
                "normalized snapshot model validation failed"
            ) from None
