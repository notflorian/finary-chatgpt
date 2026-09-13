const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('positions_history',p.batches['positions_history']);
