const prepared = $('Prepare Validated Rows').first().json;
const run = $('Validate Snapshot').first().json.run;
validateRunContext(run, $execution.id);
if (prepared.sync_run_rows?.[0]?.run_id !== run.run_id) throw new Error('STALE_EXECUTION_IDENTITY');
matchingTerminal($input.all().map((item) => item.json), run);
// Finalize after portfolio writes; the terminal Sheets request and its retries are excluded.
const completed = new Date();
const completedEpochMs = completed.getTime();
if (!Number.isFinite(run.started_epoch_ms) || !Number.isFinite(new Date(run.started_epoch_ms).getTime()) || !Number.isFinite(completedEpochMs)) throw new Error('INVALID_RUN_TIMING');
const durationMs = Math.max(0, completedEpochMs - run.started_epoch_ms);
if (!Number.isFinite(durationMs)) throw new Error('INVALID_RUN_TIMING');
const completedAt = completed.toISOString();
const rows = prepared.sync_run_rows.map((json) => ({ ...json, completed_at: completedAt, duration_ms: durationMs }));
validateBatch(prepared.schema, 'sync_runs', rows);
if (rows.length !== 1 || rows[0].started_at !== run.started_at || !['SUCCESS', 'SUCCESS_WITH_WARNINGS'].includes(rows[0].status)) invalidContract('sync_runs.status');
return sheetsItems(prepared.schema, 'sync_runs', rows);
