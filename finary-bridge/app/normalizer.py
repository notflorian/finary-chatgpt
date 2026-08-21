"""Pure transformations from adapter-owned Finary records to stable models."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.finary_client import (
    FinaryFeatureUnavailableError,
    FinaryLiabilityCoverage,
    FinaryPositionKind,
    FinaryRawAccounts,
    FinaryRawLiabilities,
    FinaryRawPositions,
)
from app.models import Account, AssetClass, Liability, Position

_CURRENCY_PATTERN: Final = re.compile(r"^[A-Z]{3}$")


class SnapshotNormalizationError(Exception):
    """Upstream data cannot be converted into a truthful stable snapshot."""

    code = "SNAPSHOT_VALIDATION_FAILED"
    retryable = False


@dataclass(frozen=True, slots=True)
class _PositionFields:
    name: str | None
    ticker: str | None
    isin: str | None
    market_currency: str | None
    cost_currency: str | None
    asset_class: AssetClass


def canonicalize_id(value: object, *, field_name: str) -> str:
    """Convert verified string or integer upstream identifiers to strings."""

    if isinstance(value, bool):
        raise SnapshotNormalizationError(f"{field_name} must be a string or integer")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise SnapshotNormalizationError(f"{field_name} must be a non-empty string or integer")


def make_account_key(account_id: object) -> str:
    """Build the stable account key."""

    return f"finary:account:{canonicalize_id(account_id, field_name='account id')}"


def make_source_asset_id(kind: FinaryPositionKind, asset_id: object) -> str:
    """Build a category-aware source asset identifier."""

    canonical_id = canonicalize_id(asset_id, field_name="position id")
    return f"{kind.value}:{canonical_id}"


def make_position_key(
    account_id: object, kind: FinaryPositionKind, asset_id: object
) -> str:
    """Build a category-aware stable position key."""

    canonical_account_id = canonicalize_id(account_id, field_name="account id")
    canonical_asset_id = canonicalize_id(asset_id, field_name="position id")
    return f"finary:{canonical_account_id}:asset:{kind.value}:{canonical_asset_id}"


def normalize_accounts(raw_accounts: FinaryRawAccounts) -> tuple[Account, ...]:
    """Normalize accounts without traversing any nested asset arrays."""

    normalized: list[Account] = []
    seen_ids: set[str] = set()
    for record in raw_accounts.records:
        account_id = canonicalize_id(record.get("id"), field_name="account id")
        if account_id in seen_ids:
            raise SnapshotNormalizationError("duplicate account id")
        seen_ids.add(account_id)

        currency = _currency_from_container(record.get("currency"), "account currency")
        if currency is None:
            raise SnapshotNormalizationError("account currency is required")
        balance = _required_number(record.get("balance"), "account balance")
        account = Account(
            account_key=make_account_key(account_id),
            source_account_id=account_id,
            name=_required_text(record.get("name"), "account name"),
            institution=_nested_text(record.get("institution"), "name", "institution"),
            account_type=_account_type(record),
            owner=None,
            currency=currency,
            market_value_eur=balance if currency == "EUR" else None,
            metadata={},
        )
        normalized.append(account)
    return tuple(normalized)


def normalize_positions(
    raw_positions: FinaryRawPositions,
    *,
    account_keys: set[str],
) -> tuple[Position, ...]:
    """Normalize only dedicated position collections from the adapter."""

    normalized: list[Position] = []
    seen_groups: set[FinaryPositionKind] = set()
    seen_source_ids: set[str] = set()
    seen_position_keys: set[str] = set()

    for group in raw_positions.groups:
        if group.kind in seen_groups:
            raise SnapshotNormalizationError("duplicate position collection")
        seen_groups.add(group.kind)
        if not group.records:
            continue
        if group.kind not in _POSITION_EXTRACTORS:
            raise SnapshotNormalizationError(
                f"position kind {group.kind.value} has no verified normalization rule"
            )

        for record in group.records:
            position = _normalize_position(group.kind, record, account_keys)
            if position.source_asset_id in seen_source_ids:
                raise SnapshotNormalizationError(
                    "duplicate position id inside an asset-category namespace"
                )
            if position.position_key in seen_position_keys:
                raise SnapshotNormalizationError("duplicate position key")
            seen_source_ids.add(position.source_asset_id)
            seen_position_keys.add(position.position_key)
            normalized.append(position)
    return tuple(normalized)


def normalize_liabilities(
    raw_liabilities: FinaryRawLiabilities,
) -> tuple[Liability, ...]:
    """Accept a verified-complete empty collection without inventing a schema."""

    if raw_liabilities.coverage is not FinaryLiabilityCoverage.COMPLETE:
        raise FinaryFeatureUnavailableError(
            "Liability coverage is not verified complete"
        )
    if raw_liabilities.records:
        raise SnapshotNormalizationError(
            "non-empty liabilities have no verified normalization rule"
        )
    return ()


def normalize_liabilities_v2(
    raw_liabilities: FinaryRawLiabilities,
) -> tuple[Liability, ...]:
    """Normalize liabilities under the explicit v2 coverage contract.

    The verified adapter has no non-empty liability schema yet. Incomplete
    coverage is represented truthfully by v2 instead of being converted to a
    zero total. Any records that cannot be normalized remain a hard failure.
    """

    if raw_liabilities.coverage is FinaryLiabilityCoverage.COMPLETE:
        return normalize_liabilities(raw_liabilities)
    if raw_liabilities.records:
        raise SnapshotNormalizationError(
            "incomplete liability coverage cannot contain authoritative records"
        )
    return ()


def calculate_gross_assets_eur(
    raw_accounts: FinaryRawAccounts,
    normalized_accounts: Sequence[Account],
) -> float:
    """Sum only non-collection account balances with proven EUR currency.

    Account balances are the sole gross-assets source. Dedicated position values
    are intentionally excluded because they overlap the account balances.
    """

    if len(raw_accounts.records) != len(normalized_accounts):
        raise SnapshotNormalizationError("account normalization count mismatch")

    gross_assets = 0.0
    for record, account in zip(raw_accounts.records, normalized_accounts, strict=True):
        is_collection = record.get("is_collection")
        if is_collection is not None and not isinstance(is_collection, bool):
            raise SnapshotNormalizationError("account is_collection must be boolean")
        if is_collection is True:
            continue
        if account.market_value_eur is None:
            raise SnapshotNormalizationError(
                "gross asset account balance lacks verified EUR provenance"
            )
        gross_assets += account.market_value_eur

    if not math.isfinite(gross_assets) or gross_assets < 0:
        raise SnapshotNormalizationError("gross assets must be a finite non-negative value")
    return gross_assets


def _normalize_position(
    kind: FinaryPositionKind,
    record: Mapping[str, object],
    account_keys: set[str],
) -> Position:
    position_id = canonicalize_id(record.get("id"), field_name="position id")
    account_id = canonicalize_id(
        record.get("holdings_account_id"), field_name="holdings_account_id"
    )
    account_key = make_account_key(account_id)
    if account_key not in account_keys:
        raise SnapshotNormalizationError("position references an unknown account")

    fields = _POSITION_EXTRACTORS[kind](record)
    quantity_value = record.get("quantity")
    if kind is FinaryPositionKind.SCPIS and quantity_value is None:
        quantity_value = record.get("shares")
    quantity = _optional_number(quantity_value, "position quantity")
    unit_price = _optional_number(record.get("current_price"), "position current price")
    current_value = _required_number(record.get("current_value"), "position current value")
    buying_value = _optional_number(record.get("buying_value"), "position buying value")

    return Position(
        position_key=make_position_key(account_id, kind, position_id),
        source_asset_id=make_source_asset_id(kind, position_id),
        account_key=account_key,
        name=fields.name,
        ticker=fields.ticker,
        isin=fields.isin,
        asset_class=fields.asset_class,
        asset_subclass=None,
        region=None,
        quantity=quantity,
        unit_price=unit_price,
        currency=fields.market_currency,
        fx_to_eur=1.0 if fields.market_currency == "EUR" else None,
        market_value_native=current_value,
        market_value_eur=current_value if fields.market_currency == "EUR" else None,
        cost_basis_eur=buying_value if fields.cost_currency == "EUR" else None,
        unrealized_pnl_eur=None,
        unrealized_pnl_pct=None,
        metadata={},
    )


def _extract_security(record: Mapping[str, object]) -> _PositionFields:
    security = _required_mapping(record.get("security"), "security")
    currency = _currency_from_container(security.get("currency"), "security currency")
    return _PositionFields(
        name=_optional_text(security.get("name"), "security name"),
        ticker=_optional_text(security.get("symbol"), "security symbol"),
        isin=_optional_text(security.get("isin"), "security ISIN"),
        market_currency=currency,
        cost_currency=currency,
        asset_class=AssetClass.OTHER,
    )


def _extract_crypto(record: Mapping[str, object]) -> _PositionFields:
    crypto = _required_mapping(record.get("crypto"), "crypto")
    cost_currency = _currency_from_container(
        record.get("buying_price_currency"), "crypto buying-price currency"
    )
    return _PositionFields(
        name=_optional_text(crypto.get("name"), "crypto name"),
        ticker=_optional_text(crypto.get("code"), "crypto code"),
        isin=None,
        market_currency=None,
        cost_currency=cost_currency,
        asset_class=AssetClass.CRYPTO,
    )


def _extract_euro_fund(record: Mapping[str, object]) -> _PositionFields:
    currency = _currency_from_container(record.get("currency"), "euro-fund currency")
    return _PositionFields(
        name=_optional_text(record.get("name"), "euro-fund name"),
        ticker=None,
        isin=None,
        market_currency=currency,
        cost_currency=currency,
        asset_class=AssetClass.LIFE_INSURANCE_FUND,
    )


def _extract_generic_asset(record: Mapping[str, object]) -> _PositionFields:
    currency = _currency_from_container(record.get("currency"), "generic-asset currency")
    return _PositionFields(
        name=_optional_text(record.get("name"), "generic-asset name"),
        ticker=None,
        isin=None,
        market_currency=currency,
        cost_currency=currency,
        asset_class=AssetClass.OTHER,
    )


def _extract_real_estate(record: Mapping[str, object]) -> _PositionFields:
    currency = _currency_from_container(record.get("currency"), "real-estate currency")
    return _PositionFields(
        name=_optional_text(record.get("name"), "real-estate name"),
        ticker=None,
        isin=None,
        market_currency=currency,
        cost_currency=currency,
        asset_class=AssetClass.REAL_ESTATE,
    )


def _extract_scpi(record: Mapping[str, object]) -> _PositionFields:
    scpi = _required_mapping(record.get("scpi"), "SCPI")
    return _PositionFields(
        name=_optional_text(scpi.get("name"), "SCPI name"),
        ticker=None,
        isin=None,
        market_currency=None,
        cost_currency=None,
        asset_class=AssetClass.SCPI,
    )


_POSITION_EXTRACTORS: Final = {
    FinaryPositionKind.SECURITIES: _extract_security,
    FinaryPositionKind.CRYPTOS: _extract_crypto,
    FinaryPositionKind.EURO_FUNDS: _extract_euro_fund,
    FinaryPositionKind.GENERIC_ASSETS: _extract_generic_asset,
    FinaryPositionKind.REAL_ESTATES: _extract_real_estate,
    FinaryPositionKind.SCPIS: _extract_scpi,
}


def _account_type(record: Mapping[str, object]) -> str:
    for key in ("holdings_account_type", "bank_account_type"):
        value = record.get(key)
        if value is None:
            continue
        account_type = _nested_text(value, "name", key)
        if account_type:
            return account_type
    manual_type = _optional_text(record.get("manual_type"), "manual account type")
    return manual_type or "OTHER"


def _currency_from_container(value: object, description: str) -> str | None:
    if value is None:
        return None
    container = _required_mapping(value, description)
    code = _optional_text(container.get("code"), f"{description} code")
    if code is None:
        return None
    if _CURRENCY_PATTERN.fullmatch(code) is None:
        raise SnapshotNormalizationError(f"{description} code must be ISO-like uppercase")
    return code


def _nested_text(value: object, key: str, description: str) -> str | None:
    if value is None:
        return None
    container = _required_mapping(value, description)
    return _optional_text(container.get(key), f"{description} {key}")


def _required_mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SnapshotNormalizationError(f"{description} must be an object")
    return value


def _required_text(value: object, description: str) -> str:
    text = _optional_text(value, description)
    if text is None:
        raise SnapshotNormalizationError(f"{description} is required")
    return text


def _optional_text(value: object, description: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SnapshotNormalizationError(f"{description} must be a string")
    text = value.strip()
    return text or None


def _required_number(value: object, description: str) -> float:
    number = _optional_number(value, description)
    if number is None:
        raise SnapshotNormalizationError(f"{description} is required")
    return number


def _optional_number(value: object, description: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SnapshotNormalizationError(f"{description} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise SnapshotNormalizationError(f"{description} must be finite")
    return number
