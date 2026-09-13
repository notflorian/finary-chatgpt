const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('account_ownership',p.batches['account_ownership']);
