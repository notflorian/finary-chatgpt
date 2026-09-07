"""Execute both exported contract boundaries with synthetic data.

Pydantic is the API field oracle. Output mutations run after valid preparation,
before its real all-batch gate; they cannot be caught by the input validator.
"""

import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_n8n_workflow import _headers, _prepare_named_rows, _run_code_node, _run_context, _snapshot
from test_n8n_workflow_v2 import _node, _run_validation
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from test_sync_completion import _finalize, _prepare

from app.models import Account, Liability, PortfolioSnapshotV2, Position, SnapshotCoverage

ROOT = Path(__file__).parents[2]
MISSING = object()
BATCHES = {
    "accounts_current": "account_rows",
    "positions_current": "position_rows",
    "liabilities_current": "liability_rows",
    "positions_history": "history_rows",
    "portfolio_daily": "daily_rows",
    "sync_runs": "sync_run_rows",
}
MODELS = [
    ((), PortfolioSnapshotV2),
    (("coverage",), SnapshotCoverage),
    (("accounts", 0), Account),
    (("positions", 0), Position),
    (("liabilities", 0), Liability),
]


def _mutate(snapshot, path, field, value):
    parent = snapshot
    for part in path:
        parent = parent[part]
    if value is MISSING:
        parent.pop(field, None)
    else:
        parent[field] = value


def _api_field_cases(rejected):
    """Select cases with the real model, not a parallel validator implementation."""
    values = [
        MISSING,
        None,
        "",
        True,
        False,
        123,
        -1,
        [],
        {},
        "invalid",
        float("nan"),
        float("inf"),
    ]
    for path, model in MODELS:
        for field in model.model_fields:
            for index, value in enumerate(values):
                snapshot = _snapshot()
                # Preserve the independent known-account-total safety gate when
                # testing omission of a nullable account valuation.
                snapshot["gross_assets_eur"] = 0
                snapshot["net_worth_eur"] = -10
                _mutate(snapshot, path, field, value)
                try:
                    PortfolioSnapshotV2.model_validate_json(json.dumps(snapshot))
                    invalid = False
                except ValidationError:
                    invalid = True
                # Positive default/null boundaries only; arbitrary valid key
                # strings still have the workflow's canonical-key safety rules.
                if invalid == rejected and (rejected or value is MISSING or value is None):
                    yield pytest.param(snapshot, id=f"{'.'.join(map(str, path))}.{field}-{index}")


@pytest.mark.parametrize("snapshot", list(_api_field_cases(True)))
def test_api_field_matrix_rejects_model_invalid_values(workflow, schema, snapshot):
    with pytest.raises(ValidationError):
        PortfolioSnapshotV2.model_validate_json(json.dumps(snapshot))
    result = _run_validation(workflow, schema, snapshot)
    assert result["can_write"] is False
    assert "snapshot" not in result
    assert result["failure"]["code"] == "SNAPSHOT_VALIDATION_FAILED"
    assert len(result["failure"]["message"]) < 180


@pytest.mark.parametrize("snapshot", list(_api_field_cases(False)))
def test_api_defaults_and_nullable_fields_match_model(workflow, schema, snapshot):
    expected = PortfolioSnapshotV2.model_validate_json(json.dumps(snapshot)).model_dump(mode="json")
    result = _run_validation(workflow, schema, snapshot)
    assert result["can_write"] is True
    assert result["snapshot"] == expected
    named = _prepare_named_rows(schema, result["snapshot"])
    prepared = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])
    assert prepared[0]["json"]["sync_run_rows"][0]["status"].startswith("SUCCESS")


ISSUE_CASES = [
    ("accounts", "name", MISSING),
    ("accounts", "currency", "EURO"),
    ("positions", "asset_class", MISSING),
    ("liabilities", "name", None),
]


@pytest.mark.parametrize("group,field,value", ISSUE_CASES)
def test_four_issue_reproductions_fail_before_overrides(workflow, schema, group, field, value):
    snapshot = _snapshot()
    _mutate(snapshot, (group, 0), field, value)
    with pytest.raises(ValidationError):
        PortfolioSnapshotV2.model_validate_json(json.dumps(snapshot))
    assert _run_validation(workflow, schema, snapshot)["can_write"] is False
    # Also guard preparation against a malformed saved input. The default
    # matching override would otherwise hide the absent position asset_class.
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            workflow,
            "Prepare Validated Rows",
            named_rows=_prepare_named_rows(schema, snapshot),
            input_rows=[{}],
        )
    assert "CONTRACT_VALIDATION_FAILED:snapshot." in error.value.stderr
    assert error.value.stdout == ""


