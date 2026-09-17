"""Build the portable, inactive MCP workflow from readable sources and canonical contracts."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "n8n/code-nodes/finary-mcp-sync"

# Dependencies include declaration-time initializers, not just function calls.
# Contract bindings are emitted before all groups (notably timestamps).
GROUP_DEPENDENCIES = {
    "core": (),
    "timestamps": ("core",),
    "schema": ("timestamps",),
    "snapshot": ("schema",),
    "run": ("timestamps",),
    "rows": ("schema",),
    "observations": ("rows",),
    "build": ("snapshot", "observations"),
    "retained": ("observations",),
}
PROFILES = {
    "Initialize MCP Run": ("run",),
    "Validate MCP Snapshot": ("run", "snapshot"),
    "Prepare MCP Rows": ("run", "build", "retained"),
    "Check": ("run",),
    "Select": ("run", "rows"),
    "Continue": ("core",),
    "Finalize MCP Success": ("run", "build"),
    "Finalize MCP Failure": ("run", "rows"),
}


def read_groups():
    """Read explicitly delimited source blocks without parsing JavaScript syntax."""
    groups = {}
    for filename in ("mcp-validation.js", "mcp-workbook.js"):
        name = None
        lines = []
        for line in (ROOT / "n8n" / filename).read_text().splitlines(keepends=True):
            marker = line.rstrip("\r\n")
            if marker.startswith("// @mcp-group "):
                candidate = marker.removeprefix("// @mcp-group ")
                if name is not None or candidate in groups or candidate not in GROUP_DEPENDENCIES:
                    raise ValueError(f"Invalid helper group: {candidate}")
                name, lines = candidate, []
            elif marker == "// @mcp-end":
                if name is None or not lines:
                    raise ValueError(f"Invalid helper group ending in {filename}")
                groups[name] = "".join(lines)
                name = None
            elif name is not None:
                lines.append(line)
            elif line.strip():
                raise ValueError(f"Source outside a helper group in {filename}")
        if name is not None:
            raise ValueError(f"Unclosed helper group: {name}")
    if groups.keys() != GROUP_DEPENDENCIES.keys():
        raise ValueError("Missing shared helper groups")
    return groups


def shared_helpers(name, groups):
    role = name.split()[0] if name.startswith(("Check ", "Select ", "Continue ")) else name
    emitted = set()
    visiting = set()
    blocks = []

    def include(group):
        if group in visiting:
            raise ValueError(f"Cyclic helper dependency: {group}")
        if group in emitted:
            return
        visiting.add(group)
        for dependency in GROUP_DEPENDENCIES[group]:
            include(dependency)
        visiting.remove(group)
        emitted.add(group)
        blocks.append(f"// Shared helpers: {group}\n" + groups[group])

    for group in PROFILES[role]:
        include(group)
    return "\n".join(blocks) + "\n"


def prelude(name, groups):
    workbook = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
    digest = hashlib.sha256(
        json.dumps(workbook, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if name == "Initialize MCP Run":
        binding = (
            "const mcpWorkbook={}; const mcpContract="
            + json.dumps(
                {
                    "contract_version": workbook["source_contract_version"],
                    "api_schema": workbook["api_schema"],
                    "workbook_schema": workbook["schema_version"],
                    "$defs": {"timestamp": workbook["mcp_definitions"]["timestamp"]},
                }
            )
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
            + ";\nconst mcpContract={contract_version:mcpWorkbook.source_contract_version,api_schema:mcpWorkbook.api_schema,workbook_schema:mcpWorkbook.schema_version,numeric_policy:mcpWorkbook.mcp_numeric_policy,$defs:mcpWorkbook.mcp_definitions,identity:mcpWorkbook.mcp_identity,valuation_contracts:mcpWorkbook.mcp_valuation_contracts};\n"
        )
    library = shared_helpers(name, groups)
    check = (
        ""
        if name == "Initialize MCP Run"
        else "mcpAssert(require('crypto').createHash('sha256').update(mcpStable(mcpWorkbook)).digest('hex')==='"
        + digest
        + "');\n"
    )
    return "// Generated contract and shared validation.\n" + binding + library + check


def generate():
    schema = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
    groups = read_groups()
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
        if source is None:
            filename = "-".join(name.lower().split()) + ".js"
            source = (DIRECTORY / filename).read_text()
        return node(name, "code", {"jsCode": prelude(name, groups) + source})

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
            p["options"]["outputFormatting"] = {
                "values": {"general": "FORMULA", "date": "FORMATTED_STRING"}
            }
            if header:
                p["options"]["dataLocationOnSheet"] = {
                    "values": {
                        "rangeDefinition": "specifyRange",
                        "headerRow": 1,
                        "firstDataRow": 1,
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
                    "response": {
                        "fullResponse": True,
                        "neverError": True,
                        "responseFormat": "text",
                        "outputPropertyName": "body",
                    }
                },
            },
        },
        executeOnce=True,
    )
    fetch_snapshot = node(
        "Fetch MCP Snapshot",
        "httpRequest",
        {
            "url": "={{ ($env.FINARY_BRIDGE_URL || 'http://finary-bridge:8000') + '/v1/snapshot' }}",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {
                        "name": "X-API-Key",
                        "value": "={{ $env.FINARY_BRIDGE_API_KEY || '' }}",
                    }
                ]
            },
            "options": {
                "timeout": 185000,
                "response": {
                    "response": {
                        "fullResponse": True,
                        "neverError": True,
                        "responseFormat": "text",
                        "outputPropertyName": "body",
                    }
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
        in {
            "n8n-nodes-base.code",
            "n8n-nodes-base.googleSheets",
            "n8n-nodes-base.httpRequest",
        }
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
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not path.exists() or path.read_text() != content:
            raise SystemExit("MCP workflow is stale")
    else:
        path.write_text(content)


if __name__ == "__main__":
    main()
