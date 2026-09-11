"""Build the portable, inactive MCP workflow from readable sources and canonical contracts."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "n8n/code-nodes/finary-mcp-sync"


def prelude(name):
    workbook = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
    digest = hashlib.sha256(
        json.dumps(workbook, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if name == "Initialize MCP Run":
        binding = (
            "const mcpWorkbook={}; const mcpContract="
            + json.dumps({"contract_version": workbook["source_contract_version"]})
            + ";\n"
        )
    else:
        value = (
            json.dumps(workbook, separators=(",", ":"))
            if name in {"Validate MCP Snapshot", "Finalize MCP Failure"}
            else "$('Validate MCP Snapshot').first().json.schema"
        )
        binding = (
            "const mcpWorkbook="
            + value
            + ";\nconst mcpContract={contract_version:mcpWorkbook.source_contract_version,numeric_policy:mcpWorkbook.mcp_numeric_policy,$defs:mcpWorkbook.mcp_definitions,identity:mcpWorkbook.mcp_identity,valuation_contracts:mcpWorkbook.mcp_valuation_contracts};\n"
        )
    library = (
        (ROOT / "n8n/mcp-validation.js").read_text()
        + "\n"
        + (ROOT / "n8n/mcp-workbook.js").read_text()
        + "\n"
    )
    check = (
        ""
        if name == "Initialize MCP Run"
        else "mcpAssert(require('crypto').createHash('sha256').update(mcpStable(mcpWorkbook)).digest('hex')==='"
        + digest
        + "');\n"
    )
    return "// Generated contract and shared validation.\n" + binding + library + check


def generate(check=False):
    schema = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
    nodes = []
    connections = {}

    def node(name, kind, parameters, **options):
        value = {
            "id": str(uuid5(NAMESPACE_URL, "finary-mcp:" + name)),
            "name": name,
            "type": "n8n-nodes-base." + kind,
            "typeVersion": {
                "code": 2,
                "googleSheets": 4.7,
                "httpRequest": 4.5,
                "manualTrigger": 1,
                "scheduleTrigger": 1.3,
                "if": 2.3,
            }[kind],
            "position": [len(nodes) * 160, 0],
            "parameters": parameters,
            **options,
        }
        nodes.append(value)
        return name

    def link(origin, target, branch=0):
        outputs = connections.setdefault(origin, {"main": []})["main"]
        while len(outputs) <= branch:
            outputs.append([])
        outputs[branch].append({"node": target, "type": "main", "index": 0})

    def code(name, source=None):
        filename = "-".join(name.lower().split()) + ".js"
        path = DIRECTORY / filename
        if source is not None:
            if check:
                if not path.exists() or path.read_text() != source:
                    raise SystemExit(f"Stale generated selector: {filename}")
            else:
                path.write_text(source)
        return node(name, "code", {"jsCode": prelude(name) + path.read_text()})

    def sheet(name, table, write=False, header=False):
        p = {
            "documentId": {
                "__rl": True,
                "value": "={{ $('Initialize MCP Run').first().json.workbook_id }}",
                "mode": "id",
            },
            "sheetName": {"__rl": True, "value": table, "mode": "name"},
            "options": {},
        }
        options = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000}
        if write:
            p.update(
                operation="appendOrUpdate",
                columns={
                    "mappingMode": "autoMapInputData",
                    "value": {},
                    "matchingColumns": [schema["sheets"][table]["unique_key"]],
                    "schema": "={{ $('Validate MCP Snapshot').first().json.schema.sheets."
                    + table
                    + ".columns.map(c => ({id:c.name,displayName:c.name,required:!c.nullable,defaultMatch:false,display:true,type:c.type==='NUMBER'?'number':c.type==='BOOLEAN'?'boolean':'string',canBeUsedToMatch:c.name==='"
                    + schema["sheets"][table]["unique_key"]
                    + "',removed:false})) }}",
                },
            )
            p["options"] = {
                "cellFormat": "RAW",
                "handlingExtraData": "error",
                "allowEmptyValues": True,
            }
        else:
            options.update(executeOnce=True, alwaysOutputData=True)
            if header:
                p["options"] = {
                    "dataLocationOnSheet": {
                        "values": {
                            "rangeDefinition": "specifyRange",
                            "headerRow": 1,
                            "firstDataRow": 1,
                        }
                    }
                }
        return node(name, "googleSheets", p, **options)

    manual = node("Manual Trigger", "manualTrigger", {})
    schedule = node(
        "Daily 07:30 Europe Paris",
        "scheduleTrigger",
        {"rule": {"interval": [{"field": "cronExpression", "expression": "30 7 * * *"}]}},
    )
    init = code("Initialize MCP Run")
    link(manual, init)
    link(schedule, init)
    fetch_schema = node(
        "Fetch MCP Schema",
        "httpRequest",
        {
            "url": "={{ $env.FINARY_MCP_SCHEMA_URL || 'http://schema-server/google-sheets-schema.json' }}",
            "options": {
                "timeout": 20000,
                "response": {
                    "response": {"fullResponse": True, "neverError": True, "responseFormat": "text"}
                },
            },
        },
        executeOnce=True,
    )
    fetch_snapshot = node(
        "Fetch MCP Snapshot",
        "httpRequest",
        {
            "url": "={{ ($env.FINARY_BRIDGE_URL || 'http://finary-bridge:8000') + '/v3/snapshot' }}",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "X-API-Key", "value": "={{ $env.FINARY_BRIDGE_API_KEY || '' }}"}
                ]
            },
            "options": {
                "timeout": 185000,
                "response": {
                    "response": {"fullResponse": True, "neverError": True, "responseFormat": "text"}
                },
            },
        },
        executeOnce=True,
    )
    link(init, fetch_schema)
    link(fetch_schema, fetch_snapshot)
    previous = code("Validate MCP Snapshot")
    link(fetch_snapshot, previous)
    for table in schema["sheets"]:
        header = sheet("Preflight " + table, table, header=True)
        link(previous, header)
        read = sheet("Read " + table, table)
        link(header, read)
        previous = read
    prepare = code("Prepare MCP Rows")
    link(previous, prepare)
    previous = prepare
    for table in schema["mcp_tables"]["sync_runs"]["count_columns"]:
        if table == "liabilities_current":
            continue
        check_name = code(
            "Check " + table,
            "const p=$('Prepare MCP Rows').first().json;\nmcpRun(p.run,String($execution.id));\nreturn [{json:{has_rows:p.batches['"
            + table
            + "'].length>0}}];\n",
        )
        link(previous, check_name)
        condition = node(
            "Has " + table,
            "if",
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "has-rows",
                            "leftValue": "={{ $json.has_rows }}",
                            "rightValue": True,
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        )
        link(check_name, condition)
        select = code(
            "Select " + table,
            "const p=$('Prepare MCP Rows').first().json;\nmcpRun(p.run,String($execution.id));\nreturn mcpItems('"
            + table
            + "',p.batches['"
            + table
            + "']);\n",
        )
        link(condition, select)
        write = sheet("Write " + table, table, write=True)
        link(select, write)
        continuation = code(
            "Continue " + table, "return [{json:{completed_table:'" + table + "'}}];\n"
        )
        link(write, continuation)
        link(condition, continuation, 1)
        previous = continuation
    control = sheet("Recheck Writer Control", "writer_control")
    link(previous, control)
    terminal = sheet("Read MCP Terminal Before Success", "sync_runs")
    link(control, terminal)
    finalize = code("Finalize MCP Success")
    link(terminal, finalize)
    success = sheet("Record MCP Success", "sync_runs", write=True)
    link(finalize, success)
    fallible = [
        n
        for n in nodes
        if n["name"] != "Initialize MCP Run"
        and n["type"]
        in {"n8n-nodes-base.code", "n8n-nodes-base.googleSheets", "n8n-nodes-base.httpRequest"}
    ]
    failure_control = sheet("Failure Writer Control", "writer_control")
    failure_header = sheet("Failure Terminal Header", "sync_runs", header=True)
    link(failure_control, failure_header)
    failure_read = sheet("Failure Terminal Read", "sync_runs")
    link(failure_header, failure_read)
    failure = code("Finalize MCP Failure")
    link(failure_read, failure)
    record_failure = sheet("Record MCP Failure", "sync_runs", write=True)
    link(failure, record_failure)
    nodes[-1]["parameters"]["columns"]["schema"] = [
        {
            "id": c["name"],
            "displayName": c["name"],
            "required": not c["nullable"],
            "defaultMatch": False,
            "display": True,
            "type": "number"
            if c["type"] == "NUMBER"
            else "boolean"
            if c["type"] == "BOOLEAN"
            else "string",
            "canBeUsedToMatch": c["name"] == "run_id",
            "removed": False,
        }
        for c in schema["sheets"]["sync_runs"]["columns"]
    ]
    for item in fallible:
        item["onError"] = "continueErrorOutput"
        link(item["name"], failure_control, 1)
    return {
        "id": "finary-mcp-sync",
        "name": "Finary MCP Portfolio Sync",
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "executionOrder": "v1",
            "executionTimeout": 300,
            "timezone": "Europe/Paris",
            "saveDataErrorExecution": "all",
            "saveDataSuccessExecution": "all",
        },
        "pinData": {},
        "tags": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "n8n/workflows/finary-mcp-sync.json"
    content = json.dumps(generate(args.check), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not path.exists() or path.read_text() != content:
            raise SystemExit("MCP workflow is stale")
    else:
        path.write_text(content)


if __name__ == "__main__":
    main()
