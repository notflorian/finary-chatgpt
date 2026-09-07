const run = $('Initialize Run').first().json;
validateRunContext(run, $execution.id);
const schemaResponse = $('Fetch Canonical Schema').first().json;
const snapshotResponse = $input.first().json;
const parseBody = (response) => {
  const body = response.data ?? response.body ?? response;
  if (typeof body !== 'string') return body;
  try { return JSON.parse(body); } catch { return null; }
};
const finishFailure = (code, message, retryable = false) => [{ json: { can_write: false, run, schema: parseBody(schemaResponse), failure: { code, message, retryable } } }];
const schema = parseBody(schemaResponse);
if ((schemaResponse.statusCode ?? 200) < 200 || (schemaResponse.statusCode ?? 200) >= 300 || !schema || typeof schema !== 'object') return finishFailure('SHEETS_SCHEMA_UNAVAILABLE', 'Canonical workbook schema is unavailable', true);
const requiredSheets = ['README', 'accounts_current', 'positions_current', 'liabilities_current', 'positions_history', 'portfolio_daily', 'allocation_targets', 'asset_overrides', 'cashflows', 'sync_runs'];
if (schema.schema_version !== '2.1' || schema.timezone !== 'Europe/Paris' || schema.reference_currency !== 'EUR' || !schema.sheets || requiredSheets.some((name) => !schema.sheets[name])) return finishFailure('SHEETS_SCHEMA_INVALID', 'Canonical workbook schema is invalid');
let snapshot = parseBody(snapshotResponse);
const statusCode = snapshotResponse.statusCode ?? 200;
if (statusCode < 200 || statusCode >= 300 || (snapshot && snapshot.error)) {
  const upstreamCode = snapshot?.error?.code;
  const allowed = { BRIDGE_AUTH_FAILED: ['Bridge authentication failed', false], FINARY_AUTH_FAILED: ['Unable to authenticate with Finary', false], FINARY_TIMEOUT: ['Finary request timed out', true], FINARY_MALFORMED_RESPONSE: ['Finary returned a malformed response', false], FINARY_UPSTREAM_ERROR: ['Unable to retrieve data from Finary', true], FINARY_FEATURE_UNAVAILABLE: ['Required Finary data is unavailable', false], SNAPSHOT_VALIDATION_FAILED: ['Unable to build a valid portfolio snapshot', false] };
  const selected = allowed[upstreamCode] ?? ['Bridge snapshot request failed', statusCode >= 500];
  return finishFailure(upstreamCode && allowed[upstreamCode] ? upstreamCode : 'BRIDGE_REQUEST_FAILED', selected[0], selected[1]);
}
try {
  snapshot = apiValue(snapshot, apiContract, 'snapshot');
} catch (error) {
  return finishFailure('SNAPSHOT_VALIDATION_FAILED', error.message);
}
const finite = finiteNumber;
const coverage = snapshot.coverage.liabilities;
const positionCoverage = snapshot.coverage.position_collections;
if (snapshot.accounts.length === 0 || (snapshot.positions.length === 0 && positionCoverage !== 'COMPLETE')) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Snapshot failed the schema 2.0 validation gate');
const unique = (values) => values.length === new Set(values).size;
const accountKeys = snapshot.accounts.map((row) => row.account_key);
const positionKeys = snapshot.positions.map((row) => row.position_key);
const liabilityKeys = snapshot.liabilities.map((row) => row.liability_key);
if (snapshot.accounts.some((row) => row.account_key !== `finary:account:${row.source_account_id}`) || !unique(accountKeys) || !unique(positionKeys) || snapshot.liabilities.some((row) => row.liability_key !== `finary:liability:${row.source_liability_id}`) || !unique(liabilityKeys)) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Snapshot identifiers are invalid or duplicated');
const accountSet = new Set(accountKeys);
if (snapshot.positions.some((row) => !accountSet.has(row.account_key) || !canonicalPositionKey(row))) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Snapshot position references or category-aware keys are invalid');
const liabilityTotal = snapshot.liabilities.reduce((sum, row) => sum + row.outstanding_eur, 0);
if (coverage === 'COMPLETE') {
  if (!finite(liabilityTotal) || !finite(snapshot.liabilities_eur) || snapshot.liabilities_eur < 0 || !finite(snapshot.net_worth_eur) || Math.abs(liabilityTotal - snapshot.liabilities_eur) > 1e-8 || Math.abs(snapshot.gross_assets_eur - snapshot.liabilities_eur - snapshot.net_worth_eur) > 1e-8) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Complete liability totals are inconsistent');
} else {
  if (snapshot.liabilities_eur !== null || snapshot.net_worth_eur !== null) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Incomplete liability coverage requires null totals');
  if (coverage === 'UNAVAILABLE' && snapshot.liabilities.length !== 0) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Unavailable liability coverage cannot claim liabilities');
}
const knownAccountTotal = snapshot.accounts.reduce((sum, row) => sum + (row.market_value_eur ?? 0), 0);
if (!finite(knownAccountTotal) || knownAccountTotal + 1e-8 < snapshot.gross_assets_eur) return finishFailure('SNAPSHOT_VALIDATION_FAILED', 'Authoritative gross assets exceed known account balances');
return [{ json: { can_write: true, run, schema, snapshot } }];