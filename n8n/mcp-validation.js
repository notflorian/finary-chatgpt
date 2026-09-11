// Versioned MCP validation shared by the exported writer and reference consumer harness.
const mcpFail = () => { throw new Error('MCP_VALIDATION_FAILED'); };
const mcpAssert = (condition) => { if (!condition) mcpFail(); };
const mcpObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const mcpStable = (value) => JSON.stringify(value, (_key, v) => mcpObject(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k,v[k]])) : v);
const mcpDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10) === value;
const mcpInstant = value => typeof value === 'string' && /T.*(Z|[+-]\d{2}:\d{2})$/.test(value) && mcpDate(value.slice(0,10)) && Number.isFinite(Date.parse(value));
const mcpSchemaValid = (value, schema, definitions=mcpContract.$defs) => {
  if (!mcpObject(schema)) return false;
  if (schema.$ref && !mcpSchemaValid(value, definitions[schema.$ref.split('/').pop()], definitions)) return false;
  if (schema.const !== undefined && value !== schema.const) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.anyOf && !schema.anyOf.some(s=>mcpSchemaValid(value,s,definitions))) return false;
  if (schema.oneOf && schema.oneOf.filter(s=>mcpSchemaValid(value,s,definitions)).length !== 1) return false;
  if (schema.allOf && !schema.allOf.every(s=>mcpSchemaValid(value,s,definitions))) return false;
  if (schema.not && mcpSchemaValid(value,schema.not,definitions)) return false;
  if (schema.if) {
    const branch=mcpSchemaValid(value,schema.if,definitions) ? schema.then : schema.else;
    if (branch && !mcpSchemaValid(value,branch,definitions)) return false;
  }
  if (schema.type) {
    const types={object:mcpObject(value),array:Array.isArray(value),string:typeof value==='string',
      boolean:typeof value==='boolean',null:value===null,number:typeof value==='number'&&Number.isFinite(value),
      integer:typeof value==='number'&&Number.isSafeInteger(value)};
    if (!types[schema.type]) return false;
  }
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && [...value].length<schema.minLength) return false;
    if (schema.maxLength !== undefined && [...value].length>schema.maxLength) return false;
    if (schema.pattern && !(new RegExp(schema.pattern,'u')).test(value)) return false;
    if (schema.format==='date' && !mcpDate(value)) return false;
    if (schema.format==='date-time' && !mcpInstant(value)) return false;
    if (schema.format==='uuid' && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) return false;
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value<schema.minimum) return false;
    if (schema.maximum !== undefined && value>schema.maximum) return false;
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length<schema.minItems) return false;
    if (schema.maxItems !== undefined && value.length>schema.maxItems) return false;
    if (schema.items && !value.every(v=>mcpSchemaValid(v,schema.items,definitions))) return false;
    if (schema.contains && !value.some(v=>mcpSchemaValid(v,schema.contains,definitions))) return false;
    if (schema.uniqueItems && new Set(value.map(mcpStable)).size!==value.length) return false;
  }
  if (mcpObject(value)) {
    if (schema.required && !schema.required.every(k=>Object.hasOwn(value,k)&&value[k]!==undefined)) return false;
    if (schema.properties && !Object.entries(schema.properties).every(([k,s])=>!Object.hasOwn(value,k)||mcpSchemaValid(value[k],s,definitions))) return false;
    if (schema.additionalProperties===false && Object.keys(value).some(k=>!Object.hasOwn(schema.properties||{},k))) return false;
  }
  return value!==undefined;
};
const mcpSchema = (value,name) => mcpAssert(mcpSchemaValid(value,mcpContract.$defs[name]));
const mcpE = value => {
  mcpSchema(value,'id');
  return encodeURIComponent(value).replace(/[!'()*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase());
};
const mcpKey = (template,values) => mcpContract.identity[template].replace(/\{E\(([^)]+)\)\}/g,(_match,k)=>mcpE(values[k]));
const mcpUnique = (rows,fields) => mcpAssert(new Set(rows.map(row=>mcpStable(fields.map(k=>row[k])))).size===rows.length);
const mcpDecimal = value => {
  mcpSchema(value,'decimal');
  const negative=value.startsWith('-');
  const [whole,fraction='']=value.replace(/^-/,'').split('.');
  return BigInt(whole+fraction.padEnd(18,'0'))*(negative?-1n:1n);
};
const mcpMoney = (money,currency=null) => {
  if (currency!==null) mcpAssert(money.currency===currency);
  if (money.amount===null) { mcpAssert(money.amount_eur===null&&money.eur_basis==='UNAVAILABLE'); return; }
  mcpAssert(money.currency!==null);
  if (money.currency==='EUR') mcpAssert(money.amount_eur!==null&&money.eur_basis==='SOURCE_EUR'&&mcpDecimal(money.amount)===mcpDecimal(money.amount_eur));
  else if (currency!==null) mcpAssert(money.amount_eur===null&&money.eur_basis==='UNAVAILABLE');
};
const mcpParisDate = value => {
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const mcpSnapshot = snapshot => {
  mcpSchema(snapshot,'snapshot_v3');
  const p=snapshot.provenance,c=snapshot.coverage;
  const start=Date.parse(p.collection_started_at),end=Date.parse(p.collection_ended_at),generated=Date.parse(snapshot.generated_at);
  mcpAssert(start<=end&&end<=generated&&end-start<=180000&&snapshot.snapshot_date===mcpParisDate(snapshot.generated_at));
  const keys={accounts:['account_key'],connections:['connection_key'],ownership:['account_key','owner_key'],positions:['holding_type','holding_id'],position_rates:['position_key','source_field'],allocation_categories:['category'],allocation_types:['category','holding_type'],members:['member_ordinal'],warnings:['code','entity_key'],unsupported_details:['account_key','holding_type','reason']};
  for (const [table,fields] of Object.entries(keys)) mcpUnique(snapshot[table],fields);
  const accounts=new Map(snapshot.accounts.map(a=>[a.account_key,a]));
  const connections=new Set(snapshot.connections.map(c=>c.connection_key));
  for (const a of snapshot.accounts) {
    mcpAssert(a.account_key===mcpKey('account_key',{account_id:a.source_account_id}));
    mcpAssert(a.connection_state==='NO_CONNECTION'?a.connection_key===null:a.connection_state==='RESOLVED'?connections.has(a.connection_key):a.connection_key!==null);
    mcpMoney(a.native_balance);
    if(a.native_balance.eur_basis==='SOURCE_CONVERSION')mcpAssert(a.full_value_eur!==null&&mcpDecimal(a.native_balance.amount_eur)===mcpDecimal(a.full_value_eur));
  }
  for(const o of snapshot.ownership)mcpAssert(accounts.get(o.account_key)?.ownership_evidence==='EXPLICIT_ENTRIES'&&o.owner_key===mcpKey('owner_key',{owner_type:o.owner_type,owner_id:o.owner_source_id}));
  for(const row of snapshot.positions){
    const account=accounts.get(row.account_key);mcpAssert(Boolean(account));
    const values={account_id:account.source_account_id,holding_id:row.holding_id,holding_type:row.holding_type};
    mcpAssert(row.source_asset_id===mcpKey('source_asset_id',values)&&row.position_key===mcpKey('position_key',values));
    for(const field of ['current_value','buying_price']){mcpMoney(row[field]);mcpAssert(row[field].eur_basis!=='SOURCE_CONVERSION');}
  }
  const positions=new Set(snapshot.positions.map(p=>p.position_key));
  for(const row of snapshot.position_rates)mcpAssert(positions.has(row.position_key));
  for(const row of snapshot.unsupported_details)mcpAssert(accounts.has(row.account_key));
  const categories=new Set(snapshot.allocation_categories.map(a=>a.category));
  for(const row of snapshot.allocation_types)mcpAssert(categories.has(row.category));
  for(const row of [...snapshot.allocation_categories,...snapshot.allocation_types])mcpMoney(row.value,p.currency);
  for(const group of [snapshot.overview,...snapshot.members]){
    for(const field of ['gross_assets','reported_liabilities','reported_net_worth'])mcpMoney(group[field],p.currency);
    mcpAssert(group.reported_liabilities.amount===null||mcpDecimal(group.reported_liabilities.amount)>=0n);
  }
  mcpMoney(snapshot.overview.financial_assets,p.currency);
  for(const [dimension,rule]of Object.entries(mcpContract.valuation_contracts)){
    const rows=snapshot[rule.rows],known=rows.filter(r=>r[rule.money_field].amount!==null&&r[rule.money_field].currency!==null).length;
    mcpAssert(c[dimension]===(c[rule.collection]!=='COMPLETE'?'UNAVAILABLE':known===rows.length?'COMPLETE':known?'PARTIAL':'UNAVAILABLE'));
  }
  return snapshot;
};
const mcpRun = (run,executionId) => {
  mcpAssert(mcpObject(run)&&typeof executionId==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(executionId));
  mcpAssert(new RegExp(`^n8n-run:${executionId}:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`).test(run.run_id));
  mcpAssert(mcpInstant(run.started_at)&&Number.isSafeInteger(run.started_epoch_ms)&&Math.abs(Date.parse(run.started_at)-run.started_epoch_ms)<1000);
  mcpAssert(run.provider==='finary_official_mcp'&&run.api_schema==='3.0'&&run.workbook_schema==='3.0'&&run.source_contract_version==='1.0.0');
  mcpAssert(typeof run.writer_id==='string'&&run.writer_id.length>0&&Number.isSafeInteger(run.writer_generation)&&run.writer_generation>=1);
};
const mcpControl = (rows,run) => {
  mcpAssert(rows.length===1);
  const {row_key,...control}=rows[0];
  mcpSchema(control,'writer_control');
  mcpAssert(row_key==='singleton'&&control.state==='ACTIVE'&&control.writer_id===run.writer_id&&control.generation===run.writer_generation);
};
