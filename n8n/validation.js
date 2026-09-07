// Shared source embedded by scripts/build-workflow-validation.py. No runtime imports.
const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const record = (value) => value !== null && Object.prototype.toString.call(value) === '[object Object]';
const finiteNumber = (value) => typeof value === 'number' && Number.isFinite(value);
// Paths below come only from checked-in contracts, never from input keys or values.
const invalidContract = (path) => { throw new Error(`CONTRACT_VALIDATION_FAILED:${path}`); };
const calendarDate = (value) => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
};
const canonicalInstant = (value) => {
  if (typeof value !== 'string') return null;
  // Pydantic's JSON datetime spellings, normalized for JS/Sheets ISO consumers.
  const match = /^(\d{4}-\d{2}-\d{2})[Tt ]([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d)([.,]\d+)?)?([Zz]|[+-](?:[01]\d|2[0-3]):?[0-5]\d)$/.exec(value);
  if (!match || !calendarDate(match[1])) return null;
  const offset = /^[Zz]$/.test(match[6]) ? 'Z' : match[6].replace(/^([+-]\d{2})(\d{2})$/, '$1:$2');
  const normalized = `${match[1]}T${match[2]}:${match[3]}:${match[4] || '00'}${(match[5] || '').replace(',', '.')}${offset}`;
  return Number.isFinite(Date.parse(normalized)) ? normalized : null;
};
const apiValue = (value, rule, path) => {
  if (rule.$ref) return apiValue(value, apiContract.$defs[rule.$ref.split('/').pop()], path);
  if (rule.anyOf) {
    for (const option of rule.anyOf) {
      try { return apiValue(value, option, path); } catch { /* Try the next declared type. */ }
    }
    return invalidContract(path);
  }
  if (rule.type === 'object') {
    if (!record(value)) return invalidContract(path);
    const properties = rule.properties || {};
    if (rule.additionalProperties === false && Object.keys(value).some((key) => !owns(properties, key))) return invalidContract(path);
    const output = {};
    for (const [key, child] of Object.entries(properties)) {
      if (!owns(value, key)) {
        if ((rule.required || []).includes(key) || !owns(child, 'default')) return invalidContract(`${path}.${key}`);
        output[key] = apiValue(child.default, child, `${path}.${key}`);
      } else output[key] = apiValue(value[key], child, `${path}.${key}`);
    }
    if (record(rule.additionalProperties)) {
      for (const child of Object.values(value)) apiValue(child, rule.additionalProperties, path);
      // Metadata accepts model-defined scalars, but the downstream allowlist is empty.
    }
    return output;
  }
  if (rule.type === 'array') {
    if (!Array.isArray(value)) return invalidContract(path);
    return Array.from(value, (child) => apiValue(child, rule.items, `${path}[]`));
  }
  const validType = rule.type === 'null' ? value === null
    : rule.type === 'number' ? finiteNumber(value)
    : rule.type === 'integer' ? finiteNumber(value) && Number.isInteger(value)
    : ['string', 'boolean'].includes(rule.type) && typeof value === rule.type;
  if (!validType || (owns(rule, 'const') && value !== rule.const) ||
      (rule.enum && !rule.enum.includes(value)) ||
      (owns(rule, 'minimum') && value < rule.minimum) ||
      (owns(rule, 'minLength') && Array.from(value).length < rule.minLength) ||
      (rule.pattern && (new RegExp(rule.pattern, 'u')).exec(value)?.[0] !== value)) return invalidContract(path);
  if (rule.format === 'date-time') return canonicalInstant(value) ?? invalidContract(path);
  return value;
};
const enumBindings = { asset_class: 'asset_class', status: 'sync_status', liability_coverage: 'liability_coverage' };
const nonemptyString = (value) => typeof value === 'string' && value.length > 0;
const canonicalAccountKey = (value) => nonemptyString(value) && value.startsWith('finary:account:') && value.length > 'finary:account:'.length;
const canonicalPositionKey = (row) => canonicalAccountKey(row.account_key) &&
  nonemptyString(row.source_asset_id) && row.source_asset_id.indexOf(':') > 0 && row.source_asset_id.indexOf(':') < row.source_asset_id.length - 1 &&
  row.position_key === `finary:${row.account_key.slice('finary:account:'.length)}:asset:${row.source_asset_id}`;
