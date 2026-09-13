"""Only explicit remote grant rejection counts as revocation evidence."""

import pytest
from mcp_live_revocation import access_outcome, refresh_outcome


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (400, {"error": "invalid_grant"}, "REJECTED_INVALID_GRANT"),
        (401, {"error": "invalid_client"}, "INCONCLUSIVE"),
        (400, {"error": "invalid_scope"}, "INCONCLUSIVE"),
        (500, {"error": "invalid_grant"}, "INCONCLUSIVE"),
        (200, {"access_token": "synthetic-only"}, "STILL_ACCEPTED"),
        (200, {}, "INCONCLUSIVE"),
        (400, "secret-bearing provider failure", "INCONCLUSIVE"),
    ],
)
def test_remote_refresh_outcome(status, payload, expected):
    assert refresh_outcome(status, payload) == expected


@pytest.mark.parametrize(
    "connected,statuses,expected",
    [
        (True, [200], "STILL_ACCEPTED"),
        (False, [401], "REJECTED_HTTP_401"),
        (False, [403], "INCONCLUSIVE"),
        (False, [500], "INCONCLUSIVE"),
        (False, [], "INCONCLUSIVE"),
    ],
)
def test_remote_access_outcome(connected, statuses, expected):
    assert access_outcome(connected, statuses) == expected
