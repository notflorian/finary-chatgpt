const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('portfolio_members',p.batches['portfolio_members']);
