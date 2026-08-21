"""Isolated adapter for Finary's private upstream API.

The authentication flow and read endpoints in this module were verified against
the public source of ``finary_uapi`` 0.2.3. Private response envelopes are
validated and retained behind adapter-owned containers so no other application
module needs to import an upstream library or know endpoint details.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol, cast

from curl_cffi.requests import Session
from curl_cffi.requests import exceptions as curl_exceptions

logger = logging.getLogger(__name__)

_API_ROOT: Final = "https://api.finary.com"
_APP_ROOT: Final = "https://app.finary.com"
_CLERK_ROOT: Final = "https://clerk.finary.com"
_SIGN_IN_URL: Final = f"{_CLERK_ROOT}/v1/client/sign_ins"
_IMPERSONATE_BROWSER: Final = "chrome110"
_DEFAULT_TIMEOUT_SECONDS: Final = 20.0


class FinaryClientError(Exception):
    """Base class for sanitized application-level Finary failures."""

    code: str = "FINARY_UPSTREAM_ERROR"
    retryable: bool = True


class FinaryAuthenticationError(FinaryClientError):
    """Authentication is unavailable, incomplete, or rejected."""

    code = "FINARY_AUTH_FAILED"
    retryable = False


class FinaryUpstreamTimeoutError(FinaryClientError):
    """The upstream API exceeded the configured request timeout."""

    code = "FINARY_UPSTREAM_TIMEOUT"


class FinaryMalformedResponseError(FinaryClientError):
    """The upstream API returned an unexpected or undecodable response."""

    code = "FINARY_MALFORMED_RESPONSE"
    retryable = False


class FinaryFeatureUnavailableError(FinaryClientError):
    """The verified upstream API surface does not expose a requested feature."""

    code = "FINARY_FEATURE_UNAVAILABLE"
    retryable = False


class FinaryUpstreamError(FinaryClientError):
    """A sanitized non-timeout upstream transport or API failure."""


@dataclass(frozen=True, slots=True)
class FinaryCredentials:
    """Credentials loaded from the bridge process environment."""

    email: str = field(repr=False)
    password: str = field(repr=False)
    mfa_code: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> FinaryCredentials:
        """Load credentials without reading or logging any credential value."""

        source = os.environ if environment is None else environment
        email = source.get("FINARY_EMAIL", "").strip()
        password = source.get("FINARY_PASSWORD", "")
        mfa_code = source.get("FINARY_MFA_CODE") or None
        if not email or not password:
            raise FinaryAuthenticationError("Finary credentials are not configured")
        return cls(email=email, password=password, mfa_code=mfa_code)


class FinaryPositionKind(StrEnum):
    """Verified upstream collections that may later produce normalized positions."""

    SECURITIES = "securities"
    CRYPTOS = "cryptos"
    EURO_FUNDS = "fonds_euro"
    CROWDLENDINGS = "crowdlendings"
    GENERIC_ASSETS = "generic_assets"
    PRECIOUS_METALS = "precious_metals"
    REAL_ESTATES = "real_estates"
    SCPIS = "scpis"
    STARTUPS = "startups"


class FinaryLiabilityCoverage(StrEnum):
    """Adapter-owned evidence state for upstream liability completeness."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FinaryRawAccounts:
    """Adapter-owned raw account records from the verified accounts endpoint."""

    records: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class FinaryRawPositionGroup:
    """Raw records for one verified upstream position collection."""

    kind: FinaryPositionKind
    records: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class FinaryRawPositions:
    """All verified upstream collections needed for later position normalization."""

    groups: tuple[FinaryRawPositionGroup, ...]


@dataclass(frozen=True, slots=True)
class FinaryRawLiabilities:
    """Liability records plus an explicit upstream completeness decision.

    An empty record tuple is meaningful only when ``coverage`` is ``COMPLETE``.
    This prevents an empty nested or partially retrieved loan collection from
    being silently interpreted as proof of zero liabilities.
    """

    records: tuple[Mapping[str, object], ...]
    coverage: FinaryLiabilityCoverage


class FinaryClient(Protocol):
    """Internal boundary consumed by later bridge services."""

    def authenticate(self) -> None:
        """Authenticate and retain an in-memory upstream session."""

    def get_accounts(self) -> FinaryRawAccounts:
        """Retrieve raw upstream account records."""

    def get_positions(self) -> FinaryRawPositions:
        """Retrieve raw records from verified position collections."""

    def get_liabilities(self) -> FinaryRawLiabilities:
        """Retrieve liabilities or raise when the upstream feature is unavailable."""


