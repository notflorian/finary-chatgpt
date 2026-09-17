"""Shared credential-free isolation and bounded pytest worker configuration."""

import os

import pytest
from ci_shards import parse_shard, select_nodeids

_LOCAL_DEFAULT_WORKER_COUNT = 2
_CI_MAX_WORKER_COUNT = 4


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--ci-shard",
        action="store",
        default=None,
        metavar="INDEX/TOTAL",
        help="Run one deterministic weighted CI test partition.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    value = config.getoption("--ci-shard")
    if value is None:
        return
    selected_nodeids = select_nodeids([item.nodeid for item in items], parse_shard(value))
    selected, deselected = [], []
    for item in items:
        (selected if item.nodeid in selected_nodeids else deselected).append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


def _parse_worker_count_override(raw_value: str) -> int:
    try:
        parsed = int(raw_value)
    except ValueError as exc:  # pragma: no cover - defensive path
        raise pytest.UsageError(
            "PYTEST_XDIST_WORKER_COUNT must be a positive integer."
        ) from exc
    if parsed < 1:
        raise pytest.UsageError("PYTEST_XDIST_WORKER_COUNT must be at least 1.")
    return parsed


def _determine_xdist_worker_count(*, env: dict[str, str], cpu_count: int | None) -> int:
    override = env.get("PYTEST_XDIST_WORKER_COUNT")
    if override:
        return _parse_worker_count_override(override)

    if env.get("CI") != "true":
        return _LOCAL_DEFAULT_WORKER_COUNT

    if cpu_count is None or cpu_count < 1:
        return _LOCAL_DEFAULT_WORKER_COUNT

    return min(max(cpu_count - 1, _LOCAL_DEFAULT_WORKER_COUNT), _CI_MAX_WORKER_COUNT)


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    del config  # unused, hook signature required by pytest-xdist
    return _determine_xdist_worker_count(env=dict(os.environ), cpu_count=os.cpu_count())


@pytest.fixture(autouse=True)
def isolated_bridge_environment(monkeypatch, request):
    """Normal tests never inherit operator authentication or dependency overrides."""
    if request.node.get_closest_marker("live"):
        return
    from app.main import app

    for name in (
        "FINARY_BRIDGE_API_KEY", "FINARY_MCP_STATE_PATH", "FINARY_PROVIDER",
        "FINARY_EMAIL", "FINARY_PASSWORD", "FINARY_MFA_CODE", "FINARY_SESSION_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app, "dependency_overrides", {})
