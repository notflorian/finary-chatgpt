# Finary authentication investigation

## Decision

Phase 8 concludes with **Outcome A: secure persisted Clerk session accepted and
implemented**.

The accepted design persists only the Clerk session identifier and the value of
the production `__client` cookie. Clerk uses those values to mint a new
short-lived session JWT through its normal session-token endpoint. The bridge
does not persist that JWT, a TOTP secret, backup code, one-time MFA code, raw
authentication response, browser profile, or mailbox credential.

On 2026-08-21, an opt-in live test authenticated once with TOTP, created two
fresh clients without another factor, refreshed the session, and performed a
harmless account-structure request. A subsequent independent Python process
also loaded the same protected file and completed the request without MFA.
The state was then placed in the dedicated Compose volume and survived two
bridge-container restarts, reaching only the expected liability-coverage gate.
This establishes routine process/container-restart reuse while the upstream
session remains valid. It does not promise permanent zero-touch authentication.

The production schedule remains inactive for the independent Phase 7 liability
coverage blocker. Successful authentication still leads schema `1.0`
`GET /v1/snapshot` to `FINARY_FEATURE_UNAVAILABLE` while liability coverage is
not verified complete.

## Verified upstream mechanism

### Current Finary and library behavior

Finary currently uses Clerk at `clerk.finary.com`. The account flow was
live-observed to require password plus TOTP. The public Clerk configuration
also exposes email-code and interactive Apple/Google strategies, but no user
API key, passkey, trusted-device credential, service account, or user-managed
machine credential suitable for this bridge.

