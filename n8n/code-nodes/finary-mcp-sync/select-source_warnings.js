const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('source_warnings',p.batches['source_warnings']);