@pytest.mark.parametrize("collection", ["accounts", "positions", "liabilities"])
@pytest.mark.parametrize("value", [None, [], "private-value", 4, True])
def test_malformed_collection_members_are_sanitized(workflow, schema, collection, value):
    snapshot = _snapshot()
    snapshot[collection][0] = value
    result = _run_validation(workflow, schema, snapshot)
    assert result["can_write"] is False
    assert result["failure"]["message"] == f"CONTRACT_VALIDATION_FAILED:snapshot.{collection}[]"


@pytest.mark.parametrize("snapshot", [None, [], True, 1, "not JSON"])
def test_snapshot_root_must_be_an_object(workflow, schema, snapshot):
    result = _run_validation(workflow, schema, snapshot)
    assert result["can_write"] is False
    assert result["failure"]["code"] == "SNAPSHOT_VALIDATION_FAILED"


@pytest.mark.parametrize("collection", ["accounts", "positions", "liabilities"])
def test_sparse_api_arrays_fail_before_property_access(workflow, schema, collection):
    result = _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [_run_context()], "Fetch Canonical Schema": [{"body": schema}],
        },
        input_rows=[{"body": _snapshot()}],
        setup_js=f"delete inputRows[0].body.{collection}[0];",
    )[0]["json"]
    assert result["can_write"] is False
    assert result["failure"]["message"] == f"CONTRACT_VALIDATION_FAILED:snapshot.{collection}[]"


@pytest.mark.parametrize("path,model", MODELS)
def test_extra_fields_and_explicit_undefined_never_disappear(workflow, schema, path, model):
    access = "inputRows[0].body" + "".join(f"[{json.dumps(part)}]" for part in path)
    for field in [*model.model_fields, "private-extra-field"]:
        setup = f"{access}[{json.dumps(field)}] = undefined;"
        result = _run_code_node(
            workflow,
            "Validate Snapshot",
            named_rows={
                "Initialize Run": [_run_context()],
                "Fetch Canonical Schema": [{"body": schema}],
            },
            input_rows=[{"body": _snapshot()}],
            setup_js=setup,
        )[0]["json"]
        assert result["can_write"] is False
        assert "private-extra-field" not in result["failure"]["message"]


@pytest.mark.parametrize("currency", ["EU", "EURO", "eur", "E1R", "EUR\n", " EUR", "€€€"])
def test_actual_currency_format(workflow, schema, currency):
    snapshot = _snapshot()
    snapshot["accounts"][0]["currency"] = currency
    assert _run_validation(workflow, schema, snapshot)["can_write"] is False


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-02-29T01:02:03Z",
        "2026-04-31T01:02:03Z",
        "2026-08-20T24:00:00Z",
        "2026-08-20",
        "2026-08-20T01:02:03",
        "2026-08-20T01:02:03+24:00",
        "2026-08-20T01:02:03+01:60",
        "0000-01-01T00:00:00Z",
    ],
)
def test_invalid_snapshot_calendar_and_offset(workflow, schema, timestamp):
    snapshot = _snapshot()
    snapshot["generated_at"] = timestamp
    assert _run_validation(workflow, schema, snapshot)["can_write"] is False


@pytest.mark.parametrize(
    "timestamp",
    [
        "2024-02-29T01:02:03.123456+05:45",
        "2026-08-20T01:02:03-03:30",
        "2026-08-20t01:02:03z",
        "2026-08-20 01:02:03+0200",
        "2026-08-20T01:02:03,123Z",
    ],
)
def test_valid_offsets_signed_values_unrestricted_strings_and_metadata(workflow, schema, timestamp):
    snapshot = _snapshot()
    snapshot["generated_at"] = timestamp
    snapshot["accounts"][0].update(name=" ", account_type="any type", currency="ZZZ")
    snapshot["positions"][0].update(
        quantity=-2,
        unit_price=-10,
        fx_to_eur=-1,
        market_value_native=-20,
        market_value_eur=-20,
        cost_basis_eur=-30,
        unrealized_pnl_eur=-10,
        unrealized_pnl_pct=-2,
        isin="any string",
        ticker="",
        region="arbitrary",
        metadata={"synthetic-private-key": "synthetic-private-value", "number": 0, "flag": True},
    )
    snapshot["liabilities"][0].update(
        interest_rate=-2, monthly_payment_eur=0, end_date="2028-02-29"
    )
    PortfolioSnapshotV2.model_validate_json(json.dumps(snapshot))
    result = _run_validation(workflow, schema, snapshot)
    assert result["can_write"] is True
    assert result["snapshot"]["positions"][0]["metadata"] == {}
    assert "synthetic-private" not in json.dumps(result)
    prepared = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, result["snapshot"]),
        input_rows=[{}],
    )[0]["json"]
    assert prepared["position_rows"][0]["asset_class"] == "EQUITY"  # Valid override.
    assert prepared["position_rows"][0]["quantity"] == -2
    assert prepared["liability_rows"][0]["monthly_payment_eur"] == 0


