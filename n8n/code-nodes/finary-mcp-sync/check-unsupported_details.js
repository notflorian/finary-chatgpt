const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return [{json:{has_rows:p.batches['unsupported_details'].length>0}}];
