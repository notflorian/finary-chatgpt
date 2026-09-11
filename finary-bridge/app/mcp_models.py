"""Generated from the reviewed MCP contract; run scripts/build-mcp-models.py."""

from __future__ import annotations

from typing import ClassVar, Literal

from app.mcp_validation import ContractModel


class McpMoney(ContractModel):
    contract_name: ClassVar[str] = "money"
    amount: str | None
    currency: str | None
    amount_eur: str | None
    eur_basis: Literal["SOURCE_EUR", "SOURCE_CONVERSION", "UNAVAILABLE"]


class McpProvenance(ContractModel):
    contract_name: ClassVar[str] = "provenance"
    provider: Literal["finary_official_mcp"]
    source_contract_version: Literal["1.0.0"]
    scope: Literal["household"]
    ownership_basis: Literal["direct"]
    metric: Literal["gross_assets"]
    currency: str
    collection_started_at: str
    collection_ended_at: str
    atomicity: Literal["COLLECTION_WINDOW"]
    upstream_as_of: str | None


class McpCoverage(ContractModel):
    contract_name: ClassVar[str] = "coverage"
    accounts: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    holdings: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    debt_detail: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    account_valuation: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    holding_valuation: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    debt_valuation: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    overview_quality: Literal["REPORTED_COMPLETE", "REPORTED_UNVALUED_DEBT", "ASSETS_ONLY"]
    detail_semantics: Literal["SUPPORTED", "UNVERIFIED", "INCONSISTENT"]
    source_freshness: Literal["FRESH", "STALE", "BROKEN", "UNKNOWN", "NOT_APPLICABLE"]
    debt_detail_basis: Literal["UNVERIFIED", "INDEPENDENT_EMPTY_ENUMERATION"]


class McpOverview(ContractModel):
    contract_name: ClassVar[str] = "overview"
    gross_assets: McpMoney
    financial_assets: McpMoney
    reported_liabilities: McpMoney
    reported_net_worth: McpMoney
    unvalued_liability_count: int
    source_completeness: Literal["complete", "assets_only"]
    preferred_wealth_metric: str | None


class McpAccount(ContractModel):
    contract_name: ClassVar[str] = "account"
    account_key: str
    source_account_id: str
    resource_type: Literal["assets"]
    label: str | None
    account_type: str | None
    tax_wrapper: str | None
    native_balance: McpMoney
    full_value_eur: str | None
    direct_owners_value_eur: str | None
    total_ownership_share: str | None
    entity_updated_at: str | None
    connection_key: str | None
    connection_state: Literal["NO_CONNECTION", "RESOLVED", "UNRESOLVED"]
    ownership_evidence: Literal["EXPLICIT_ENTRIES", "UNAVAILABLE"]


class McpOwnership(ContractModel):
    contract_name: ClassVar[str] = "ownership"
    account_key: str
    owner_key: str
    owner_type: str
    owner_source_id: str
    owner_label: str | None
    ownership_share: str | None
    owner_value_eur: str | None


class McpConnection(ContractModel):
    contract_name: ClassVar[str] = "connection"
    connection_key: str
    institution_key: str | None
    institution_label: str | None
    source_status: str | None
    last_sync_at: str | None
    last_successful_sync_at: str | None
    freshness: Literal["FRESH", "STALE", "BROKEN", "UNKNOWN", "NOT_APPLICABLE"]


class McpPosition(ContractModel):
    contract_name: ClassVar[str] = "position"
    position_key: str
    source_asset_id: str
    account_key: str
    holding_type: str
    holding_id: str
    label: str | None
    product_key: str | None
    quantity: str | None
    quantity_unit: Literal["UNITS", "SHARES", "UNKNOWN"]
    current_value: McpMoney
    value_ownership_basis: Literal["DIRECT_OWNERS_COMBINED", "UNVERIFIED"]
    buying_price: McpMoney
    buying_price_basis: Literal["UNVERIFIED"]
    asset_class: Literal[
        "EQUITY",
        "BOND",
        "CASH",
        "REAL_ESTATE",
        "SCPI",
        "PRIVATE_EQUITY",
        "CRYPTO",
        "COMMODITY",
        "LIFE_INSURANCE_FUND",
        "OTHER",
    ]
    entity_updated_at: str | None


class McpPositionRate(ContractModel):
    contract_name: ClassVar[str] = "position_rate"
    position_key: str
    source_field: Literal[
        "annual_yield", "annual_yield_percent", "expense_ratio", "subscription_fees_ratio"
    ]
    value: str | None
    unit: Literal["PERCENT", "FRACTION", "UNVERIFIED"]
    period: Literal["ANNUAL", "UNVERIFIED"]


class McpAllocationCategory(ContractModel):
    contract_name: ClassVar[str] = "allocation_category"
    category: str
    value: McpMoney


class McpAllocationType(ContractModel):
    contract_name: ClassVar[str] = "allocation_type"
    category: str
    holding_type: str
    value: McpMoney


class McpMember(ContractModel):
    contract_name: ClassVar[str] = "member"
    member_ordinal: int
    label: str | None
    gross_assets: McpMoney
    reported_liabilities: McpMoney
    reported_net_worth: McpMoney
    unvalued_liability_count: int


class McpWarning(ContractModel):
    contract_name: ClassVar[str] = "warning"
    code: Literal[
        "OWNERSHIP_WORDING_CONFLICT",
        "UNVERIFIED_DETAIL",
        "INCOMPLETE_DETAIL",
        "UNVALUED_DEBT",
        "STALE_SOURCE",
        "BROKEN_CONNECTION",
        "UNKNOWN_FRESHNESS",
        "MISSING_ENRICHMENT",
        "BUDGET_HISTORY_INCONSISTENT",
        "UNRESOLVED_CROSSWALK",
    ]
    entity_key: str | None


class McpUnsupportedDetail(ContractModel):
    contract_name: ClassVar[str] = "unsupported_detail"
    account_key: str
    holding_type: str
    count: int
    reason: Literal["UNSUPPORTED_TYPE", "UNVERIFIED_FIELDS", "UNVERIFIED_LOAN"]


class McpSnapshotV3(ContractModel):
    contract_name: ClassVar[str] = "snapshot_v3"
    schema_version: Literal["3.0"]
    observation_id: str
    snapshot_date: str
    generated_at: str
    provenance: McpProvenance
    coverage: McpCoverage
    overview: McpOverview
    accounts: list[McpAccount]
    ownership: list[McpOwnership]
    connections: list[McpConnection]
    positions: list[McpPosition]
    position_rates: list[McpPositionRate]
    allocation_categories: list[McpAllocationCategory]
    allocation_types: list[McpAllocationType]
    members: list[McpMember]
    debt_details: list[None]
    warnings: list[McpWarning]
    unsupported_details: list[McpUnsupportedDetail]
