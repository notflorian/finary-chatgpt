const prepared = $('Prepare Validated Rows').first().json;
return sheetsItems(prepared.schema, 'positions_current', prepared.position_rows);
