const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('official_allocation_categories',p.batches['official_allocation_categories']);
