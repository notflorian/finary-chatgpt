const context = $('Validate Snapshot').first().json;
const { schema, run } = context;
if (context.can_write !== true) throw new Error('SNAPSHOT_VALIDATION_FAILED');
validateRunContext(run, $execution.id);
// Defaults and validation precede overrides even when this node is run with saved data.
const snapshot = apiValue(context.snapshot, apiContract, 'snapshot');
const rows = (nodeName) => $(nodeName).all().map((item) => item.json).filter((row) => !(record(row) && Object.keys(row).length === 0));
const expectedHeaders = (sheetName) => schema.sheets[sheetName].columns.map((column) => column.name);
const actualHeaders = (nodeName) => Object.keys($(nodeName).first().json).filter((name) => name !== 'row_number');
const preflights = { asset_overrides: 'Preflight Overrides Header', accounts_current: 'Preflight Accounts Header', positions_current: 'Preflight Positions Header', liabilities_current: 'Preflight Liabilities Header', positions_history: 'Preflight History Header', portfolio_daily: 'Preflight Daily Header', sync_runs: 'Preflight Sync Header' };
for (const [sheetName, nodeName] of Object.entries(preflights)) {
  const expected = expectedHeaders(sheetName);
  const actual = actualHeaders(nodeName);
  if (actual.length !== expected.length || actual.some((value, index) => value !== expected[index])) throw new Error(`SHEETS_HEADER_MISMATCH:${sheetName}`);
}
const existingAccounts = rows('Read Current Accounts');
const existingPositions = rows('Read Current Positions');
const existingLiabilities = rows('Read Current Liabilities');
const previousDaily = rows('Read Portfolio Daily');
const terminalRows = rows('Read Sync Runs');
matchingTerminal(terminalRows, run);
const overrides = rows('Read Asset Overrides').filter((row) => row.enabled === true || String(row.enabled).toUpperCase() === 'TRUE');
const assetClasses = new Set(schema.enums.asset_class);
const normalizeExact = (value) => value == null ? null : String(value).normalize('NFKC').trim();
const normalizeCode = (value) => { const normalized = normalizeExact(value); return normalized ? normalized.toUpperCase() : null; };
const normalizeName = (value) => { const normalized = normalizeExact(value); return normalized ? normalized.replace(/\s+/g, ' ').toLocaleLowerCase('en-US') : null; };
const fields = [
  ['source_asset_id', (value) => normalizeExact(value)],
  ['isin', (value) => normalizeCode(value)],
  ['ticker', (value) => normalizeCode(value)],
  ['name_match', (value) => normalizeName(value)],
];
const applyOverride = (position) => {
  for (const [field, normalize] of fields) {
    const positionField = field === 'name_match' ? position.name : position[field];
    const wanted = normalize(positionField);
    if (!wanted) continue;
    const matches = overrides.filter((override) => normalize(override[field]) === wanted);
    if (matches.length > 1) throw new Error(`AMBIGUOUS_ASSET_OVERRIDE:${field}`);
    if (matches.length === 1) {
      const override = matches[0];
      const customClass = normalizeExact(override.custom_asset_class);
      if (customClass && !assetClasses.has(customClass)) throw new Error(`INVALID_ASSET_OVERRIDE_CLASS:asset_overrides`);
      return { ...position, asset_class: customClass || position.asset_class, asset_subclass: normalizeExact(override.custom_asset_subclass) || position.asset_subclass, region: normalizeExact(override.custom_region) || position.region };
    }
  }
  return { ...position };
};
const finalPositions = snapshot.positions.map(applyOverride);
const accountByKey = new Map(snapshot.accounts.map((account) => [account.account_key, account]));
const knownPositionTotal = finalPositions.reduce((sum, position) => sum + (position.market_value_eur ?? 0), 0);
if (!finiteNumber(knownPositionTotal)) invalidContract('positions_current.market_value_eur');
const warnings = [];
const liabilityCoverage = snapshot.coverage.liabilities;
if (liabilityCoverage !== 'COMPLETE') warnings.push(`LIABILITY_COVERAGE_${liabilityCoverage}`);
const warningThresholds = { net_worth_change: 0.20, account_count_change: 0.30, position_count_change: 0.30 };
const isActive = (row) => row.is_active === true || String(row.is_active).toUpperCase() === 'TRUE';
const previousAccountCount = existingAccounts.filter(isActive).length;
const previousPositionCount = existingPositions.filter(isActive).length;
const relativeCountChange = (current, previous) => previous === 0 ? null : Math.abs(current - previous) / previous;
if (relativeCountChange(snapshot.accounts.length, previousAccountCount) > warningThresholds.account_count_change) warnings.push('ACCOUNT_COUNT_CHANGE_OVER_30_PERCENT');
if (relativeCountChange(snapshot.positions.length, previousPositionCount) > warningThresholds.position_count_change) warnings.push('POSITION_COUNT_CHANGE_OVER_30_PERCENT');
if (finalPositions.some((position) => position.market_value_eur === null)) warnings.push('PARTIAL_POSITION_EUR_COVERAGE');
const parisDate = parisBusinessDate;
const snapshotDate = parisDate(snapshot.generated_at);
const appendInactive = (sheetName, existing, currentKeys, targetRows) => {
  const key = schema.sheets[sheetName].unique_key;
  const seen = new Set();
  for (const old of existing) {
    if (!record(old) || !nonemptyString(old[key]) || seen.has(old[key])) throw new Error(`DUPLICATE_OR_MISSING_TARGET_KEY:${sheetName}`);
    seen.add(old[key]);
    if (!currentKeys.has(old[key])) targetRows.push({ ...decodeRetainedRow(schema, sheetName, old), is_active: false });
  }
};
const currentAccountKeys = new Set(snapshot.accounts.map((row) => row.account_key));
const accountRows = snapshot.accounts.map((account) => ({ account_key: account.account_key, source: account.source, source_account_id: account.source_account_id, name: account.name, institution: account.institution, account_type: account.account_type, owner: account.owner, currency: account.currency, market_value_eur: account.market_value_eur, last_seen_at: snapshot.generated_at, last_seen_run_id: run.run_id, is_active: true }));
appendInactive('accounts_current', existingAccounts, currentAccountKeys, accountRows);
const currentPositionKeys = new Set(finalPositions.map((row) => row.position_key));
const positionRows = finalPositions.map((position) => { const account = accountByKey.get(position.account_key); return { position_key: position.position_key, source: position.source, source_asset_id: position.source_asset_id, account_key: position.account_key, account_name: account.name, account_type: account.account_type, institution: account.institution, name: position.name, ticker: position.ticker, isin: position.isin, asset_class: position.asset_class, asset_subclass: position.asset_subclass, region: position.region, quantity: position.quantity, unit_price: position.unit_price, currency: position.currency, fx_to_eur: position.fx_to_eur, market_value_native: position.market_value_native, market_value_eur: position.market_value_eur, cost_basis_eur: position.cost_basis_eur, unrealized_pnl_eur: position.unrealized_pnl_eur, unrealized_pnl_pct: position.unrealized_pnl_pct, weight_portfolio: position.market_value_eur === null || knownPositionTotal === 0 ? null : position.market_value_eur / knownPositionTotal, last_seen_at: snapshot.generated_at, last_seen_run_id: run.run_id, is_active: true }; });
appendInactive('positions_current', existingPositions, currentPositionKeys, positionRows);
const liabilityRows = [];
if (liabilityCoverage === 'COMPLETE') {
  const currentLiabilityKeys = new Set(snapshot.liabilities.map((row) => row.liability_key));
  liabilityRows.push(...snapshot.liabilities.map((liability) => ({ liability_key: liability.liability_key, source: liability.source, source_liability_id: liability.source_liability_id, name: liability.name, liability_type: liability.liability_type, institution: liability.institution, outstanding_eur: liability.outstanding_eur, interest_rate: liability.interest_rate, monthly_payment_eur: liability.monthly_payment_eur, end_date: liability.end_date, last_seen_at: snapshot.generated_at, last_seen_run_id: run.run_id, is_active: true })));
  appendInactive('liabilities_current', existingLiabilities, currentLiabilityKeys, liabilityRows);
}
const historyRows = positionRows.filter((row) => row.is_active === true).map((position) => ({ history_key: `${snapshotDate}:${position.position_key}`, snapshot_date: snapshotDate, generated_at: snapshot.generated_at, position_key: position.position_key, account_key: position.account_key, source_asset_id: position.source_asset_id, name: position.name, ticker: position.ticker, isin: position.isin, asset_class: position.asset_class, asset_subclass: position.asset_subclass, quantity: position.quantity, unit_price: position.unit_price, currency: position.currency, fx_to_eur: position.fx_to_eur, market_value_eur: position.market_value_eur, cost_basis_eur: position.cost_basis_eur, run_id: run.run_id }));
const classNames = ['EQUITY', 'BOND', 'CASH', 'REAL_ESTATE', 'SCPI', 'PRIVATE_EQUITY', 'CRYPTO', 'COMMODITY', 'LIFE_INSURANCE_FUND', 'OTHER'];
const classSlugs = { EQUITY: 'equity', BOND: 'bond', CASH: 'cash', REAL_ESTATE: 'real_estate', SCPI: 'scpi', PRIVATE_EQUITY: 'private_equity', CRYPTO: 'crypto', COMMODITY: 'commodity', LIFE_INSURANCE_FUND: 'life_insurance_fund', OTHER: 'other' };
const daily = { snapshot_date: snapshotDate, generated_at: snapshot.generated_at, gross_assets_eur: snapshot.gross_assets_eur, liability_coverage: liabilityCoverage, liabilities_eur: snapshot.liabilities_eur, net_worth_eur: snapshot.net_worth_eur, financial_assets_eur: null };
for (const assetClass of classNames) {
  const positions = finalPositions.filter((row) => row.asset_class === assetClass);
  const known = positions.filter((row) => row.market_value_eur !== null);
  const total = known.reduce((sum, row) => sum + row.market_value_eur, 0);
  daily[`${classSlugs[assetClass]}_eur`] = positions.some((row) => row.market_value_eur === null) ? null : total;
  daily[`${classSlugs[assetClass]}_pct`] = knownPositionTotal === 0 ? null : total / knownPositionTotal;
}
const accountGroups = { pea_eur: new Set(['PEA']), cto_eur: new Set(['CTO']), life_insurance_eur: new Set(['ASSURANCE VIE', 'LIFE INSURANCE']), cash_accounts_eur: new Set(['CASH', 'COMPTE COURANT', 'CURRENT ACCOUNT']) };
for (const [column, types] of Object.entries(accountGroups)) {
  const matching = snapshot.accounts.filter((account) => types.has(String(account.account_type).trim().toUpperCase()));
  daily[column] = matching.length === 0 || matching.some((account) => account.market_value_eur === null) ? null : matching.reduce((sum, account) => sum + account.market_value_eur, 0);
}
// Validate retained daily aggregates independently of current tables and position history.
// Count physical evidence before status filtering; duplicate records are never deduplicated.
const groupEvidence = (evidence, key) => {
  const groups = new Map();
  for (const row of evidence) {
    const value = row[key];
    if (!groups.has(value)) groups.set(value, []);
    groups.get(value).push(row);
  }
  return groups;
};
const dailyByDate = groupEvidence(previousDaily, 'snapshot_date');
const terminalsByRun = groupEvidence(terminalRows, 'run_id');
const blankCell = (value) => value == null || (typeof value === 'string' && value.trim() === '');
const workbookNumber = (value) => {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const validDate = (value) => {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000')) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};
const workbookInstant = (value) => {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d)(\.\d+)?)?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  if (!match || !validDate(match[1])) return null;
  const epoch = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4] || '00'}${match[6]}`);
  // Preserve fractional precision and equivalent offsets when ordering completion instants.
  return Number.isFinite(epoch) ? { epoch, fraction: (match[5] || '').slice(1).replace(/0+$/, '') } : null;
};
const compareInstants = (a, b) => a.epoch - b.epoch || (a.fraction < b.fraction ? -1 : a.fraction > b.fraction ? 1 : 0);
const baselineCandidates = [];
for (const candidate of previousDaily) {
  if (!validDate(candidate.snapshot_date) || dailyByDate.get(candidate.snapshot_date).length !== 1) continue;
  const id = candidate.run_id;
  if (typeof id !== 'string' || id.trim() === '' || id === run.run_id) continue;
  const evidence = terminalsByRun.get(id);
  if (!evidence || evidence.length !== 1) continue;
  const terminal = evidence[0];
  if (!['SUCCESS', 'SUCCESS_WITH_WARNINGS'].includes(terminal.status)) continue;
  const completed = workbookInstant(terminal.completed_at);
  const generated = workbookInstant(candidate.generated_at);
  if (!completed || !generated || parisDate(generated.epoch) !== candidate.snapshot_date) continue;
  if (candidate.liability_coverage !== 'COMPLETE' || terminal.liability_coverage !== 'COMPLETE') continue;
  // Nullable analytical fields may be blank, but malformed populated numbers invalidate the row.
  if (schema.sheets.portfolio_daily.columns.some((column) => column.type === 'NUMBER' &&
      !(column.nullable && blankCell(candidate[column.name])) && workbookNumber(candidate[column.name]) === null)) continue;
  const shared = ['gross_assets_eur', 'liabilities_eur', 'net_worth_eur'];
  if (shared.some((key) => workbookNumber(candidate[key]) === null || workbookNumber(candidate[key]) !== workbookNumber(terminal[key]))) continue;
  const gross = workbookNumber(candidate.gross_assets_eur);
  const liabilities = workbookNumber(candidate.liabilities_eur);
  const netWorth = workbookNumber(candidate.net_worth_eur);
  if (gross < 0 || liabilities < 0 || Math.abs(gross - liabilities - netWorth) > 1e-8) continue;
  baselineCandidates.push({ netWorth, completed });
}
baselineCandidates.sort((a, b) => compareInstants(b.completed, a.completed));
// A newer success without retained valid daily evidence cannot reconstruct its state.
// Fall back to the latest usable aggregate, but never choose between tied latest candidates.
const previous = baselineCandidates[0];
const tied = previous && baselineCandidates[1] && compareInstants(previous.completed, baselineCandidates[1].completed) === 0;
const previousNetWorth = previous && !tied ? previous.netWorth : null;
const change = snapshot.net_worth_eur === null || previousNetWorth === null || previousNetWorth === 0 ? null : (snapshot.net_worth_eur - previousNetWorth) / Math.abs(previousNetWorth);
if (change !== null && Math.abs(change) > warningThresholds.net_worth_change) warnings.push('NET_WORTH_CHANGE_OVER_20_PERCENT');
const preparedAt = new Date();
const completedAt = preparedAt.toISOString();
const syncRun = { run_id: run.run_id, started_at: run.started_at, completed_at: completedAt, status: warnings.length ? 'SUCCESS_WITH_WARNINGS' : 'SUCCESS', accounts_count: snapshot.accounts.length, positions_count: snapshot.positions.length, liabilities_count: snapshot.liabilities.length, liability_coverage: liabilityCoverage, gross_assets_eur: snapshot.gross_assets_eur, liabilities_eur: snapshot.liabilities_eur, net_worth_eur: snapshot.net_worth_eur, previous_net_worth_eur: previousNetWorth, net_worth_change_pct: change, duration_ms: Math.max(0, preparedAt.getTime() - run.started_epoch_ms), bridge_version: null, schema_version: snapshot.schema_version, warning_count: warnings.length, error_code: null, error_message: warnings.length ? warnings.join(',') : null };
daily.run_id = run.run_id;
const orderedDaily = Object.fromEntries(expectedHeaders('portfolio_daily').map((key) => [key, daily[key]]));
const prepared = { schema, account_rows: accountRows, position_rows: positionRows, liability_rows: liabilityRows, history_rows: historyRows, daily_rows: [orderedDaily], sync_run_rows: [syncRun], warnings };
// All six batches, including history/daily/terminal fields, precede the first portfolio write.
validatePrepared(schema, prepared, snapshot, run);
return [{ json: prepared }];