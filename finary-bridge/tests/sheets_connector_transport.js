// Run inside the Compose-pinned image. Replace only Sheets I/O, keeping the
// installed operation, update preparation, addressing and append conversion.
const assert = require('node:assert/strict');
assert.equal(require('/usr/local/lib/node_modules/n8n/package.json').version, '2.35.5');
const base = '/usr/local/lib/node_modules/n8n/node_modules/n8n-nodes-base/dist/nodes/Google/Sheet/v2/';
const { GoogleSheet } = require(base + 'helpers/GoogleSheet.js');
const { execute } = require(base + 'actions/sheet/appendOrUpdate.operation.js');
const { createInterface } = require('node:readline');

async function apply({ schema, workbook, writes }) {
  const updates = [];
  for (const { node, rows } of writes) {
    assert.equal(node.typeVersion, 4.7);
    assert.equal(node.parameters.operation, 'appendOrUpdate');
    const name = node.parameters.sheetName.value;
    const headers = schema.sheets[name].columns.map(column => column.name);
    const cells = [headers, ...workbook[name].map(row => headers.map(key => row[key] ?? ''))];
    const context = {
      getNode: () => node,
      getInputData: () => rows.map(json => ({ json })),
      getNodeParameter: (path, index, fallback) => {
        const value = path.split('.').reduce((value, key) => value?.[key], node.parameters);
        if (value === undefined && fallback === undefined) throw new Error(`Unexpected parameter: ${path}`);
        if (typeof value === 'string' && value.startsWith('={{')) {
          const $ = () => ({ first: () => ({ json: { schema } }) });
          return new Function('$', `return (${value.slice(3, -2)});`)($);
        }
        return value ?? fallback;
      },
    };
    const sheet = new GoogleSheet('synthetic-workbook', context);
    sheet.getData = async () => structuredClone(cells);
    sheet.batchUpdate = async (data, mode) => {
      assert.equal(mode, 'RAW');
      for (const update of data) {
        const match = /^(.+)!([A-Z]+)([0-9]+)$/.exec(update.range);
        assert.equal(match[1], name);
        const column = [...match[2]].reduce((index, c) => index * 26 + c.charCodeAt(0) - 64, 0) - 1;
        const row = Number(match[3]) - 1;
        const value = update.values[0][0];
        updates.push({ node: node.name, sheet: name, key: cells[row][0], column: headers[column], value });
        // ValueRange null/omission leaves a cell unchanged; '' explicitly clears it.
        if (value !== null && value !== undefined) cells[row][column] = value;
      }
    };
    sheet.appendEmptyRowsOrColumns = async () => {};
    sheet.appendData = async (range, data, mode, lastRow) => {
      assert.equal(mode, 'RAW');
      for (const [offset, values] of data.entries()) {
        const row = lastRow - 1 + offset;
        cells[row] ??= headers.map(() => '');
        values.forEach((value, column) => {
          if (value !== null && value !== undefined) cells[row][column] = value;
        });
      }
    };
    await execute.call(context, sheet, name, 'synthetic-sheet');
    workbook[name] = cells.slice(1).map(values => Object.fromEntries(headers.map((key, i) => [key, values[i] ?? ''])));
  }
  return { workbook, updates };
}

(async () => {
  for await (const line of createInterface({ input: process.stdin })) {
    try {
      process.stdout.write(JSON.stringify(await apply(JSON.parse(line))) + '\n');
    } catch (error) {
      process.stdout.write(JSON.stringify({ error: error.stack }) + '\n');
    }
  }
})();
