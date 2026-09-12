const {run,snapshot,schema}=$('Validate MCP Snapshot').first().json;
mcpRun(run,String($execution.id));mcpSnapshot(snapshot);
mcpAssert(mcpStable(schema)===mcpStable(mcpWorkbook));
const existing={};
for(const table of Object.keys(mcpWorkbook.sheets)){
  const node=`Read ${table}`;
  const physical=$(node).all().map(i=>i.json).filter(r=>Object.keys(r).length>0);
  const header=$(`Preflight ${table}`).first().json;
  mcpHeaders(table,Object.keys(header).filter(k=>k!=='row_number'));
  existing[table]=physical.map(row=>mcpDecode(table,row));
}
mcpControl(existing.writer_control,run);
mcpCollision(existing,run,snapshot.observation_id);
mcpRetained(existing);
const prepared=mcpBuild(snapshot,run,existing,existing.asset_overrides);
mcpPrepared(snapshot,run,prepared,existing,existing.asset_overrides);
return [{json:{schema,run,snapshot,existing,...prepared}}];
