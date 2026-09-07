const prepared = $('Prepare Validated Rows').first().json;
return sheetsItems(prepared.schema, 'positions_history', prepared.history_rows);
