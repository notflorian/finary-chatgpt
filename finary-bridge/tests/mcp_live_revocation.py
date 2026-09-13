"""Structural classification of explicit server-side revocation evidence."""


def refresh_outcome(status, payload):
    if not isinstance(payload, dict):
        return "INCONCLUSIVE"
    if status == 400 and payload.get("error") == "invalid_grant":
        return "REJECTED_INVALID_GRANT"
    if status == 200 and isinstance(payload.get("access_token"), str) and payload["access_token"]:
        return "STILL_ACCEPTED"
    return "INCONCLUSIVE"


def access_outcome(connected, statuses):
    if connected:
        return "STILL_ACCEPTED"
    if 401 in statuses:
        return "REJECTED_HTTP_401"
    return "INCONCLUSIVE"
