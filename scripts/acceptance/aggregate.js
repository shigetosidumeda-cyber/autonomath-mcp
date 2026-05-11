#!/usr/bin/env node
/* acceptance/aggregate.js - merge per-category JSONs into status_acceptance.json */
const fs = require('fs');
const path = require('path');
const dir = process.argv[2] || 'data/acceptance/';
const all = [];
for (const sub of fs.readdirSync(dir)) {
  for (const f of fs.readdirSync(path.join(dir, sub))) {
    if (f.endsWith('.json')) {
      const data = JSON.parse(fs.readFileSync(path.join(dir, sub, f)));
      all.push(...(data.items || []));
    }
  }
}
const passed = all.filter(i => i.pass).length;
const out = {
  schema_version: '1.0',
  generated_at: new Date().toISOString(),
  summary: { passed, total: all.length, ratio: all.length ? passed / all.length : 0 },
  items: all
};
console.log(JSON.stringify(out, null, 2));
