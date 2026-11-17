/* Development gate only; no parser or Node.js is an application dependency. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const acorn = require('acorn');
const root = path.resolve(__dirname, '..');
for (const [name, version] of [['bootstrap.js', 5], ['app.js', 2017]]) {
  const filename = path.join(root, 'source', 'static', name);
  acorn.parse(fs.readFileSync(filename, 'utf8'), {
    ecmaVersion: version,
    sourceType: 'script'
  });
  process.stdout.write(`${name}: ECMAScript ${version} syntax PASS\n`);
}
