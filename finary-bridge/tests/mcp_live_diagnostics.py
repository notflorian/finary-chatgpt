"""Observe production validation without exposing instances or remote schemas."""

import json
import re
from decimal import Decimal, InvalidOperation
from itertools import islice

from mcp.client.session import ClientSession
from mcp.types import TextContent

import app.mcp_client as client
import app.mcp_validation as validation


def decimal_shape(value):
    """Report lexical categories and contract bounds, never digits or magnitude."""
    if not isinstance(value, str):
        return {"syntax": "NOT_TEXT"}
    if len(value) > 256:
        return {"syntax": "TEXT_TOO_LONG"}
    stripped = value.strip()
    result = {"surrounding_whitespace": value != stripped}
    plain = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
    if re.fullmatch(plain + r"[eE][+-]?[0-9]+", stripped):
        result["syntax"] = "SCIENTIFIC_NOTATION"
    elif re.fullmatch(plain, stripped):
        result["syntax"] = "PLAIN_DECIMAL"
    elif stripped.lower().lstrip("+-") in {"nan", "snan", "inf", "infinity"}:
        result["syntax"] = "NON_FINITE"
    else:
        result["syntax"] = "OTHER_TEXT"
    if result["syntax"] in {"PLAIN_DECIMAL", "SCIENTIFIC_NOTATION"}:
        try:
            _, digits, exponent = Decimal(stripped).as_tuple()
            limits = validation.CONTRACT["numeric_policy"]["limits"]
            result["integer_limit_exceeded"] = (
                max(len(digits) + exponent, 1) > limits["integer_digits"]
            )
            result["fraction_limit_exceeded"] = max(-exponent, 0) > limits["fractional_digits"]
            significant = list(digits)
            exact_exponent = exponent
            while significant and significant[-1] == 0:
                significant.pop()
                exact_exponent += 1
            if not significant:
                exact_exponent = 0
            result["exact_value_fits_bounds"] = (
                max(len(significant) + exact_exponent, 1) <= limits["integer_digits"]
                and max(-exact_exponent, 0) <= limits["fractional_digits"]
            )
            result["leading_plus"] = stripped.startswith("+")
            result["leading_zero_padding"] = bool(re.match(r"[+-]?0[0-9]", stripped))
        except (InvalidOperation, ValueError, TypeError):
            result["syntax"] = "UNSUPPORTED_DECIMAL"
    return result


def install_diagnostics(monkeypatch):
    state = {"stage": "SESSION_INITIALIZATION"}
    original_call = client.McpSession.call
    original_decode = client.decode_result
    original_validate = validation.validate
    original_sdk_validation = ClientSession.validate_tool_result

    async def traced_call(session, name, arguments):
        state.clear()
        state["stage"] = "TOOL_CALL"
        if name in validation.CONTRACT["capabilities"]:
            state["tool"] = name
        result = await original_call(session, name, arguments)
        state["stage"] = "NORMALIZATION"
        return result

    def traced_decode(result):
        state["stage"] = "NATIVE_RESULT_DECODING"
        try:
            value = original_decode(result)
        except client.McpFailure:
            shapes = []
            text_objects = []
            for block in result.content[:4]:
                if not isinstance(block, TextContent):
                    shapes.append("NON_TEXT")
                    continue
                try:
                    payload = json.loads(block.text, object_pairs_hook=client._object_pairs)
                    shapes.append("JSON_OBJECT" if isinstance(payload, dict) else "OTHER_JSON")
                    text_objects.append(payload)
                except (ValueError, RecursionError):
                    shapes.append("INVALID_JSON")
            state["native_shape"] = {
                "structured_present": result.structured_content is not None,
                "content": shapes,
                "more_content": len(result.content) > 4,
            }
            if result.structured_content is not None and len(text_objects) == 1:
                try:
                    state["native_shape"]["representations_match"] = json.dumps(
                        result.structured_content,
                        sort_keys=True,
                        allow_nan=False,
                    ) == json.dumps(text_objects[0], sort_keys=True, allow_nan=False)
                except (ValueError, TypeError, RecursionError):
                    state["native_shape"]["representations_match"] = False
            raise
        state["stage"] = "DECLARED_OUTPUT_SCHEMA"
        return value

    async def traced_sdk_validation(session, name, result):
        state["stage"] = "SDK_OUTPUT_SCHEMA"
        return await original_sdk_validation(session, name, result)

    def traced_validate(name, value):
        try:
            return original_validate(name, value)
        except ValueError:
            state["stage"] = "CONTRACT_VALIDATION"
            if name in validation.CONTRACT["$defs"]:
                state["contract"] = name
                rules = []
                try:
                    pending = list(islice(validation.schema_validator(name).iter_errors(value), 8))
                    visited = 0
                    while pending and len(rules) < 8 and visited < 64:
                        error = pending.pop(0)
                        visited += 1
                        if error.context:
                            pending.extend(error.context[:8])
                            continue
                        # These paths belong to the checked-in schema, never the instance.
                        rule = {"schema_path": list(error.absolute_schema_path)}
                        if (
                            error.validator == "pattern"
                            and error.validator_value
                            == validation.CONTRACT["$defs"]["decimal"]["pattern"]
                        ):
                            rule["decimal_shape"] = decimal_shape(error.instance)
                        if error.validator == "required" and isinstance(error.instance, dict):
                            rule["missing_fields"] = [
                                key for key in error.validator_value if key not in error.instance
                            ][:8]
                        if rule not in rules:
                            rules.append(rule)
                    state["rules"] = rules
                except Exception:
                    state["rules"] = []
            raise

    monkeypatch.setattr(client.McpSession, "call", traced_call)
    monkeypatch.setattr(client, "decode_result", traced_decode)
    monkeypatch.setattr(client, "validate", traced_validate)
    monkeypatch.setattr(validation, "validate", traced_validate)
    monkeypatch.setattr(ClientSession, "validate_tool_result", traced_sdk_validation)

    def report(error):
        outcome = dict(state)
        outcome["code"] = error.code if isinstance(error, client.McpFailure) else "CHECK_FAILED"
        print(json.dumps({"structural_diagnostic": outcome}))

    return report
