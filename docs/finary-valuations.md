# Verified SCPI and crypto valuation evidence

The bridge recognizes two current dedicated-collection formats: `user_crypto`
with `owning_type` equal to `hodled` or `staked`, and `user_scpi` with
`property_type` equal to `full_ownership`, `bare_ownership` or `usufruct`. This
note records the amount-specific evidence behind those rules, investigated on
2026-09-08. Other formats remain conservative.
The original `UserCrypto` and `UserScpi` fixtures still have unknown EUR values.

## Sources and verification

The referenced upstream client,
[finary_uapi 0.2.3](https://github.com/lasconic/finary_uapi/tree/be147ce47eb0acb3b8f2b1d2152c551953e775bd),
confirms the dedicated GET endpoints in
[user_cryptos.py](https://github.com/lasconic/finary_uapi/blob/be147ce47eb0acb3b8f2b1d2152c551953e775bd/finary_uapi/user_cryptos.py)
and
[user_scpis.py](https://github.com/lasconic/finary_uapi/blob/be147ce47eb0acb3b8f2b1d2152c551953e775bd/finary_uapi/user_scpis.py).
It returns JSON without defining amount denominations or converting valuations.
The older, unofficial
[UserCrypto schema](https://github.com/lasconic/openapi-finary/blob/bb0d8796d2f40a49abc066e3215813c90c192d52/src/schemas/UserCrypto.yaml)
and
[UserSCPI schema](https://github.com/lasconic/openapi-finary/blob/bb0d8796d2f40a49abc066e3215813c90c192d52/src/schemas/UserSCPI.yaml)
provide structural leads, but do not establish amount/currency relationships.
Neither those schemas nor synthetic numeric fixtures alone justify EUR labels.

Stronger evidence comes from Finary's own publicly served application source.
The scripts below were retrieved without authentication and inspected as text;
no application JavaScript was executed. They belong to the
[inspected build manifest](https://app.finary.com/v2/_next/static/build-TfctsWXpff2fKS/_buildManifest.js).

| Primary source | Verified behavior |
| --- | --- |
| [Crypto page mapper](https://app.finary.com/v2/_next/static/chunks/05-cnl_ban.gz.js) | Maps holding `current_value` to native balance, pairs it with `buying_price_currency`, and preserves quantity and `current_price` separately. Display balance/price use distinct fields. |
| [Crypto table renderer](https://app.finary.com/v2/_next/static/chunks/12_u9.o5nawms.js) | Identifies `staked` rows with a staking label. Native unit price uses the mapped row currency; staking does not introduce another valuation or rate calculation. |
| [Holding selectors](https://app.finary.com/v2/_next/static/chunks/0orwzfp3054uz.js) | Selects `user_crypto` and `user_scpi` entries from `account.holdings`. |
| [Holding detail mapper](https://app.finary.com/v2/_next/static/chunks/05i-j7qwc6ejd.js) | Maps `current_value` directly to value and `buying_value` separately to cost basis. The native amount cells use `valueCurrencyCode`; display amounts remain separate. With no buying-price, root or fiat currency, the native code comes from `valuable.currency`. No quantity or ownership multiplication is applied to the total. |
| [SCPI purchase form](https://app.finary.com/v2/_next/static/chunks/0ec7x89t-u4v3.js) | Enumerates full ownership, bare ownership and usufruct in the same form. Uses `scpi.currency.code` for purchase-price denomination and shares for the purchase calculation. |

The public detail renderer also has account/default fallbacks. The bridge does
**not** adopt them. In particular, the crypto field's purchase-oriented name is
not sufficient evidence by itself: the current crypto mapper explicitly assigns
that code to the native market balance and price as well.

The initial public-only investigation could not establish that these newer
`account.holdings` objects matched the dedicated collection responses. The
operator subsequently authorized a narrow, read-only structural probe using an
existing renewable session. It compared the two dedicated collections with
only their associated holding-account detail responses. No settings, portfolio
holdings, workbook, deployment or workflow were changed. Password sign-in was
disabled for the probe. Output was restricted to field types, currency codes,
variant counts and equality-check results; identifiers, names, amounts,
quantities, credentials and raw payloads were neither printed nor saved.

For the observed `hodled` and `full_ownership` formats, each dedicated record
matched exactly one same-category account holding by holding ID. The account
association, product ID, native total, cost, quantities and applicable unit
prices agreed across the two surfaces. Crypto `buying_price_currency` agreed;
SCPI `scpi.currency` and `valuable.currency` agreed. Thus the primary-source
native amount renderers apply to these dedicated response structures. This is
structural/semantic verification, not a certification of actual prices,
account reconciliation, complete upstream coverage or a user's exposure caps.

The ownership extension is supported by a further control-flow trace of these
same primary sources, not by new live observations:

- The selectors filter on `user_crypto` / `user_scpi`, without excluding staking
  or SCPI property types. The crypto mapper copies `owning_type` alongside the
  same native amount/currency pair. The table renderer explicitly handles
  `staked` as a label on that mapped row; no separate market denomination or
  staking multiplier intervenes.
- The holding detail mapper copies `property_type` to `scpiPropertyType` while
  assigning `current_value`, `buying_value` and `valueCurrencyCode` through the
  same path. Its SCPI metrics explicitly branch for `bare_ownership` and
  `usufruct` to show expiry information, not to replace the holding valuation or
  its currency. The purchase form enumerates all three types and keeps the same
  purchase-currency source for each.
- Together with the already verified dedicated/current-holding representation,
  the source-based inference is that the same amount-specific currency rules
  apply to the three additional states when the existing product/currency checks
  pass. This is a mapping conclusion from source, not a new live validation.
  The earlier live probe observed only held crypto and full SCPI ownership. No
  staked, bare-ownership or usufruct private records were inspected for this
  extension, and no new account access was needed. Synthetic variant fixtures
  represent the source-supported structure, not captured private holdings.

Public scripts can disappear between builds. SHA-256 hashes identify the
inspected source without checking third-party bundles into this repository:

| Script | SHA-256 |
| --- | --- |
| `05-cnl_ban.gz.js` | `c0496330eeb7fab35271b1527c25da146b5383fb0c1f1b3f989412ff45e4cd03` |
| `0orwzfp3054uz.js` | `375c75190d94a032a409bdc388b67c4d6564684bda7007addd71b1442727761b` |
| `05i-j7qwc6ejd.js` | `2479fa934d97aadb78044da43f0c2ab0219d2e2dbee3b813bd8ef170f89f57e1` |
| `0ec7x89t-u4v3.js` | `afb928492924b8e3d8ac86d69a9e5ca9e96e958d7dacce206c420bafb5ce1f17` |
| `12_u9.o5nawms.js` | `6dc117c95d6c065f2d7f7913c4050f4f25d156999bca08f7fe449f3d6abb5bda` |

## Implemented mapping rules

| Format | Market-value evidence | Independent cost evidence |
| --- | --- | --- |
| `user_crypto`, `hodled` or `staked` | `current_value` is the native total; `current_price` is the native unit price. The verified mapper pairs both with `buying_price_currency.code`. Require matching `crypto.id` and `valuable.id`. `crypto.code` identifies the token, not its quote currency. | `buying_value` is the supplied total cost in `buying_price_currency`. The existing cost rule remains available even when market evidence is missing or the format is unsupported. |
| `user_scpi`, `full_ownership`, `bare_ownership` or `usufruct` | `current_value` is the supplied native position total. Require matching `scpi.id` and `valuable.id`, and agreeing populated `scpi.currency.code` and `valuable.currency.code`. | `buying_value` is the supplied total cost in `scpi.currency`. Missing valuable evidence can prevent market coverage while retaining independently known cost. |

SCPI quantity is informational: use `quantity`, with the existing `shares`
fallback when quantity is missing. In the observed full-ownership format the
fields agreed, and total equaled shares times product current price. The holding
had no top-level `current_price`; normalized `unit_price` therefore remains null.
Do not replace it with the nested product price or recompute a supplied total.
[Finary's SCPI explanation](https://help.finary.com/fr/articles/6521924-moins-value-affichee-pour-ma-scpi)
describes withdrawal-price valuation and time-dependent usufruct amortization.
For bare ownership and usufruct, the authoritative supplied total can differ
from shares times the full-ownership product price. In particular, Finary can
supply a zero total at usufruct expiry while shares and purchase cost remain
nonzero. Preserve that zero; do not recompute amortization, apply a discount,
multiply an ownership share or replace it with the product withdrawal value.
Dates, remaining months and the dismemberment period are not conversion inputs
or new prerequisites for reading an already supplied, denominated total.

For staked crypto, retain the dedicated holding's total and unit price just as
supplied. Do not add an estimated staking yield or future rewards. Held and
staked positions can share a token/product ID while retaining distinct holding
IDs; preserve both canonical positions without merging by ticker or product.
Other ownership codes and legacy or missing type markers remain unsupported.
The stable API class remains CRYPTO or SCPI and does not expose the ownership
mode: a policy that distinguishes those modes still needs separate membership
and classification evidence.

The adapter returns only market/cost currency evidence to the pure normalizer.
It adds no retrieval, uses no account balance as a holding value, and exposes no
raw evidence fields in the stable API. Matching product IDs validate the two
product representations; the position ID and `holdings_account_id` continue to
supply the existing position/account identities. Dedicated collections remain
the canonical position source; account holdings were used only for investigation.

Missing usable evidence leaves market currency, EUR amount and FX unknown.
Supplied malformed currency objects/codes or product identifiers fail with a
sanitized adapter error. Contradictory product IDs or populated native currency
candidates (`buying_price_currency`, root `currency`, `fiat`,
`valuable.currency`, and the applicable category source) also fail the snapshot.
Alternate paths are checked for conflicts, never used as positive fallbacks.
The token identifier and every `display_*` field are excluded from that set.
Unsupported variants supply no new evidence; their existing normalization and
strict numeric validation still apply.

Only proven EUR produces `currency=EUR`, `fx_to_eur=1`, and
`market_value_eur=market_value_native=current_value`. This is identity, not a
foreign-exchange conversion. Other proven native codes remain in `currency`,
with their original total in `market_value_native` and EUR/FX unknown. No source
currency-to-EUR rate endpoint, direction, observation-time or freshness contract
was verified, so **no FX conversion path is implemented**. Missing, stale,
invalid, reciprocal or conflicting uncontracted rate/display inputs cannot
supply EUR evidence; no already converted display amount is used or converted
again. Snapshot generation time is not an upstream price observation time.

Cost completeness never gates market completeness. Unknown optional cost stays
null, proven zero stays numeric zero, and consumed monetary fields still reject
booleans, numeric strings, non-finite numbers and float overflow. The exported
n8n validator also rejects aggregate arithmetic overflow before any writes.

## Regression evidence and adoption

[The synthetic fixture](../finary-bridge/tests/fixtures/finary/verified-valuations.json)
contains minimal fields from the verified current structures, with invented
identifiers/names/amounts and deliberately different display values. It is not a
captured private payload. The additional
[ownership fixture](../finary-bridge/tests/fixtures/finary/verified-ownership-valuations.json)
contains staked crypto, bare ownership and usufruct with the enum/amount fields
supported by the primary-source branches above. Tests derive missing, conflicting
and unrecognized variants as negative or adversarial cases. The original legacy
fixtures and their null expectations are retained.

Before correction, both positive normalization regressions fail with unknown
currency/EUR. Afterwards, the synthetic crypto total is EUR 60 and SCPI total
EUR 105; quantities are two, so multiplying totals again would fail the tests.
Their independently known costs are EUR 50 and EUR 100. The six retrieved
synthetic positions total EUR 610, while account-derived gross assets remain
EUR 150. These intentionally different scopes must not be reconciled by adding
positions to balances.

The three added ownership regressions also failed before their mapping was
enabled and pass with synthetic totals EUR 45 (staked), EUR 75 (bare ownership)
and EUR 12 (usufruct), preserving costs EUR 30 / 70 / 40. The two SCPI totals
intentionally differ from shares times the product price. The ownership dataset
has seven retrieved positions, a known-position denominator of EUR 577, SCPI
EUR 87 and crypto EUR 45, with unchanged gross assets EUR 150. A separate expiry
case preserves usufruct zero and demonstrates distinct held/staked positions
for the same token. These amounts illustrate supplied totals, not a new formula
for pricing rights or projecting staking returns.

Tests pass adapter-owned fixture data through the real adapter, snapshot
service/model, exported JavaScript, Sheets serialization and the installed n8n
Sheets connector with a network-disabled in-memory transport. They check
null → known → null cell clearing for all five supported ownership states,
retained cost, current/history identity,
same-day upserts, prior-day history, inactivation and manual-sheet preservation.
The combined-category worked example in the
[consumer knowledge](finary-portfolio-data-knowledge.md#combined-exposure-checks)
has executable coverage, including missing values, membership/classification
uncertainty and a zero denominator.

No API/workbook schema migration, n8n logic change, application version bump or
historical valuation backfill is required. Operator adoption requires installing
the reviewed bridge revision through the normal operational process and then
allowing a fresh validated sync. Refresh the ChatGPT Project's uploaded
`finary-portfolio-data-knowledge.md` source so the combined-exposure guidance is
available to its consumer. Deployment and production workbook writes are
separate operator actions, not part of this change. Keep earlier history as
observed; new currency evidence does not prove historical denominations/prices.

After adoption, inspect the normalized current state and retained warnings.
`PARTIAL_POSITION_EUR_COVERAGE` disappears only when every retrieved current
position has a known EUR amount; independent liability warnings remain. Further
variants require separately authorized structural verification or authoritative
source evidence. Complete valuation of retrieved positions does not establish
coverage of undiscovered upstream holdings or reconciliation to gross assets.
