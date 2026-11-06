const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(require('node:path').join(__dirname, '../lib/api.ts'), 'utf8');
function apiFor(response) {
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,
    { module, exports:module.exports, process:{env:{}}, fetch: async () => ({ok:true,json:async()=>response}) });
  return module.exports;
}
test('previous API metadata is rejected before rendering', async () => {
  await assert.rejects(apiFor({model_version:'paper-v8',parameters:[],replication:{},paper_baseline:{regime_comparison:{}}}).getMeta(), /incompatible|earlier/i);
});
test('previous API run is rejected before accessing policy rows', async () => {
  await assert.rejects(apiFor({model_version:'paper-v8',regime_comparison:{flat_stabilization:{pv:{},joint:{}},spot_only:{pv:{},joint:{}},dual_switching:{pv:{},joint:{}}},switching:{},diagnostics:{},sensitivity:[],definitions:{},scope:[]}).runModel({},false,42), /incompatible|earlier/i);
});