class _HttpResponse(Protocol):
    status_code: int

    def json(self) -> object:
        """Decode an HTTP response body."""


class _HttpSession(Protocol):
    headers: MutableMapping[str, str]
    impersonate: str

    def get(self, url: str, *, timeout: float) -> _HttpResponse:
        """Issue a GET request."""

    def post(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        headers: Mapping[str, str],
        impersonate: str,
        timeout: float,
    ) -> _HttpResponse:
        """Issue a form-encoded POST request."""


_SessionFactory = Callable[[], _HttpSession]
_SecondFactorCodeProvider = Callable[[str], str]


def _create_session() -> _HttpSession:
    return cast(_HttpSession, Session())


_POSITION_ENDPOINTS: Final[tuple[tuple[FinaryPositionKind, str], ...]] = (
    (FinaryPositionKind.SECURITIES, f"{_API_ROOT}/users/me/securities"),
    (FinaryPositionKind.CRYPTOS, f"{_API_ROOT}/users/me/cryptos"),
    (FinaryPositionKind.EURO_FUNDS, f"{_API_ROOT}/users/me/fonds_euro"),
    (FinaryPositionKind.CROWDLENDINGS, f"{_API_ROOT}/users/me/crowdlendings"),
    (FinaryPositionKind.GENERIC_ASSETS, f"{_API_ROOT}/users/me/generic_assets"),
    (FinaryPositionKind.PRECIOUS_METALS, f"{_API_ROOT}/users/me/precious_metals"),
    (FinaryPositionKind.REAL_ESTATES, f"{_API_ROOT}/users/me/real_estates"),
    (FinaryPositionKind.SCPIS, f"{_API_ROOT}/users/me/scpis"),
    (FinaryPositionKind.STARTUPS, f"{_API_ROOT}/users/me/startups"),
)


