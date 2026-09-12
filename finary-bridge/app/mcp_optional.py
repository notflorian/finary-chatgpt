"""On-demand budget, label aggregates and complete goal plans at the MCP boundary."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.mcp_client import McpFailure, NativeMcpClient, checked
from app.mcp_validation import CONTRACT, key, validate

DecimalText = Annotated[
    str,
    Field(
        pattern=CONTRACT["$defs"]["decimal"]["pattern"],
        max_length=CONTRACT["$defs"]["decimal"]["maxLength"],
    ),
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Count = Annotated[int, Field(ge=0)]


class OptionalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class ReadContext(OptionalModel):
    schema_version: Literal["3.0"] = "3.0"
    provider: Literal["finary_official_mcp"] = "finary_official_mcp"
    source_contract_version: Literal["1.1.0"] = "1.1.0"
    observation_id: str
    generated_at: str


class PeriodRequest(OptionalModel):
    period: Literal["this_month", "last_month", "last_3_months", "year_to_date"] = "this_month"
    start_date: str | None = None
    end_date: str | None = None

    def arguments(self, today: date) -> dict[str, Any]:
        arguments = self.model_dump(exclude_none=True)
        try:
            validate("search_input" if "query" in arguments else "period_input", arguments)
            if self.start_date is not None and (
                not date.fromisoformat(self.start_date)
                <= date.fromisoformat(self.end_date or "")
                <= today
            ):
                raise ValueError
            return arguments
        except ValueError:
            raise McpFailure("MCP_INVALID_ARGUMENT") from None


class SearchRequest(PeriodRequest):
    query: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
    direction: Literal["spending", "income"] | None = None


class PeriodView(OptionalModel):
    currency: Currency
    start_date: str
    end_date: str

    @model_validator(mode="after")
    def dates(self) -> PeriodView:
        validate("date", self.start_date)
        validate("date", self.end_date)
        if self.start_date > self.end_date:
            raise ValueError("Invalid returned period")
        return self


class BudgetView(PeriodView):
    is_partial: bool
    elapsed_days: Count
    total_days: Count
    history_from: str | None
    history_to: str | None


class BudgetTarget(OptionalModel):
    entered_amount: DecimalText
    currency: None = None
    currency_evidence: Literal["UNVERIFIED"] = "UNVERIFIED"
    should_reach: bool


class Category(OptionalModel):
    slug: str
    is_user_authored: bool
    currency: Currency
    family_expense: DecimalText
    family_income: DecimalText
    transactions_count: Count
    label_en: str | None
    label_fr: str | None
    monthly_average_expenses: DecimalText | None
    monthly_average_denominator: Literal[12] = 12
    share_of_expenses_percent: DecimalText | None
    target: BudgetTarget | None


class Monthly(OptionalModel):
    month: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    currency: Currency
    family_expense: DecimalText
    family_income: DecimalText
    family_net_cashflow: DecimalText


class Attribution(OptionalModel):
    name: str | None
    currency: Currency
    family_expense: DecimalText
    family_income: DecimalText
    transactions_count: Count
    unpriced_transactions_count: Count


class Comparison(PeriodView):
    family_expense_total: DecimalText
    family_income_total: DecimalText
    family_net_cashflow: DecimalText
    expenses_change_percent: DecimalText | None


class ExpenseSplit(OptionalModel):
    currency: Currency
    family_recurring_expense: DecimalText
    family_variable_expense: DecimalText
    recurring_share_percent: DecimalText | None


class Recurring(OptionalModel):
    detected_count: Count
    unpriced_count: Count
    family_monthly_equivalent: None = None
    value_semantics: Literal["UNVERIFIED"] = "UNVERIFIED"


class BudgetResponse(ReadContext):
    view: BudgetView
    population: Literal["CALLER_CONFIGURED_WHOLE_HOUSEHOLD"] = "CALLER_CONFIGURED_WHOLE_HOUSEHOLD"
    family_expense_total: DecimalText
    family_income_total: DecimalText
    family_net_cashflow: DecimalText
    family_savings_rate_percent: DecimalText | None
    transactions_count: Count
    unpriced_transactions_count: Count
    by_category: list[Category]
    by_month: list[Monthly]
    by_profile: list[Attribution]
    joint: Attribution | None
    comparison: Comparison | None
    expense_split: ExpenseSplit
    monthly_average_months_covered: Annotated[int, Field(ge=0, le=12)]
    recurring_charges: Recurring | None
    targets_status: Literal["RETURNED", "UNAVAILABLE", "UNVERIFIED"]
    history_quality: Literal["SUPPORTED", "UNVERIFIED", "INCONSISTENT", "OUTSIDE_HISTORY"]
    trend_certified: Literal[False] = False
    limitations: list[
        Literal[
            "UNVERIFIED_SOURCE_NOTES",
            "UNPRICED_TRANSACTIONS",
            "UNVERIFIED_RECURRING_VALUE",
            "UNKNOWN_TARGET_CURRENCY",
            "WHOLE_JOINT_AMOUNTS",
        ]
    ]


class SearchResponse(ReadContext):
    view: PeriodView
    matched_query: Annotated[str, Field(min_length=1, pattern=r"\S")]
    matched_direction: str | None
    matched_expense_total: DecimalText
    matched_income_total: DecimalText
    matched_transactions_count: Count
    unpriced_transactions_count: Count
    result_kind: Literal["LABEL_SUBSTRING_AGGREGATE"] = "LABEL_SUBSTRING_AGGREGATE"


class SafetyNet(OptionalModel):
    kind: Literal["safety_net"]
    monthly_expenses_amount: DecimalText | None
    target_coverage_months: DecimalText | None


class LifeProject(OptionalModel):
    kind: Literal["life_project"]
    target_amount: DecimalText | None
    contribution_amount: DecimalText | None
    contribution_frequency: str | None


class UnavailablePlan(OptionalModel):
    kind: Literal["unavailable"]


class Goal(OptionalModel):
    name: str
    goal_type: str
    currency: Currency
    target_month: str | None
    target_precision: Literal["MONTH_ATTRIBUTED"] = "MONTH_ATTRIBUTED"
    created_at: str
    contributor_labels: list[str | None]
    funding_account_keys: list[str]
    unresolved_funding_count: Count
    plan: SafetyNet | LifeProject | UnavailablePlan


class GoalsResponse(ReadContext):
    response_coverage: Literal["COMPLETE"] = "COMPLETE"
    identity_basis: Literal["COMPLETE_RESPONSE_ONLY"] = "COMPLETE_RESPONSE_ONLY"
    funding_reference_coverage: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    goals: list[Goal]


def context(now: datetime) -> dict[str, Any]:
    return {"observation_id": str(uuid4()), "generated_at": now.isoformat()}


def select(row: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: row.get(name) for name in names}


def view(raw: dict[str, Any]) -> dict[str, Any]:
    return {"currency": raw["currency"], "start_date": raw["from"], "end_date": raw["to"]}


def normalize_budget(raw: dict[str, Any], now: datetime) -> BudgetResponse:
    checked("budget_view_observed", raw["view"])
    currency = checked("currency", raw["view"]["currency"])
    period_view = {
        **view(raw["view"]),
        **select(
            raw["view"], ("is_partial", "elapsed_days", "total_days", "history_from", "history_to")
        ),
    }
    start, end = period_view["history_from"], period_view["history_to"]
    quality = "UNVERIFIED"
    if start is not None and end is not None:
        checked("date", start)
        checked("date", end)
        quality = (
            "INCONSISTENT"
            if start > end
            else "OUTSIDE_HISTORY"
            if period_view["end_date"] < start or period_view["start_date"] > end
            else "UNVERIFIED"
        )
    if (
        period_view["elapsed_days"] > period_view["total_days"]
        or raw["unpriced_transactions_count"] > raw["transactions_count"]
    ):
        quality = "INCONSISTENT"
    categories = []
    for row in raw["by_category"]:
        category = select(
            row,
            (
                "slug",
                "is_user_authored",
                "family_expense",
                "family_income",
                "transactions_count",
                "label_en",
                "label_fr",
                "monthly_average_expenses",
                "share_of_expenses_percent",
            ),
        )
        category.update(
            currency=currency,
            target={
                "entered_amount": row["target"]["amount"],
                "should_reach": row["target"]["should_reach"],
            }
            if row.get("target") is not None
            else None,
        )
        categories.append(category)

    def attribution(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **select(
                row,
                (
                    "name",
                    "family_expense",
                    "family_income",
                    "transactions_count",
                    "unpriced_transactions_count",
                ),
            ),
            "currency": currency,
        }

    comparison = raw.get("comparison")
    recurring = raw.get("recurring_charges")
    limits = ["UNVERIFIED_SOURCE_NOTES", "UNKNOWN_TARGET_CURRENCY", "WHOLE_JOINT_AMOUNTS"]
    if raw["unpriced_transactions_count"]:
        limits.append("UNPRICED_TRANSACTIONS")
    if recurring is not None:
        limits.append("UNVERIFIED_RECURRING_VALUE")
    return BudgetResponse.model_validate(
        {
            **context(now),
            "view": period_view,
            **select(
                raw,
                (
                    "family_expense_total",
                    "family_income_total",
                    "family_net_cashflow",
                    "family_savings_rate_percent",
                    "transactions_count",
                    "unpriced_transactions_count",
                    "monthly_average_months_covered",
                ),
            ),
            "by_category": categories,
            "by_month": [
                {
                    **select(
                        row, ("month", "family_expense", "family_income", "family_net_cashflow")
                    ),
                    "currency": currency,
                }
                for row in raw["by_month"]
            ],
            "by_profile": [attribution(row) for row in raw["by_profile"]],
            "joint": attribution(raw["joint"]) if raw.get("joint") is not None else None,
            "comparison": {
                **view({**comparison, "currency": currency}),
                **select(
                    comparison,
                    (
                        "family_expense_total",
                        "family_income_total",
                        "family_net_cashflow",
                        "expenses_change_percent",
                    ),
                ),
            }
            if comparison is not None
            else None,
            "expense_split": {
                **select(
                    raw["expense_split"],
                    (
                        "family_recurring_expense",
                        "family_variable_expense",
                        "recurring_share_percent",
                    ),
                ),
                "currency": currency,
            },
            "recurring_charges": select(recurring, ("detected_count", "unpriced_count"))
            if recurring is not None
            else None,
            "targets_status": "UNAVAILABLE"
            if raw.get("targets_unavailable_reason")
            else "RETURNED"
            if any(c["target"] is not None for c in categories)
            else "UNVERIFIED",
            "history_quality": quality,
            "limitations": limits,
        }
    )


class OptionalMcpService:
    def __init__(self, client: NativeMcpClient) -> None:
        self.client = client

    async def budget(self, request: PeriodRequest, now: datetime) -> BudgetResponse:
        arguments = request.arguments(now.astimezone(ZoneInfo("Europe/Paris")).date())
        async with self.client.session(("get_budget_overview",)) as session:
            raw = await session.call("get_budget_overview", arguments)
            try:
                return normalize_budget(raw, now)
            except (ValueError, TypeError, KeyError):
                raise McpFailure() from None

    async def search(self, request: SearchRequest, now: datetime) -> SearchResponse:
        arguments = request.arguments(now.astimezone(ZoneInfo("Europe/Paris")).date())
        async with self.client.session(("search_spending",)) as session:
            raw = await session.call("search_spending", arguments)
            try:
                return SearchResponse.model_validate(
                    {
                        **context(now),
                        "view": view(raw["view"]),
                        "matched_query": raw["matched_filter"]["query"],
                        "matched_direction": raw["matched_filter"].get("direction"),
                        **select(
                            raw,
                            (
                                "matched_expense_total",
                                "matched_income_total",
                                "matched_transactions_count",
                                "unpriced_transactions_count",
                            ),
                        ),
                    }
                )
            except (ValueError, TypeError, KeyError):
                raise McpFailure() from None

    async def goals(self, now: datetime) -> GoalsResponse:
        async with self.client.session(("goals",)) as session:
            raw = await session.call("goals", {})
            ids = set()
            available = "accounts" in session.catalog
            if available:
                accounts = await session.call("accounts", {})
                for account in accounts["data"]:
                    checked("account_observed", account)
                    if account["id"] in ids:
                        raise McpFailure()
                    ids.add(account["id"])
            try:
                goals = []
                for row in raw["goals"]:
                    target = row.get("target_date")
                    if target is not None:
                        checked("date", target)
                    checked("timestamp", row["created_at"])
                    for identifier in row["funding_account_ids"]:
                        checked("id", identifier)
                    plan = row["plan"]
                    fields = {
                        "safety_net": ("monthly_expenses_amount", "target_coverage_months"),
                        "life_project": (
                            "target_amount",
                            "contribution_amount",
                            "contribution_frequency",
                        ),
                        "unavailable": (),
                    }[plan["kind"]]
                    goals.append(
                        {
                            **select(row, ("name", "goal_type", "currency", "created_at")),
                            "target_month": target[:7] if target else None,
                            "contributor_labels": [c.get("name") for c in row["contributors"]],
                            "funding_account_keys": [
                                key("account_key", account_id=i)
                                for i in row["funding_account_ids"]
                                if i in ids
                            ],
                            "unresolved_funding_count": sum(
                                i not in ids for i in row["funding_account_ids"]
                            ),
                            "plan": {"kind": plan["kind"], **select(plan, fields)},
                        }
                    )
                coverage = (
                    "UNAVAILABLE"
                    if not available
                    else "PARTIAL"
                    if any(g["unresolved_funding_count"] for g in goals)
                    else "COMPLETE"
                )
                return GoalsResponse.model_validate(
                    {**context(now), "goals": goals, "funding_reference_coverage": coverage}
                )
            except (ValueError, TypeError, KeyError):
                raise McpFailure() from None
