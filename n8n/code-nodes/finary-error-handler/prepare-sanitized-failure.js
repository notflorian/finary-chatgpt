const trigger = $('Workflow Error Trigger').first().json;
const schemaResponse = $('Fetch Operational Schema').first().json;
const body = schemaResponse.data ?? schemaResponse.body ?? schemaResponse;
const schema = typeof body === 'string' ? JSON.parse(body) : body;
if ((schemaResponse.statusCode ?? 200) < 200 || (schemaResponse.statusCode ?? 200) >= 300 || schema?.schema_version !== '2.1' || !schema?.sheets?.sync_runs) throw new Error('OPERATIONAL_SCHEMA_UNAVAILABLE');
const columns = schema.sheets.sync_runs.columns.map((column) => column.name);
const existingRows = $input.all().map((item) => item.json).filter((row) => row && row.run_id && row.run_id !== 'run_id');
const execution = trigger.execution ?? {};
const run = $('Resolve Source Execution').first().json;
validateRunContext(run, sourceExecutionId(execution.id));
const error = execution.error ?? {};
const raw = JSON.stringify({ message: error.message ?? '', description: error.description ?? '', name: error.name ?? '', node: execution.lastNodeExecuted ?? '' }).toLowerCase();
const step = typeof execution.lastNodeExecuted === 'string' ? execution.lastNodeExecuted : 'Unknown step';
const sheetSteps = new Set(['Preflight Overrides Header','Preflight Accounts Header','Preflight Positions Header','Preflight Liabilities Header','Preflight History Header','Preflight Daily Header','Preflight Sync Header','Read Asset Overrides','Read Current Accounts','Read Current Positions','Read Current Liabilities','Read Portfolio Daily','Read Sync Runs','Read Terminal Before Success','Read Terminal Before Failure','Upsert Current Accounts','Upsert Current Positions','Upsert Current Liabilities','Upsert Position History','Upsert Portfolio Daily','Record Successful Sync','Preflight Failure Sync Header','Record Failed Sync']);
let code = 'N8N_EXECUTION_FAILED';
let message = 'The synchronization workflow failed';
if (/quota|rate.?limit|too many requests|\b429\b|resource_exhausted/.test(raw)) { code = 'GOOGLE_RATE_LIMITED'; message = 'Google Sheets request quota was exceeded'; }
else if (sheetSteps.has(step) && /auth|credential|unauthorized|forbidden|\b401\b|\b403\b/.test(raw)) { code = 'GOOGLE_AUTH_FAILED'; message = 'Google Sheets authentication failed'; }
else if (/execution timed out|workflow.*timeout|timeout exceeded/.test(raw)) { code = 'WORKFLOW_TIMEOUT'; message = 'The synchronization workflow timed out'; }
else if (sheetSteps.has(step) && /timeout|timed out|econnreset|\b5\d\d\b|temporar|unavailable/.test(raw)) { code = 'GOOGLE_TEMPORARY_FAILURE'; message = 'Google Sheets was temporarily unavailable'; }
else if (sheetSteps.has(step) && /header|schema|column|mapping/.test(raw)) { code = 'GOOGLE_SCHEMA_MISMATCH'; message = 'Google Sheets schema validation failed'; }
else if (step.startsWith('Upsert ') || step.startsWith('Record ')) { code = 'WRITE_FAILED'; message = 'A portfolio write did not complete'; }
const safeStep = new Set(['Fetch Canonical Schema','Fetch Snapshot','Validate Snapshot','Snapshot Is Valid','Prepare Validated Rows', ...sheetSteps]).has(step) ? step : 'Unknown step';
const runId = run.run_id;
const alreadyRecorded = matchingTerminal(existingRows, run, true) !== null;
const successes = existingRows.filter((row) => ['SUCCESS','SUCCESS_WITH_WARNINGS'].includes(row.status) && Number.isFinite(Date.parse(row.completed_at))).sort((a, b) => Date.parse(b.completed_at) - Date.parse(a.completed_at));
const completedAt = new Date().toISOString();
const safeStartedAt = run.started_at;
const row = { run_id: runId, started_at: safeStartedAt, completed_at: completedAt, status: 'FAILED', accounts_count: null, positions_count: null, liabilities_count: null, liability_coverage: null, gross_assets_eur: null, liabilities_eur: null, net_worth_eur: null, previous_net_worth_eur: null, net_worth_change_pct: null, duration_ms: 0, bridge_version: null, schema_version: null, warning_count: 0, error_code: code, error_message: `${message} (${safeStep})` };
validateBatch(schema, 'sync_runs', [row]);
return [{ json: { should_record: !alreadyRecorded, row, schema, diagnostics: { error_code: code, failing_step: safeStep, execution_id: String(execution.id ?? 'unknown'), last_success_at: successes[0]?.completed_at ?? null } } }];