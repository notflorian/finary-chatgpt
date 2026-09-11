// Typed cells and observation membership; native decimal strings never become Numbers.
const mcpTableInputs = {accounts_current:'accounts',positions_current:'positions',positions_history:'positions',portfolio_daily:'overview',account_ownership:'ownership',source_connections:'connections',position_rates:'position_rates',official_allocation_categories:'allocation_categories',official_allocation_types:'allocation_types',portfolio_members:'members',observations:'observation',source_warnings:'warnings',unsupported_details:'unsupported_details'};
const mcpChildFields = {account_ownership:['account_key','owner_key'],source_connections:['connection_key'],position_rates:['position_key','source_field'],official_allocation_categories:['category'],official_allocation_types:['category','holding_type'],portfolio_members:['member_ordinal'],source_warnings:['code','entity_key'],unsupported_details:['account_key','holding_type','reason']};
const mcpPointer = (value,path) => path.split('/').slice(1).reduce((value,key)=>value?.[key],value);
const mcpPut = (value,path,leaf) => {
  const parts=path.split('/').slice(1),last=parts.pop();
  for(const part of parts){value[part]??={};value=value[part];}value[last]=leaf;
};
const mcpBlankRow = table => Object.fromEntries(mcpWorkbook.sheets[table].columns.map(c=>[c.name,null]));
const mcpHeaders = (table,headers) => mcpAssert(mcpStable(headers)===mcpStable(mcpWorkbook.sheets[table].columns.map(c=>c.name)));
const mcpDecode = (table,input) => {
  mcpAssert(mcpObject(input));
  const schema=mcpWorkbook.sheets[table],allowed=new Set(schema.columns.map(c=>c.name));
  mcpAssert(Object.keys(input).every(k=>k==='row_number'||allowed.has(k)));
  const row={};
  for(const column of schema.columns){
    let value=Object.hasOwn(input,column.name)?input[column.name]:null;
    mcpAssert(value!==undefined);
    if(value==='')value=null;
    if(column.type==='BOOLEAN'&&['TRUE','FALSE'].includes(value))value=value==='TRUE';
    if(column.type==='NUMBER'&&typeof value==='string'&&/^-?\d+(\.\d+)?$/.test(value))value=Number(value);
    row[column.name]=value;
  }
  return row;
};
const mcpRow = (table,row) => {
  const columns=mcpWorkbook.sheets[table].columns;
  mcpAssert(mcpObject(row)&&Object.keys(row).length===columns.length&&columns.every(c=>Object.hasOwn(row,c.name)));
  for(const c of columns){
    const value=row[c.name];mcpAssert(value!==undefined);
    if(value===null){mcpAssert(c.nullable);continue;}
    const valid=c.type==='NUMBER'?typeof value==='number'&&Number.isFinite(value):c.type==='BOOLEAN'?typeof value==='boolean':c.type==='DATE'?mcpDate(value):c.type==='DATETIME'?mcpInstant(value):typeof value==='string';
    mcpAssert(valid);
    if(c.mcp_schema)mcpAssert(mcpSchemaValid(value,c.mcp_schema));
  }
  const key=mcpWorkbook.sheets[table].unique_key;
  mcpAssert(typeof row[key]==='string'&&row[key].length>0);
  const definition=mcpWorkbook.mcp_tables[table];
  if(definition?.row_schema){
    const normalized={};
    for(const [name,path]of Object.entries(definition.column_bindings))mcpPut(normalized,path,row[name]);
    mcpAssert(mcpSchemaValid(normalized,{$ref:definition.row_schema}));
  }
};
const mcpBatch = (table,rows) => {mcpAssert(Array.isArray(rows));mcpUnique(rows,[mcpWorkbook.sheets[table].unique_key]);for(const row of rows)mcpRow(table,row);};
const mcpItems = (table,rows) => {mcpBatch(table,rows);return rows.map(row=>({json:Object.fromEntries(Object.entries(row).map(([k,v])=>[k,v===null?'':v]))}));};
const mcpChildKey = (observation,table,row) => `${observation}:${mcpE(table)}:${mcpChildFields[table].map(field=>field==='entity_key'?(row[field]===null?'~null':'~value'+mcpE(row[field])):mcpE(String(row[field]))).join(':')}`;
const mcpPermitted = snapshot => {
  const accounts=snapshot.coverage.accounts==='COMPLETE',positions=accounts&&snapshot.coverage.holdings==='COMPLETE'&&['SUPPORTED','UNVERIFIED'].includes(snapshot.coverage.detail_semantics);
  return {accounts_current:accounts,positions_current:positions,positions_history:positions,portfolio_daily:true,
    account_ownership:accounts,source_connections:accounts,position_rates:positions,official_allocation_categories:true,
    official_allocation_types:true,portfolio_members:true,observations:true,source_warnings:true,unsupported_details:accounts,liabilities_current:false};
};
const mcpBuild = (snapshot,run,existing,overrides=[]) => {
  mcpSnapshot(snapshot);
  const permitted=mcpPermitted(snapshot),batches={};
  const positions=JSON.parse(JSON.stringify(snapshot.positions));
  const enabled=overrides.filter(o=>o.enabled===true&&typeof o.source_asset_id==='string'&&o.source_asset_id.startsWith('mcp:holding:'));
  mcpUnique(enabled,['source_asset_id']);
  for(const position of positions){
    const override=enabled.find(o=>o.source_asset_id===position.source_asset_id);
    if(override){mcpAssert(mcpContract.$defs.position.properties.asset_class.enum.includes(override.custom_asset_class));position.asset_class=override.custom_asset_class;}
  }
  const source={...snapshot,positions,observation:{observation_id:snapshot.observation_id,run_id:run.run_id,snapshot_date:snapshot.snapshot_date,generated_at:snapshot.generated_at,provenance:snapshot.provenance,coverage:snapshot.coverage}};
  for(const [table,input]of Object.entries(mcpTableInputs)){
    const rows=Array.isArray(source[input])?source[input]:[source[input]],definition=mcpWorkbook.mcp_tables[table];
    batches[table]=permitted[table]?rows.map(value=>{
      const row=mcpBlankRow(table);
      for(const [column,path]of Object.entries(definition.column_bindings))row[column]=mcpPointer(value,path);
      for(const [column,v]of Object.entries({observation_id:snapshot.observation_id,run_id:run.run_id,provider:run.provider}))if(Object.hasOwn(row,column))row[column]=v;
      if(mcpChildFields[table])row.row_key=mcpChildKey(snapshot.observation_id,table,value);
      if(table==='accounts_current'||table==='positions_current'){
        row.source=run.provider;row.last_seen_run_id=run.run_id;row.last_seen_at=snapshot.generated_at;row.is_active=true;
        if(table==='accounts_current'){row.name=value.label;row.account_type=value.account_type;row.currency=value.native_balance.currency;}
      }
      if(table==='positions_history'){
        row.history_key=`mcp:history:${snapshot.snapshot_date}:${snapshot.observation_id}:${value.position_key}`;
        row.snapshot_date=snapshot.snapshot_date;row.generated_at=snapshot.generated_at;
      }
      if(table==='portfolio_daily'){
        row.daily_key=`mcp:daily:${snapshot.snapshot_date}:${snapshot.observation_id}`;
        row.snapshot_date=snapshot.snapshot_date;row.generated_at=snapshot.generated_at;
      }
      return row;
    }):[];
  }
  batches.liabilities_current=[];
  for(const table of ['accounts_current','positions_current']){
    if(!permitted[table])continue;
    const key=mcpWorkbook.sheets[table].unique_key,seen=new Set(batches[table].map(r=>r[key]));
    for(const old of existing[table]||[]){
      if(old.source==='finary_official_mcp'&&!seen.has(old[key])){
        mcpRow(table,old);batches[table].push({...old,is_active:false});
      }
    }
  }
  const terminal=mcpBlankRow('sync_runs');
  Object.assign(terminal,{run_id:run.run_id,started_at:run.started_at,completed_at:run.started_at,duration_ms:0,
    status:snapshot.warnings.length?'SUCCESS_WITH_WARNINGS':'SUCCESS',schema_version:'3.0',workbook_schema:'3.0',
    observation_id:snapshot.observation_id,provider:run.provider,source_contract_version:mcpContract.contract_version,
    writer_generation:run.writer_generation,writer_id:run.writer_id,warning_count:snapshot.warnings.length,
    accounts_count:permitted.accounts_current?snapshot.accounts.length:null,positions_count:permitted.positions_current?snapshot.positions.length:null,
    series_break:mcpSeriesBreak(existing,snapshot.provenance)});
  for(const [table,column]of Object.entries(mcpWorkbook.mcp_tables.sync_runs.count_columns)){
    terminal[column]=permitted[table]?batches[table].filter(r=>!Object.hasOwn(r,'is_active')||r.is_active===true).length:null;
  }
  batches.sync_runs=[terminal];
  return {batches,permitted};
};
const mcpPrepared = (snapshot,run,prepared,existing,overrides) => {
  const expected=mcpBuild(snapshot,run,existing,overrides);
  mcpAssert(mcpStable(prepared)===mcpStable(expected));
  for(const [table,rows]of Object.entries(prepared.batches))mcpBatch(table,rows);
  for(const [table,rows]of Object.entries(prepared.batches)){
    if(table==='sync_runs')continue;
    for(const row of rows){
      if(Object.hasOwn(row,'is_active')&&row.is_active===false)continue;
      mcpAssert(row.observation_id===snapshot.observation_id&&row.run_id===run.run_id);
    }
  }
};
const mcpCollision = (existing,run,observation) => {
  for(const [table,rows]of Object.entries(existing)){
    if(!mcpWorkbook.sheets[table])continue;
    mcpUnique(rows,[mcpWorkbook.sheets[table].unique_key]);
    for(const row of rows)mcpAssert(row.run_id!==run.run_id&&row.last_seen_run_id!==run.run_id&&row.observation_id!==observation);
  }
};
const mcpTerminal = (rows,run,observation) => {
  mcpUnique(rows,['run_id']);
  mcpAssert(!rows.some(r=>r.run_id===run.run_id||r.observation_id===observation));
};
const mcpNormalized = (table,row) => {
  const value={};for(const [column,path]of Object.entries(mcpWorkbook.mcp_tables[table].column_bindings))mcpPut(value,path,row[column]);return value;
};
const mcpRetained = existing => {
  for(const [table,rows]of Object.entries(existing)){
    if(!mcpTableInputs[table])continue;
    for(const row of rows){
      if(!row.observation_id)continue;
      mcpRow(table,row);
      if(table.endsWith('_current'))mcpAssert(row.source==='finary_official_mcp'&&row.provider==='finary_official_mcp');
      if(mcpChildFields[table])mcpAssert(row.row_key===mcpChildKey(row.observation_id,table,mcpNormalized(table,row)));
      if(table==='positions_history')mcpAssert(row.history_key===`mcp:history:${row.snapshot_date}:${row.observation_id}:${row.position_key}`);
      if(table==='portfolio_daily')mcpAssert(row.daily_key===`mcp:daily:${row.snapshot_date}:${row.observation_id}`);
      const terminal=existing.sync_runs.filter(r=>r.observation_id===row.observation_id);
      mcpAssert(terminal.length<=1);
      if(terminal.length)mcpAssert(terminal[0].run_id===row.run_id&&terminal[0].provider==='finary_official_mcp');
    }
  }
  for(const terminal of existing.sync_runs.filter(r=>r.provider==='finary_official_mcp'&&['SUCCESS','SUCCESS_WITH_WARNINGS'].includes(r.status))){
    mcpRow('sync_runs',terminal);
    mcpAssert(terminal.schema_version==='3.0'&&terminal.workbook_schema==='3.0'&&terminal.source_contract_version===mcpContract.contract_version);
    const observations=existing.observations.filter(r=>r.observation_id===terminal.observation_id&&r.run_id===terminal.run_id);
    mcpAssert(observations.length===1);
    for(const [table,column]of Object.entries(mcpWorkbook.mcp_tables.sync_runs.count_columns)){
      if(table.endsWith('_current'))continue;
      const selected=existing[table].filter(r=>r.observation_id===terminal.observation_id);
      mcpAssert(terminal[column]===null?selected.length===0:selected.length===terminal[column]);
    }
  }
};
const mcpSeriesBreak = (existing,provenance) => {
  const successful=(existing.sync_runs||[]).filter(r=>['SUCCESS','SUCCESS_WITH_WARNINGS'].includes(r.status));
  if(!successful.length)return true;
  mcpAssert(successful.every(r=>mcpInstant(r.completed_at)));
  successful.sort((a,b)=>Date.parse(b.completed_at)-Date.parse(a.completed_at));
  if(successful.length>1&&Date.parse(successful[0].completed_at)===Date.parse(successful[1].completed_at))return true;
  const previous=successful[0];
  if(previous.provider!=='finary_official_mcp'||previous.schema_version!=='3.0'||previous.source_contract_version!==provenance.source_contract_version)return true;
  const context=(existing.observations||[]).find(r=>r.run_id===previous.run_id&&r.observation_id===previous.observation_id);
  if(!context)return true;
  const other=mcpNormalized('observations',context).provenance;
  return ['provider','source_contract_version','scope','ownership_basis','metric','currency'].some(field=>other[field]!==provenance[field]);
};
