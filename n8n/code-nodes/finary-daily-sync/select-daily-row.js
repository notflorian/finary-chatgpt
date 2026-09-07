const prepared = $('Prepare Validated Rows').first().json;
return sheetsItems(prepared.schema, 'portfolio_daily', prepared.daily_rows);