The inspected `finary_uapi` release is `0.2.3`, revision
[`be147ce47eb0acb3b8f2b1d2152c551953e775bd`](https://github.com/lasconic/finary_uapi/tree/be147ce47eb0acb3b8f2b1d2152c551953e775bd).
Its sign-in helper records a cookie jar, Clerk session ID, and current JWT. Its
authentication helper reloads the cookie jar and session ID, then calls:

```text
POST https://clerk.finary.com/v1/client/sessions/{session_id}/tokens
```

The Phase 8 live test narrowed the required restart state further:

- required cookie: production Clerk `__client` on `.clerk.finary.com`;
- required identifier: Clerk session ID;
- client ID: not separately required;
- bearer JWT: not required in persistent storage; the endpoint returns a new
  `jwt`;
- `__client_uat`, Cloudflare cookies, and arbitrary cookie-jar contents: not
  required by the verified bridge flow;
- cookies may rotate, so the bridge atomically saves the current `__client`
  value after every successful refresh;
- the session ID did not rotate in the verified flow. The bridge preserves the
  identifier that names the refreshed session.

This is Clerk's normal production session model, not an invented endpoint.
[Clerk documents](https://clerk.com/docs/guides/how-clerk-works/overview) that
the long-lived client token is held in `__client`, session JWTs normally last
about 60 seconds, and frontend clients refresh them about every 50 seconds via
`/client/sessions/{id}/tokens`. The bridge uses a conservative 45-second
in-process refresh interval and the same supported endpoint.

### Lifetime and revocation

The session JWT lifetime is approximately 60 seconds. The persisted `__client`
state represents the longer Clerk session, not an indefinitely valid refresh
token. Clerk requires an inactivity timeout and/or maximum lifetime; those
values are configured by Finary and are not disclosed by the inspected public
configuration. The bridge therefore does not claim a specific absolute or idle
lifetime.

[Clerk documents](https://clerk.com/docs/guides/secure/session-options) that a
session ends at its configured inactivity timeout or maximum lifetime.
[Revoking a session](https://clerk.com/docs/reference/backend/sessions/revoke-session)
signs its associated client out. A rejected refresh (`401` or `403`) causes the
bridge to clear the local state and return `FINARY_AUTH_FAILED`; no automatic
password/MFA loop occurs. A timeout or temporary non-authentication upstream
failure preserves the last valid file for a later bounded retry.

A password change does not universally prove that other sessions were revoked:
Clerk exposes `signOutOfOtherSessions` as an explicit password-update option.
Likewise, no inspected source proves that changing an MFA factor always revokes
existing sessions. After a password change, MFA-factor rotation, suspected
compromise, or logout-all operation, the operator must explicitly sign out or
revoke upstream sessions and clear the local store. The next request then
requires a new password-plus-MFA bootstrap.

## Threat model

| Credential | Consequence if stolen | Lifetime and recovery | Decision |
| --- | --- | --- | --- |
| Password | Enables the first sign-in factor and may expose other account actions; this account still requires MFA for a new session | Valid until password rotation | Already accepted in protected local configuration |
| TOTP seed or backup code | A TOTP seed generates future MFA codes until factor rotation; a backup code can satisfy recovery authentication | Stronger ability to create new sessions; recovery requires factor/code rotation | Strictly prohibited |
| Persisted Clerk session | Bearer-equivalent access to the already-created Clerk session and ability to mint short-lived JWTs while it remains valid | Bound by Finary's Clerk session lifetime; server-revocable; cannot create a new session after expiry/revocation without password plus MFA | Accepted only in the bridge-only protected store |

The session file is sensitive: theft can impersonate the existing session
until expiry or revocation. Its blast radius is nevertheless narrower than a
TOTP seed because it does not generate future factors and cannot establish a
new session after the current one is invalidated. This proportionality, normal
Clerk refresh support, live restart verification, local isolation, and explicit
revocation make the trade-off acceptable for routine local restarts.

## Storage design

`FINARY_SESSION_PATH` selects the session file. Direct local runs have no
default and therefore persist nothing unless the operator opts in. Compose
sets it to:

```text
/var/lib/finary-session/state/session.json
```

The `finary_session_data` named volume is mounted only into `finary-bridge` at
`/var/lib/finary-session`. It is not mounted into n8n or `schema-server` and is
not a host bind mount. The file is outside the repository and Docker build
context.

The strict versioned JSON format contains exactly:

```json
{
  "client_cookie": "<sensitive value>",
  "session_id": "<sensitive value>",
  "version": 1
}
```

Actual values must never be printed, committed, copied into diagnostics, or
placed in documentation. The store:

- requires an absolute path;
- creates and validates an owner-only `0700` directory;
- validates an owner-only regular `0600` file and rejects symlinks;
- validates exact fields, types, lengths, version, and maximum file size;
- writes and `fsync`s a same-directory temporary file before atomic replace;
- retains the old state if replacement fails;
- never uses pickle or persists full upstream objects.

Application-level encryption is not used. A decryption key stored next to this
single-host file would not create a meaningful boundary. The chosen boundary is
the local OS, restrictive permissions, Docker volume isolation, and access to
the Docker host. Host administrators and an attacker with root/Docker-daemon
control remain able to read the state and are outside this file-level boundary.
A separately managed encryption key could be added only if a real independent
key boundary is introduced later.

The session volume is deliberately **not backed up**. Disaster recovery
restores n8n separately and requires a fresh MFA bootstrap, avoiding bearer
state in generic backups.

## Authentication lifecycle

1. On a request requiring Finary, the process-local singleton client acquires
   an authentication lock.
2. If its in-memory JWT is younger than 45 seconds, it is reused.
3. Otherwise the adapter loads the protected session state and calls Clerk's
   token endpoint.
4. On success, it uses the returned JWT only in memory and atomically saves the
   current `__client` state.
5. If no session file exists, the existing password flow runs. An explicit
   `FINARY_MFA_CODE` or injected interactive provider may complete MFA. The
   one-time code is discarded immediately after the attempt.
6. If the session is expired or revoked, refresh is rejected, the file is
   cleared, and the API returns the sanitized `FINARY_AUTH_FAILED` response.
7. Malformed, truncated, incompatible, insecurely permissioned, or unreadable
   stored state also fails safely as `FINARY_AUTH_FAILED`. `GET /health` neither
   loads the file nor contacts Clerk.

The lock prevents simultaneous requests in one process from refreshing and
rewriting the same session or starting duplicate bootstrap flows. It is not a
distributed lock; the supported Compose topology runs one bridge process
against the volume.

## Manual bootstrap and restart verification

Use the protected Compose volume for normal operation. Supply a current
one-time code only for bootstrap:

```bash
set -a
source .env.live
set +a
read -s "FINARY_MFA_CODE?Enter the current Finary TOTP code: "
echo
export FINARY_MFA_CODE
docker compose up -d --build --force-recreate finary-bridge
unset FINARY_MFA_CODE
```

Trigger one authenticated request while the code is current. A schema `1.0`
response of `FINARY_FEATURE_UNAVAILABLE` is sufficient to prove that
authentication reached the independent liability gate. Then recreate the
bridge without `FINARY_MFA_CODE` and repeat the request. Authentication should
reuse the persisted Clerk session; it must not prompt.

The repository also provides the explicit, credential-safe live test:

```bash
FINARY_LIVE_SESSION_TEST=1 \
  python -m pytest -m live tests/live/test_finary_session_live.py -vv -s --tb=no
```

It requires an absolute, empty `FINARY_SESSION_PATH`, prompts once, creates two
fresh clients, refreshes each, and performs only structural account reads. Its
sanitized success messages expose no identifiers, tokens, cookies, factors, or
portfolio values. The acceptance run additionally verified a separate process
and two Compose container restarts.

## Revocation and recovery

To invalidate local authentication:

1. stop `finary-bridge`;
2. sign out all Finary sessions, or otherwise revoke the relevant session in
   Finary/Clerk where supported;
3. remove the bridge's session file or the dedicated session volume;
4. update `FINARY_PASSWORD` if it changed;
5. restart and explicitly bootstrap once with a fresh MFA code.

Clearing only the local file prevents this bridge from using it but does not
itself revoke a copied session. Upstream logout/revocation is required after
suspected compromise. Password or MFA changes should be paired with explicit
session revocation because automatic invalidation was not proven.

## Security boundary and remaining gate

The session state remains inside `finary-bridge`. It is absent from n8n
environment variables, workflow exports, Google Sheets, ChatGPT, repository
files, logs, normal diagnostics, and normal backups. n8n continues to call only
the stable bridge API.

Phase 8 resolves the routine restart-authentication blocker. It does not enable
the production schedule because Phase 7 Outcome B remains unchanged:
`PARTIAL` and `UNAVAILABLE` liability coverage still produce
`FINARY_FEATURE_UNAVAILABLE`, schema `1.0` is unchanged, and schema `2.0` is not
implemented. Issue #15 remains out of scope.
