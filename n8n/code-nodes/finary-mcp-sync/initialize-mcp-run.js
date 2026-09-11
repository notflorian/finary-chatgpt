const executionId=String($execution.id);
const nonce=require('crypto').randomUUID();
const now=new Date();
const run={run_id:`n8n-run:${executionId}:${nonce}`,started_at:now.toISOString(),started_epoch_ms:now.getTime(),
  provider:'finary_official_mcp',api_schema:'3.0',workbook_schema:'3.0',source_contract_version:'1.0.0',
  writer_id:$env.FINARY_MCP_WRITER_ID,writer_generation:Number($env.FINARY_MCP_WRITER_GENERATION),
  workbook_id:$env.FINARY_MCP_GOOGLE_SHEET_ID};
mcpRun(run,executionId);
mcpAssert(typeof run.workbook_id==='string'&&run.workbook_id.length>0);
return [{json:run}];
