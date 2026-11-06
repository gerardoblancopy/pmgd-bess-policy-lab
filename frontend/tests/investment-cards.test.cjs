const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function loadSource(file) {
  const module = { exports: {} };
  let source = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
  if (file === 'app/page.tsx') source += '\nmodule.exports.RegimesPanel = RegimesPanel; module.exports.inputsMatchRun = inputsMatchRun; module.exports.ReplicationPanel = ReplicationPanel;';
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { module, exports: module.exports, process: { env: {} }, require: (name) => {
    if (name === '@/components/charts') return { RegimeChart: () => null };
    if (name.startsWith('@/')) return loadSource(name.slice(2) + (name.endsWith('/ui') ? '.tsx' : '.ts'));
    return require(name);
  } });
  return module.exports;
}

const { POLICIES } = loadSource('lib/terminology.ts');
const { default: Page, RegimesPanel, inputsMatchRun, ReplicationPanel } = loadSource('app/page.tsx');
const result = {
  params_used: { n_paths: 5000 }, definitions: { exercise_rate: 'Share of paths investing.' },
  policy_comparison: Object.fromEntries(POLICIES.map(({ key }, index) => [key,
    Object.fromEntries(['pv', 'joint'].map((asset, offset) => [asset, {
      immediate_npv_musd: index + offset / 10 - 2.3456,
      pure_deferral_premium_musd: index + offset / 10 + 0.1234,
      option_value_musd: index + offset / 10 + 7,
      exercise_rate: 0.4 + offset / 10,
      mean_exercise_time: index + offset / 10,
    }])),
  ])),
};

test('eight investment cards show the matching policy and asset metrics', () => {
  const html = renderToStaticMarkup(React.createElement(RegimesPanel, { result, loading: false }));
  const cards = html.match(/<article class="stat-tile investment-card"[\s\S]*?<\/article>/g) ?? [];
  assert.equal(cards.length, 8);
  assert.ok(!cards.some((card) => card.includes('Historical flat')));
  for (const { key } of POLICIES.filter(({ key }) => key !== 'historical_flat')) {
    for (const asset of ['pv', 'joint']) {
      const card = cards.find((card) => card.includes(`data-policy="${key}"`) && card.includes(`data-asset="${asset}"`));
      assert.ok(card, `${key}/${asset} must be present`);
      const row = result.policy_comparison[key][asset];
      assert.ok(card.includes(`>${row.immediate_npv_musd.toFixed(4)} M USD<`));
      assert.ok(card.includes(`>${row.pure_deferral_premium_musd.toFixed(4)} M USD<`));
      assert.ok(card.includes(`>${row.mean_exercise_time.toFixed(2)} y<`));
      assert.match(card, /Immediate NPV N₀/);
      assert.match(card, /Exclusive deferral premium/);
      assert.match(card, /Mean investment time, if exercised/);
    }
  }
  assert.match(html, /MEP-only \(time-block\), no restitution/);
  assert.match(html, /Spot-only, no switching or restitution/);
});

test('a policy that never invests does not display an immediate investment time', () => {
  const noExercise = structuredClone(result);
  noExercise.policy_comparison.spot_only.pv.mean_exercise_time = null;
  noExercise.policy_comparison.spot_only.pv.exercise_rate = 0;
  const html = renderToStaticMarkup(React.createElement(RegimesPanel, { result: noExercise, loading: false }));
  const card = html.match(/<article class="stat-tile investment-card"[^>]*data-policy="spot_only"[^>]*data-asset="pv"[\s\S]*?<\/article>/)?.[0];
  assert.ok(card);
  assert.match(card, /Not exercised/);
  assert.match(card, /0\.0%/);
  assert.ok(!card.includes('>0.00 y<'));
});

test('edited inputs are distinguished from the last completed result', () => {
  const completed = { params_used: { s0_spot: 50, s0_mep: 90 }, seed: 42, sensitivity: [{}] };
  assert.equal(inputsMatchRun(completed, { s0_spot: 50, s0_mep: 90 }, 42, true), true);
  assert.equal(inputsMatchRun(completed, { s0_spot: 25, s0_mep: 90 }, 42, true), false);
  assert.equal(inputsMatchRun(completed, { s0_spot: 50, s0_mep: 90 }, 43, true), false);
  assert.equal(inputsMatchRun(completed, { s0_spot: 50, s0_mep: 90 }, 42, false), false);
  assert.equal(inputsMatchRun({ ...completed, sensitivity: [] }, completed.params_used, 42, false), true);
});

test('public UI exposes result exports without a manuscript download', () => {
  const completed = { ...result, seed: 42, runtime_s: 1, run_id: 'test', model_sha256: '0'.repeat(64), model_version: 'test', scope: [] };
  const markup = renderToStaticMarkup(React.createElement(Page)) + renderToStaticMarkup(React.createElement(ReplicationPanel, { result: completed, meta: { replication: { command: 'python lsmc_switching_cases.py' } }, isPaperRun: true }));
  assert.doesNotMatch(markup, /href="[^"]*\.pdf[^"]*"/i);
  assert.doesNotMatch(markup, /Download manuscript|Download IEEE Access manuscript/);
  assert.match(markup, /Download run JSON/);
  assert.match(markup, /Download results CSV/);
});
