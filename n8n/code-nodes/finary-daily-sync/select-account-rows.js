const prepared = $('Prepare Validated Rows').first().json;
return sheetsItems(prepared.schema, 'accounts_current', prepared.account_rows);