def test_identifiers_have_no_speculative_character_allowlist(workflow, schema):
    snapshot = _snapshot()
    account = snapshot["accounts"][0]
    account["source_account_id"] = " arbitrary:identifier: "
    account["account_key"] = f"finary:account:{account['source_account_id']}"
    for index, position in enumerate(snapshot["positions"]):
        position["account_key"] = account["account_key"]
        position["source_asset_id"] = f"any-kind: arbitrary:{index}:"
        position["position_key"] = (
            f"finary:{account['source_account_id']}:asset:{position['source_asset_id']}"
        )
    PortfolioSnapshotV2.model_validate_json(json.dumps(snapshot))
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True
    _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, snapshot),
        input_rows=[{}],
    )


@pytest.mark.parametrize("year", ["0001", "0099", "2000"])
def test_valid_calendar_years_keep_iso_business_dates(workflow, schema, year):
    snapshot = _snapshot()
    snapshot["generated_at"] = f"{year}-01-01T12:00:00Z"
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True
    result = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, snapshot),
        input_rows=[{}],
    )[0]["json"]
    assert result["daily_rows"][0]["snapshot_date"] == f"{year}-01-01"


def mutated_preparation(workflow, mutation):
    exported = deepcopy(workflow)
    node = _node(exported, "Prepare Validated Rows")
    marker = "validatePrepared(schema, prepared, snapshot, run);"
    assert node["parameters"]["jsCode"].count(marker) == 1
    node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace(
        marker, mutation + "\n" + marker
    )
    return exported


def _row_cases():
    schema = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
    for sheet, batch in BATCHES.items():
        for column in schema["sheets"][sheet]["columns"]:
            field = column["name"]
            target = f"prepared.{batch}[0].{field}"
            mutations = [
                f"delete {target};",
                f"{target} = undefined;",
                f"{target} = {{}};",
                f"{target} = [];",
            ]
            if not column["nullable"]:
                mutations.extend([f"{target} = null;", f"{target} = '';"])
            if column["type"] == "NUMBER":
                mutations.extend(
                    f"{target} = {value};"
                    for value in ["'1'", "true", "NaN", "Infinity", "-Infinity"]
                )
            elif column["type"] == "BOOLEAN":
                mutations.extend(f"{target} = {value};" for value in ["'TRUE'", "1", "'yes'"])
            else:
                mutations.extend(f"{target} = {value};" for value in ["1", "false"])
            if column["type"] in {"ENUM", "DATE", "DATETIME"}:
                mutations.append(f"{target} = 'invalid';")
            for index, mutation in enumerate(mutations):
                yield pytest.param(mutation, id=f"{sheet}.{field}-{index}")


@pytest.mark.parametrize("mutation", list(_row_cases()))
def test_output_field_matrix_independent_of_input_gate(workflow, schema, mutation):
    snapshot = _snapshot()
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            mutated_preparation(workflow, mutation),
            "Prepare Validated Rows",
            named_rows=_prepare_named_rows(schema, snapshot),
            input_rows=[{}],
        )
    assert error.value.stdout == ""
    assert error.value.stderr.startswith(("CONTRACT_VALIDATION_FAILED:", "TARGET_SCHEMA_MISMATCH:"))
    assert len(error.value.stderr) < 180


@pytest.mark.parametrize("batch", BATCHES.values())
@pytest.mark.parametrize(
    "mutation",
    [
        "prepared.BATCH = null;",
        "prepared.BATCH = {};",
        "prepared.BATCH[0] = null;",
        "prepared.BATCH[0] = [];",
        "prepared.BATCH[0].extra = 1;",
        "prepared.BATCH[0] = Object.fromEntries(Object.entries(prepared.BATCH[0]).reverse());",
        "prepared.BATCH.push({...prepared.BATCH[0]});",
    ],
)
def test_output_batch_shape_order_and_duplicates(workflow, schema, batch, mutation):
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            mutated_preparation(workflow, mutation.replace("BATCH", batch)),
            "Prepare Validated Rows",
            named_rows=_prepare_named_rows(schema, _snapshot()),
            input_rows=[{}],
        )
    assert error.value.stdout == ""
    assert error.value.stderr.startswith(
        (
            "CONTRACT_VALIDATION_FAILED:",
            "TARGET_SCHEMA_MISMATCH:",
            "DUPLICATE_OR_MISSING_TARGET_KEY:",
        )
    )


