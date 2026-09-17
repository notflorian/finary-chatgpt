const run=$('Initialize MCP Run').first().json;
mcpRun(run,String($execution.id));
const control=$('Failure Writer Control').all().map(i=>i.json).filter(r=>Object.keys(r).length).map(r=>mcpDecode('writer_control',r));
mcpControl(control,run);
const header=$('Failure Terminal Header').first().json;
mcpHeaders('sync_runs',Object.keys(header).filter(k=>k!=='row_number'));
const terminals=$('Failure Terminal Read').all().map(i=>i.json).filter(r=>Object.keys(r).length).map(r=>mcpDecode('sync_runs',r));
mcpBatch('sync_runs',terminals);
// A lost terminal response must not overwrite the successful terminal already stored.
if(terminals.some(r=>r.run_id===run.run_id))return [];
// Error-branch execution must explicitly read the normal preparation output.
let observation=null;
try{const p=$('Prepare MCP Rows').first(0).json;mcpRun(p.run,String($execution.id));mcpAssert(p.run.run_id===run.run_id);observation=p.snapshot.observation_id;}catch{}
if(observation!==null)mcpAssert(!terminals.some(r=>r.observation_id===observation));
const completed=new Date();
const row=mcpBlankRow('sync_runs');
Object.assign(row,{run_id:run.run_id,started_at:run.started_at,completed_at:completed.toISOString(),duration_ms:Math.max(0,completed.getTime()-run.started_epoch_ms),
  status:'FAILED',api_schema:mcpWorkbook.api_schema,workbook_schema:mcpWorkbook.schema_version,provider:run.provider,source_contract_version:run.source_contract_version,
  writer_generation:run.writer_generation,writer_id:run.writer_id,observation_id:observation,warning_count:0,
  error_code:'MCP_SYNC_FAILED',error_message:'The MCP synchronization failed. Validate the workbook before retrying.'});
return mcpItems('sync_runs',[row]);
