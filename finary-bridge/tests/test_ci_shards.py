"""CI shards remain complete, disjoint, deterministic and fail closed."""

import pytest
from ci_shards import Shard, parse_shard, partition_nodeids, select_nodeids


def test_weighted_partitions_are_complete_disjoint_and_deterministic():
    nodeids = [
        "tests/test_fast.py::test_case[0]",
        "tests/test_fast.py::test_case[1]",
        "tests/test_mcp_runtime.py::test_runtime_populated_empty_repeated_and_partial_preserves_manual",
        "tests/test_new_module.py::test_new_case",
    ]
    first = partition_nodeids(nodeids, 2)
    second = partition_nodeids(list(reversed(nodeids)), 2)

    assert first == second
    assert set(first[0]) | set(first[1]) == set(nodeids)
    assert set(first[0]).isdisjoint(first[1])
    assert "tests/test_new_module.py::test_new_case" in set().union(*map(set, first))


@pytest.mark.parametrize("value", ["", "0", "0/1", "2/2", "-1/2", "x/2", "0/x", "0/2/3"])
def test_invalid_shard_configuration_fails(value):
    with pytest.raises(pytest.UsageError):
        parse_shard(value)


def test_unexpected_empty_shard_fails():
    with pytest.raises(pytest.UsageError, match="selected no tests"):
        select_nodeids(["tests/test_only.py::test_case"], Shard(index=1, total=2))
