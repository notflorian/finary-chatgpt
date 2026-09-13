const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return [{json:{has_rows:p.batches['accounts_current'].length>0}}];
