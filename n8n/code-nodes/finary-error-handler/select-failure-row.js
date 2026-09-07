const prepared = $('Prepare Sanitized Failure').first().json;
return sheetsItems(prepared.schema, 'sync_runs', [prepared.row]);
