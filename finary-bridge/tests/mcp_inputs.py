"""Fresh typed manual inputs; formulas are intentional only in notes."""

def manual_rows():
    return {
        "allocation_targets": {
            "target_key": "target",
            "asset_class": "OTHER",
            "target_pct": 0.75,
            "min_pct": 0.5,
            "max_pct": 1,
            "notes": "=1+2",
            "enabled": False,
        },
        "asset_overrides": {
            "override_key": "override",
            "source_asset_id": "mcp:holding:securities:synthetic",
            "custom_asset_class": "OTHER",
            "notes": "=1+2",
            "enabled": False,
        },
        "cashflows": {
            "cashflow_key": "flow",
            "date": "2026-09-11",
            "account_key": "mcp:account:assets:synthetic",
            "amount_eur": -12.5,
            "type": "FEE",
            "notes": "=1+2",
            "source": "manual",
        },
    }
