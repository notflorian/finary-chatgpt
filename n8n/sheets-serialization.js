// Only call after contract validation. Keep internal rows immutable and nullable;
// auto-mapped Sheets updates skip null but write '' as an explicit cell clear.
const sheetsItems = (schema, sheetName, rows) => {
  const columns = schema.sheets[sheetName].columns;
  const expected = columns.map((column) => column.name);
  return rows.map((row) => {
    const actual = Object.keys(row);
    if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new Error(`TARGET_SCHEMA_MISMATCH:${sheetName}`);
    const json = {};
    for (const column of columns) {
      const value = row[column.name];
      // Never hide absent fields, explicit undefined, or invalid required blanks.
      if (value === undefined || (!column.nullable && (value === null || value === ''))) throw new Error(`CONTRACT_VALIDATION_FAILED:${sheetName}.${column.name}`);
      json[column.name] = value === null ? '' : value;
    }
    return { json };
  });
};
