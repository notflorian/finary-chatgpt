const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('positions_current',p.batches['positions_current']);