@pytest.mark.parametrize("value", ["2026-02-29", "2026-04-31", "2026-01-01T00:00:00Z", "arbitrary"])
def test_api_string_end_date_fails_only_at_sheet_date_boundary(workflow, schema, value):
    snapshot = _snapshot()
    snapshot["liabilities"][0]["end_date"] = value
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            workflow,
            "Prepare Validated Rows",
            named_rows=_prepare_named_rows(schema, snapshot),
            input_rows=[{}],
        )
    assert error.value.stderr == "CONTRACT_VALIDATION_FAILED:liabilities_current.end_date"


def test_generated_contract_and_all_embedded_copies_are_current(workflow, schema):
    spec = importlib.util.spec_from_file_location(
        "build_validation", ROOT / "scripts/build-workflow-validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for node in workflow["nodes"]:
        if node["type"] != "n8n-nodes-base.code":
            continue
        path = module.code_node_source_path("finary-daily-sync.json", node["name"])
        assert path.is_file()
        assert node["parameters"]["jsCode"] == module.expected_code(
            "finary-daily-sync.json", node["name"]
        )
    assert module.api_contract()["$defs"]["AssetClass"]["enum"] == schema["enums"]["asset_class"]
    assert (
        module.api_contract()["$defs"]["LiabilityCoverage"]["enum"]
        == schema["enums"]["liability_coverage"]
    )
    # Every emitted enum resolves explicitly; no duplicated enum value lists.
    bindings = {
        "asset_class": "asset_class",
        "status": "sync_status",
        "liability_coverage": "liability_coverage",
    }
    for sheet in BATCHES:
        for column in schema["sheets"][sheet]["columns"]:
            if column["type"] == "ENUM":
                assert bindings[column["name"]] in schema["enums"]


def test_valid_failed_telemetry_preserves_nullable_unavailable_values(workflow, schema):
    named = _prepare_named_rows(schema, _snapshot())
    named["Validate Snapshot"][0]["failure"] = {
        "code": "SNAPSHOT_VALIDATION_FAILED",
        "message": "Snapshot validation failed",
    }
    result = _run_code_node(
        workflow, "Prepare Failed Run", named_rows=named, input_rows=[_headers(schema, "sync_runs")]
    )[0]["json"]
    assert result["status"] == "FAILED"
    for key in [
        "accounts_count",
        "positions_count",
        "liabilities_count",
        "gross_assets_eur",
        "liabilities_eur",
        "net_worth_eur",
    ]:
        assert result[key] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "FAILED"),
        ("warning_count", -1),
        ("accounts_count", None),
        ("liability_coverage", "invalid"),
        ("started_at", "invalid"),
    ],
)
def test_terminal_rechecks_saved_success_fields(workflow, schema, field, value):
    named = _prepare(workflow, schema)
    named["Prepare Validated Rows"][0]["sync_run_rows"][0][field] = value
    with pytest.raises(subprocess.CalledProcessError) as error:
        _finalize(workflow, named)
    assert error.value.stdout == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "foreign"),
        ("started_at", None),
        ("started_epoch_ms", "0"),
        ("started_epoch_ms", float("inf")),
        ("started_epoch_ms", 0),
    ],
)
def test_run_context_fails_before_preparing_any_write(workflow, schema, field, value):
    named = _prepare_named_rows(schema, _snapshot())
    named["Validate Snapshot"][0]["run"][field] = value
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])
    assert error.value.stderr in {"STALE_EXECUTION_IDENTITY", "INVALID_RUN_TIMING"}
    assert error.value.stdout == ""


RETAINED = [
    (
        "accounts_current",
        "Read Current Accounts",
        "account_rows",
        "source_account_id",
        "account_key",
    ),
    (
        "positions_current",
        "Read Current Positions",
        "position_rows",
        "source_asset_id",
        "position_key",
    ),
    (
        "liabilities_current",
        "Read Current Liabilities",
        "liability_rows",
        "source_liability_id",
        "liability_key",
    ),
]


def retained_context(workflow, schema, binding):
    sheet, node, batch, source, key = binding
    named = _prepare_named_rows(schema, _snapshot())
    old = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[0][
        "json"
    ][batch][0]
    old[source] += "-retained"
    old[key] += "-retained"
    old["last_seen_at"] = "2024-02-29T23:30:00-03:30"
    old["last_seen_run_id"] = "legacy-observation-id"
    named[node] = [old]
    return named, old


