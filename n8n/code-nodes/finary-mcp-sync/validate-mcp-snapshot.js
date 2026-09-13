const run=$('Initialize MCP Run').first().json;
mcpRun(run,String($execution.id));
const response=name=>{
  const response=$(name).first().json;
  mcpAssert(response.statusCode===200);
  try{return typeof response.body==='string'?JSON.parse(response.body):response.body;}catch{mcpFail();}
};
const schema=response('Fetch MCP Schema');
mcpAssert(mcpStable(schema)===mcpStable(mcpWorkbook));
const snapshot=mcpSnapshot(response('Fetch MCP Snapshot'));
return [{json:{run,schema,snapshot}}];
