const p=$('Prepare MCP Rows').first().json;
mcpRun(p.run,String($execution.id));
return mcpItems('unsupported_details',p.batches['unsupported_details']);