@pytest.mark.parametrize("binding", RETAINED)
def test_supported_retained_encodings_preserve_observation(workflow, schema, binding):
    named, old = retained_context(workflow, schema, binding)
    sheet, node, batch, _, key = binding
    expected = deepcopy(old)
    expected["is_active"] = False
    for column in schema["sheets"][sheet]["columns"]:
        field = column["name"]
        value = old[field]
        if value is None:
            old[field] = ""
        elif column["type"] == "BOOLEAN":
            old[field] = "TRUE" if value else "FALSE"
        elif column["type"] == "NUMBER":
            old[field] = f" {value}e0 "
    # Google can omit empty nullable cells. Required cells must remain present.
    nullable = next(
        c["name"]
        for c in schema["sheets"][sheet]["columns"]
        if c["nullable"] and old[c["name"]] == ""
    )
    del old[nullable]
    old["row_number"] = 3
    result = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]
    assert next(row for row in result[batch] if row[key] == old[key]) == expected
    assert all(row["run_id"] != "legacy-observation-id" for row in result["history_rows"])


@pytest.mark.parametrize("binding", RETAINED)
@pytest.mark.parametrize(
    "field,value",
    [
        ("name", {}),
        ("source", None),
        ("source", MISSING),
        ("source", ""),
        ("last_seen_at", "2026-02-29T00:00:00Z"),
        ("last_seen_at", "2026-01-01"),
        ("last_seen_run_id", None),
        ("last_seen_run_id", MISSING),
        ("is_active", "yes"),
        ("is_active", 1),
        ("is_active", "true"),
    ],
)
def test_corrupt_required_retained_cells_fail_before_writes(
    workflow, schema, binding, field, value
):
    named, old = retained_context(workflow, schema, binding)
    if value is MISSING:
        del old[field]
    else:
        old[field] = value
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])
    assert error.value.stdout == ""
    assert error.value.stderr == f"CONTRACT_VALIDATION_FAILED:{binding[0]}.{field}"


@pytest.mark.parametrize("binding", RETAINED)
def test_explicit_undefined_retained_cell_is_not_a_blank(workflow, schema, binding):
    named, old = retained_context(workflow, schema, binding)
    sheet, node, _, _, _ = binding
    field = next(c["name"] for c in schema["sheets"][sheet]["columns"] if c["nullable"])
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            workflow,
            "Prepare Validated Rows",
            named_rows=named,
            input_rows=[{}],
            setup_js=f"namedRows[{json.dumps(node)}][0][{json.dumps(field)}] = undefined;",
        )
    assert error.value.stderr == f"CONTRACT_VALIDATION_FAILED:{sheet}.{field}"


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_untouched_liabilities_and_history_do_not_require_repair(workflow, schema, coverage):
    snapshot = _snapshot()
    snapshot.update(liabilities_eur=None, net_worth_eur=None)
    snapshot["coverage"]["liabilities"] = coverage
    if coverage == "UNAVAILABLE":
        snapshot["liabilities"] = []
    else:
        snapshot["liabilities"][0]["end_date"] = "API string, not a Sheets date"
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True
    named = _prepare_named_rows(schema, snapshot)
    named["Read Current Liabilities"] = [{"name": None}]
    named["Read Portfolio Daily"] = [{"snapshot_date": "invalid historical row"}]
    named["Read Sync Runs"] = [{"run_id": None}]
    result = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]
    assert result["liability_rows"] == []
    assert result["daily_rows"][0]["liabilities_eur"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "prepared.account_rows[0].account_key += 'bad';",
        "prepared.position_rows[0].source_asset_id = ':missing-kind';",
        "prepared.history_rows[0].history_key += 'bad';",
        "prepared.history_rows[0].run_id = null;",
        "prepared.daily_rows[0].snapshot_date = '2026-02-29';",
        "prepared.daily_rows[0].snapshot_date = '2026-08-21';",
        "prepared.sync_run_rows[0].positions_count = 9;",
        "prepared.sync_run_rows[0].positions_count = 1.5;",
        "prepared.sync_run_rows[0].status = 'FAILED';",
        "prepared.sync_run_rows[0].run_id = 'foreign';",
        "prepared.liability_rows[0].monthly_payment_eur = -1;",
        "prepared.liability_rows[0].outstanding_eur = 11;",
    ],
)
def test_prepared_semantic_constraints(workflow, schema, mutation):
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            mutated_preparation(workflow, mutation),
            "Prepare Validated Rows",
            named_rows=_prepare_named_rows(schema, _snapshot()),
            input_rows=[{}],
        )
    assert error.value.stdout == ""
    assert error.value.stderr.startswith("CONTRACT_VALIDATION_FAILED:")