class FinaryApiClient:
    """Private Finary API adapter with sanitized errors and in-memory auth state."""

    def __init__(
        self,
        credentials: FinaryCredentials,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        session_factory: _SessionFactory = _create_session,
        second_factor_code_provider: _SecondFactorCodeProvider | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._credentials = credentials
        self._timeout_seconds = timeout_seconds
        self._session = session_factory()
        self._second_factor_code_provider = second_factor_code_provider
        self._authenticated = False

    @classmethod
    def from_environment(
        cls,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        environment: Mapping[str, str] | None = None,
        second_factor_code_provider: _SecondFactorCodeProvider | None = None,
    ) -> FinaryApiClient:
        """Build the adapter from the documented Finary environment variables."""

        return cls(
            FinaryCredentials.from_environment(environment),
            timeout_seconds=timeout_seconds,
            second_factor_code_provider=second_factor_code_provider,
        )

    def authenticate(self) -> None:
        """Authenticate through Clerk password, TOTP, or email-code flows."""

        __tracebackhide__ = True

        if self._authenticated:
            return

        logger.info(
            "Finary authentication started",
            extra={"event": "finary.authentication.started"},
        )
        payload = self._post_authentication(
            _SIGN_IN_URL,
            {
                "identifier": self._credentials.email,
                "password": self._credentials.password,
            },
        )
        payload = self._complete_second_factor_if_needed(payload)
        self._raise_for_authentication_errors(payload)
        session_token = self._extract_session_token(payload)

        self._session.headers.update({"authorization": f"Bearer {session_token}"})
        self._session.impersonate = _IMPERSONATE_BROWSER
        self._authenticated = True
        logger.info(
            "Finary authentication completed",
            extra={"event": "finary.authentication.succeeded"},
        )

    def get_accounts(self) -> FinaryRawAccounts:
        """Retrieve all holding accounts exposed by the verified API surface."""

        self._require_authenticated()
        records = self._get_entity_records(
            f"{_API_ROOT}/users/me/holdings_accounts", operation="accounts"
        )
        logger.info(
            "Finary accounts retrieved",
            extra={"event": "finary.accounts.retrieved", "entity_count": len(records)},
        )
        return FinaryRawAccounts(records=records)

    def get_positions(self) -> FinaryRawPositions:
        """Retrieve each verified asset collection without normalizing its fields."""

        self._require_authenticated()
        groups = tuple(
            FinaryRawPositionGroup(
                kind=kind,
                records=self._get_entity_records(endpoint, operation=kind.value),
            )
            for kind, endpoint in _POSITION_ENDPOINTS
        )
        logger.info(
            "Finary position collections retrieved",
            extra={
                "event": "finary.positions.retrieved",
                "collection_count": len(groups),
                "entity_count": sum(len(group.records) for group in groups),
            },
        )
        return FinaryRawPositions(groups=groups)

    def get_liabilities(self) -> FinaryRawLiabilities:
        """Report the missing verified liability read API explicitly."""

        logger.warning(
            "Finary liabilities are unavailable in the verified upstream surface",
            extra={"event": "finary.liabilities.unavailable"},
        )
        raise FinaryFeatureUnavailableError(
            "Liability retrieval is unavailable in the verified upstream API surface"
        )

    def _complete_second_factor_if_needed(
        self, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        self._raise_for_authentication_errors(payload)
        response = _require_mapping(payload.get("response"), "authentication response")
        status_value = response.get("status")
        if status_value not in ("needs_second_factor", "needs_client_trust"):
            return payload

        sign_in_id = response.get("id")
        if not isinstance(sign_in_id, str) or not sign_in_id:
            raise FinaryMalformedResponseError(
                "Finary authentication response is missing its sign-in identifier"
            )

        strategies = _extract_factor_strategies(response)
        if "totp" in strategies and self._credentials.mfa_code:
            return self._attempt_second_factor(
                sign_in_id, strategy="totp", code=self._credentials.mfa_code
            )
        if "email_code" in strategies and self._second_factor_code_provider:
            return self._complete_email_code_factor(response, sign_in_id)
        if "totp" in strategies and self._second_factor_code_provider:
            code = self._request_second_factor_code("totp")
            return self._attempt_second_factor(sign_in_id, strategy="totp", code=code)

        strategy_summary = ", ".join(strategies) if strategies else "unknown"
        raise FinaryAuthenticationError(
            "Finary MFA is required but not configured "
            f"(supported strategies: {strategy_summary})"
        )

    def _complete_email_code_factor(
        self, response: Mapping[str, object], sign_in_id: str
    ) -> Mapping[str, object]:
        factor = _find_factor(response, "email_code")
        if factor is None:
            raise FinaryMalformedResponseError(
                "Finary email-code factor is missing from the authentication response"
            )
        email_address_id = factor.get("email_address_id")
        if not isinstance(email_address_id, str) or not email_address_id:
            raise FinaryMalformedResponseError(
                "Finary email-code factor is missing its email address identifier"
            )

        prepare_url = (
            f"{_CLERK_ROOT}/v1/client/sign_ins/{sign_in_id}/prepare_second_factor"
        )
        prepared_payload = self._post_authentication(
            prepare_url,
            {"strategy": "email_code", "email_address_id": email_address_id},
        )
        self._raise_for_authentication_errors(prepared_payload)
        code = self._request_second_factor_code("email_code")
        return self._attempt_second_factor(
            sign_in_id, strategy="email_code", code=code
        )

    def _request_second_factor_code(self, strategy: str) -> str:
        provider = self._second_factor_code_provider
        if provider is None:
            raise FinaryAuthenticationError(
                f"Finary {strategy} verification code is required"
            )
        try:
            code = provider(strategy).strip()
        except (EOFError, OSError):
            raise FinaryAuthenticationError(
                f"Finary {strategy} verification code could not be read"
            ) from None
        if not code:
            raise FinaryAuthenticationError(
                f"Finary {strategy} verification code was not provided"
            )
        return code

    def _attempt_second_factor(
        self, sign_in_id: str, *, strategy: str, code: str
    ) -> Mapping[str, object]:
        second_factor_url = (
            f"{_CLERK_ROOT}/v1/client/sign_ins/{sign_in_id}/attempt_second_factor"
        )
        return self._post_authentication(
            second_factor_url,
            {"strategy": strategy, "code": code},
        )

    def _post_authentication(
        self, url: str, data: Mapping[str, str]
    ) -> Mapping[str, object]:
        __tracebackhide__ = True
        headers = {
            "Accept-Encoding": "identity",
            "Origin": _APP_ROOT,
            "Referer": _APP_ROOT,
            "User-Agent": "finary-bridge/0.1.0",
        }
        try:
            response = self._session.post(
                url,
                data=data,
                headers=headers,
                impersonate=_IMPERSONATE_BROWSER,
                timeout=self._timeout_seconds,
            )
        except curl_exceptions.Timeout:
            raise FinaryUpstreamTimeoutError(
                "Finary authentication request timed out"
            ) from None
        except curl_exceptions.RequestException:
            raise FinaryUpstreamError("Finary authentication request failed") from None
        return self._decode_response(response, authentication=True)

    def _get_entity_records(
        self, url: str, *, operation: str
    ) -> tuple[Mapping[str, object], ...]:
        __tracebackhide__ = True
        try:
            response = self._session.get(url, timeout=self._timeout_seconds)
        except curl_exceptions.Timeout:
            raise FinaryUpstreamTimeoutError(
                f"Finary {operation} request timed out"
            ) from None
        except curl_exceptions.RequestException:
            raise FinaryUpstreamError(f"Finary {operation} request failed") from None

        payload = self._decode_response(response, authentication=False)
        if set(("message", "error", "result")) - payload.keys():
            raise FinaryMalformedResponseError(
                f"Finary {operation} response is missing its result envelope"
            )
        if payload["error"] is not None:
            raise FinaryUpstreamError(f"Finary {operation} request returned an error")
        if payload["message"] != "OK":
            raise FinaryMalformedResponseError(
                f"Finary {operation} response has an unexpected status message"
            )
        result = payload["result"]
        if not isinstance(result, list):
            raise FinaryMalformedResponseError(
                f"Finary {operation} result must be a list"
            )

        records: list[Mapping[str, object]] = []
        for item in result:
            if not isinstance(item, Mapping):
                raise FinaryMalformedResponseError(
                    f"Finary {operation} result contains a non-object item"
                )
            records.append(deepcopy(dict(item)))
        return tuple(records)

    def _decode_response(
        self, response: _HttpResponse, *, authentication: bool
    ) -> Mapping[str, object]:
        __tracebackhide__ = True
        if response.status_code in (401, 403):
            raise FinaryAuthenticationError("Finary rejected the authenticated session")
        if response.status_code != 200:
            if authentication:
                raise FinaryAuthenticationError("Finary authentication was rejected")
            raise FinaryUpstreamError("Finary returned an unexpected HTTP status")
        try:
            payload = response.json()
        except (ValueError, curl_exceptions.RequestException):
            raise FinaryMalformedResponseError(
                "Finary returned an undecodable JSON response"
            ) from None
        if not isinstance(payload, Mapping):
            raise FinaryMalformedResponseError("Finary response must be a JSON object")
        return cast(Mapping[str, object], payload)

    def _raise_for_authentication_errors(self, payload: Mapping[str, object]) -> None:
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            raise FinaryAuthenticationError("Finary authentication failed")

    def _extract_session_token(self, payload: Mapping[str, object]) -> str:
        self._raise_for_authentication_errors(payload)
        response = _require_mapping(payload.get("response"), "authentication response")
        if response.get("status") != "complete":
            raise FinaryAuthenticationError("Finary authentication did not complete")

        client = _require_mapping(payload.get("client"), "authentication client")
        sessions = client.get("sessions")
        if not isinstance(sessions, list) or not sessions:
            raise FinaryMalformedResponseError(
                "Finary authentication response is missing its session"
            )
        session = _require_mapping(sessions[0], "authentication session")
        active_token = _require_mapping(
            session.get("last_active_token"), "authentication session token"
        )
        session_token = active_token.get("jwt")
        if not isinstance(session_token, str) or not session_token:
            raise FinaryMalformedResponseError(
                "Finary authentication response is missing its session token"
            )
        return session_token

    def _require_authenticated(self) -> None:
        if not self._authenticated:
            raise FinaryAuthenticationError("Finary client is not authenticated")


def _require_mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FinaryMalformedResponseError(f"Finary {description} must be an object")
    return cast(Mapping[str, object], value)


def _extract_factor_strategies(response: Mapping[str, object]) -> tuple[str, ...]:
    """Return only non-sensitive Clerk factor strategy names for diagnostics."""

    factors = response.get("supported_second_factors")
    if not isinstance(factors, list):
        return ()

    strategies: list[str] = []
    for factor in factors:
        if not isinstance(factor, Mapping):
            continue
        strategy = factor.get("strategy")
        if isinstance(strategy, str) and strategy and strategy not in strategies:
            strategies.append(strategy)
    return tuple(strategies)


def _find_factor(
    response: Mapping[str, object], strategy: str
) -> Mapping[str, object] | None:
    factors = response.get("supported_second_factors")
    if not isinstance(factors, list):
        return None
    for factor in factors:
        if isinstance(factor, Mapping) and factor.get("strategy") == strategy:
            return cast(Mapping[str, object], factor)
    return None