const parisBusinessDate = (timestamp) => {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(timestamp)).map((part) => [part.type, part.value]));
  return `${parts.year.padStart(4, '0')}-${parts.month}-${parts.day}`;
};
const validateRow = (schema, sheetName, row) => {
  const columns = schema.sheets[sheetName].columns;
  const expected = columns.map((column) => column.name);
  if (!record(row)) return invalidContract(sheetName);
  const actual = Object.keys(row);
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new Error(`TARGET_SCHEMA_MISMATCH:${sheetName}`);
  for (const column of columns) {
    const value = row[column.name];
    const path = `${sheetName}.${column.name}`;
    if (value === undefined) return invalidContract(path);
    if (value === null || value === '') {
      // Empty optional strings are also intentional blank cells; never numeric zero.
      if (column.nullable) continue;
      return invalidContract(path);
    }
    const valid = column.type === 'STRING' ? typeof value === 'string'
      : column.type === 'NUMBER' ? finiteNumber(value)
      : column.type === 'BOOLEAN' ? typeof value === 'boolean'
      : column.type === 'DATE' ? calendarDate(value)
      : column.type === 'DATETIME' ? canonicalInstant(value) !== null
      : column.type === 'ENUM' ? schema.enums[enumBindings[column.name]]?.includes(value) === true : false;
    if (!valid) return invalidContract(path);
    // Reuse source-field constraints (length, literal, currency, lower bound).
    const source = /(?:^|joined )(Account|Position|Liability|PortfolioSnapshot)\.(\w+)/.exec(column.source);
    if (source) {
      const model = source[1] === 'PortfolioSnapshot' ? apiContract : apiContract.$defs[source[1]];
      apiValue(value, model.properties[source[2]], path);
    }
  }
  if (sheetName === 'accounts_current' && row.account_key !== `finary:account:${row.source_account_id}`) return invalidContract(`${sheetName}.account_key`);
  if (['positions_current', 'positions_history'].includes(sheetName) && !canonicalPositionKey(row)) return invalidContract(`${sheetName}.position_key`);
  if (sheetName === 'liabilities_current' && row.liability_key !== `finary:liability:${row.source_liability_id}`) return invalidContract(`${sheetName}.liability_key`);
  if (sheetName === 'positions_history' && row.history_key !== `${row.snapshot_date}:${row.position_key}`) return invalidContract(`${sheetName}.history_key`);
  if (['portfolio_daily', 'sync_runs'].includes(sheetName)) {
    for (const key of ['gross_assets_eur', 'liabilities_eur', 'duration_ms', 'warning_count', 'accounts_count', 'positions_count', 'liabilities_count']) {
      if (!owns(row, key) || row[key] === null || row[key] === '') continue;
      if (row[key] < 0 || ((key.endsWith('_count') || key === 'duration_ms') && !Number.isInteger(row[key]))) return invalidContract(`${sheetName}.${key}`);
    }
    if (sheetName === 'portfolio_daily' || row.status !== 'FAILED') {
      if (!finiteNumber(row.gross_assets_eur)) return invalidContract(`${sheetName}.gross_assets_eur`);
      if (row.liability_coverage === 'COMPLETE') {
        if (!finiteNumber(row.liabilities_eur) || !finiteNumber(row.net_worth_eur) ||
            Math.abs(row.gross_assets_eur - row.liabilities_eur - row.net_worth_eur) > 1e-8) return invalidContract(`${sheetName}.liabilities_eur`);
      } else if (!['PARTIAL', 'UNAVAILABLE'].includes(row.liability_coverage) || row.liabilities_eur !== null || row.net_worth_eur !== null) return invalidContract(`${sheetName}.liability_coverage`);
      if (sheetName === 'sync_runs' && ['accounts_count', 'positions_count', 'liabilities_count'].some((key) => !finiteNumber(row[key]))) return invalidContract(`${sheetName}.status`);
    }
  }
};
const validateBatch = (schema, sheetName, batch) => {
  if (!Array.isArray(batch)) return invalidContract(sheetName);
  const keys = new Set();
  for (const row of batch) {
    validateRow(schema, sheetName, row);
    const key = row[schema.sheets[sheetName].unique_key];
    if (!nonemptyString(key) || keys.has(key)) throw new Error(`DUPLICATE_OR_MISSING_TARGET_KEY:${sheetName}`);
    keys.add(key);
  }
};
// Only Sheets reads use these encodings. API values never pass through this decoder.
const decodeRetainedRow = (schema, sheetName, old) => {
  if (!record(old)) return invalidContract(sheetName);
  const columns = schema.sheets[sheetName].columns;
  const expected = new Set(columns.map((column) => column.name));
  if (Object.keys(old).some((key) => key !== 'row_number' && !expected.has(key))) return invalidContract(sheetName);
  const row = {};
  for (const column of columns) {
    let value = old[column.name];
    if (!owns(old, column.name) || value === null || value === '') {
      if (!column.nullable) return invalidContract(`${sheetName}.${column.name}`);
      value = null; // Sheets may omit a nullable empty cell, but not an explicit undefined.
    } else if (column.type === 'BOOLEAN' && ['TRUE', 'FALSE'].includes(value)) value = value === 'TRUE';
    else if (column.type === 'NUMBER' && typeof value === 'string' && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim())) value = Number(value);
    row[column.name] = value;
  }
  validateRow(schema, sheetName, row);
  return row;
};
const validateRunContext = (run, executionId) => {
  if (!record(run) || !nonemptyString(executionId) || run.run_id !== `n8n-execution:${executionId}`) throw new Error('STALE_EXECUTION_IDENTITY');
  const start = canonicalInstant(run.started_at);
  if (!start || !finiteNumber(run.started_epoch_ms) || !Number.isInteger(run.started_epoch_ms) ||
      !Number.isFinite(new Date(run.started_epoch_ms).getTime()) ||
      Math.abs(Date.parse(start) - run.started_epoch_ms) >= 1000) throw new Error('INVALID_RUN_TIMING');
};
const validatePrepared = (schema, batches, snapshot, run) => {
  const bindings = { accounts_current: 'account_rows', positions_current: 'position_rows', liabilities_current: 'liability_rows', positions_history: 'history_rows', portfolio_daily: 'daily_rows', sync_runs: 'sync_run_rows' };
  for (const [sheetName, field] of Object.entries(bindings)) validateBatch(schema, sheetName, batches[field]);
  if (batches.daily_rows.length !== 1 || batches.sync_run_rows.length !== 1) return invalidContract('prepared');
  const daily = batches.daily_rows[0];
  const terminal = batches.sync_run_rows[0];
  if (!Array.isArray(batches.warnings) || batches.warnings.some((value) => typeof value !== 'string') ||
      terminal.warning_count !== batches.warnings.length ||
      terminal.status !== (batches.warnings.length ? 'SUCCESS_WITH_WARNINGS' : 'SUCCESS') ||
      terminal.error_message !== (batches.warnings.length ? batches.warnings.join(',') : null)) return invalidContract('sync_runs.warning_count');
  const businessDate = parisBusinessDate(snapshot.generated_at);
  if (daily.snapshot_date !== businessDate || daily.generated_at !== snapshot.generated_at || daily.run_id !== run.run_id ||
      terminal.run_id !== run.run_id || terminal.started_at !== run.started_at || terminal.schema_version !== snapshot.schema_version ||
      !['SUCCESS', 'SUCCESS_WITH_WARNINGS'].includes(terminal.status) || terminal.error_code !== null) return invalidContract('prepared.run');
  for (const key of ['gross_assets_eur', 'liabilities_eur', 'net_worth_eur']) {
    if (daily[key] !== snapshot[key] || terminal[key] !== snapshot[key]) return invalidContract(`portfolio_daily.${key}`);
  }
  const coverage = snapshot.coverage.liabilities;
  if (daily.liability_coverage !== coverage || terminal.liability_coverage !== coverage) return invalidContract('prepared.liability_coverage');
  const activeAccounts = new Set(batches.account_rows.filter((row) => row.is_active).map((row) => row.account_key));
  const activePositions = new Map(batches.position_rows.filter((row) => row.is_active).map((row) => [row.position_key, row]));
  for (const [collection, field, key] of [['accounts', 'account_rows', 'account_key'], ['positions', 'position_rows', 'position_key'], ['liabilities', 'liability_rows', 'liability_key']]) {
    if (terminal[`${collection}_count`] !== snapshot[collection].length) return invalidContract(`sync_runs.${collection}_count`);
    if (collection === 'liabilities' && coverage !== 'COMPLETE') {
      if (batches[field].length) return invalidContract('liabilities_current');
      continue;
    }
    const expected = new Set(snapshot[collection].map((row) => row[key]));
    const active = batches[field].filter((row) => row.is_active);
    if (active.length !== expected.size || active.some((row) => !expected.has(row[key]) || row.last_seen_run_id !== run.run_id || row.last_seen_at !== snapshot.generated_at)) return invalidContract(field);
  }
  if ([...activePositions.values()].some((row) => !activeAccounts.has(row.account_key))) return invalidContract('positions_current.account_key');
  if (batches.history_rows.length !== activePositions.size) return invalidContract('positions_history');
  for (const row of batches.history_rows) {
    const position = activePositions.get(row.position_key);
    if (!position || row.run_id !== run.run_id || row.snapshot_date !== businessDate || row.generated_at !== snapshot.generated_at ||
        Object.keys(row).some((key) => owns(position, key) && row[key] !== position[key])) return invalidContract('positions_history');
  }
  if (coverage === 'COMPLETE') {
    const total = batches.liability_rows.filter((row) => row.is_active).reduce((sum, row) => sum + row.outstanding_eur, 0);
    if (!finiteNumber(total) || Math.abs(total - snapshot.liabilities_eur) > 1e-8) return invalidContract('liabilities_current.outstanding_eur');
  }
};
