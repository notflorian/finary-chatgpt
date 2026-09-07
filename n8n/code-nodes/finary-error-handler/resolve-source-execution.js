const response = $input.first().json;
if (response.statusCode !== 200) throw new Error('SOURCE_RUN_IDENTITY_UNAVAILABLE');
return [{ json: resolveSourceRun($('Workflow Error Trigger').first().json, response.body) }];