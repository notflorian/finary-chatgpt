"""Deterministic weighted pytest partitions for the two expensive CI suites."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class Shard:
    index: int
    total: int


_WEIGHTS = (
    ("test_runtime_populated_empty_repeated_and_partial_preserves_manual", 79),
    ("test_native_restored_execution_number_gets_new_uuid", 45),
    ("test_runtime_exhausted_retry_then_valid_recovery", 39),
    ("test_native_terminal_response_loss_preserves_finalized_identity[True]", 32),
    ("test_real_engine_control_flow[write_failure]", 32),
    ("test_runtime_inventory_rejection_precedes_first_portfolio_write", 29),
    ("test_native_terminal_response_loss_preserves_finalized_identity[False]", 27),
    ("test_engine_rejects_malformed_timestamps_before_portfolio_writes", 26),
    ("test_runtime_captures_complete_large_cli_evidence", 26),
    ("test_initializer_bridge_engine_connector_consumer_round_trip", 23),
    ("test_mcp_runtime.py::", 15),
    ("test_derived_key_corruption_cannot_be_hidden", 20),
    ("test_every_retained_derived_key_precedes_consumer_selection", 10),
    ("test_readback_cli_rejects_unselected_derived_keys", 8),
    ("test_retained_encoding_and_decoded_ordinals_match_exported_keys", 8),
    ("test_unselected_failed_rows_must_have_one_valid_terminal_and_schema", 8),
    ("test_submillisecond_completion_selection_and_series", 8),
    ("test_native_service_warning_deduplication_avoids_accumulated_list_scans[1000]", 7),
)


def parse_shard(value: str) -> Shard:
    try:
        raw_index, raw_total = value.split("/", 1)
        shard = Shard(index=int(raw_index), total=int(raw_total))
    except (TypeError, ValueError) as exc:
        raise pytest.UsageError("--ci-shard must use INDEX/TOTAL integers.") from exc
    if shard.total < 2:
        raise pytest.UsageError("--ci-shard TOTAL must be at least 2.")
    if not 0 <= shard.index < shard.total:
        raise pytest.UsageError("--ci-shard INDEX must be within the shard range.")
    return shard


def estimated_weight(nodeid: str) -> int:
    for marker, weight in _WEIGHTS:
        if marker in nodeid:
            return weight
    return 1


def partition_nodeids(nodeids: list[str], total: int) -> tuple[tuple[str, ...], ...]:
    if total < 2:
        raise pytest.UsageError("CI shard count must be at least 2.")
    assignments: list[list[str]] = [[] for _ in range(total)]
    loads = [0] * total
    for nodeid in sorted(nodeids, key=lambda item: (-estimated_weight(item), item)):
        target = min(range(total), key=lambda index: (loads[index], index))
        assignments[target].append(nodeid)
        loads[target] += estimated_weight(nodeid)
    return tuple(tuple(assignment) for assignment in assignments)


def select_nodeids(nodeids: list[str], shard: Shard) -> set[str]:
    selected = set(partition_nodeids(nodeids, shard.total)[shard.index])
    if not selected:
        raise pytest.UsageError(f"CI shard {shard.index}/{shard.total} selected no tests.")
    return selected
