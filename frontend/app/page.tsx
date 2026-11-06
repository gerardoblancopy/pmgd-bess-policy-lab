"use client";

import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Moon, Play, SlidersHorizontal, Sun } from "lucide-react";
import {
  ContinuationCharts,
  DistributionCharts,
  RegimeChart,
  SensitivityCharts,
  SwitchingValueChart,
} from "@/components/charts";
import { DefinitionNote, ParamSlider, StatTile, Toggle } from "@/components/ui";
import {
  getMeta,
  runModel,
  type AssetKey,
  type Meta,
  type ModelResult,
  type ParamMeta,
  type SwitchingAssetKey,
} from "@/lib/api";
import { ASSETS, REGIMES, POLICIES, SWITCHING_SERIES, GLOSSARY } from "@/lib/terminology";

const TABS = [
  { id: "regimes", label: "Policy comparison" },
  { id: "deferral", label: "Investment deferral" },
  { id: "switching", label: "Operating switching" },
  { id: "sensitivity", label: "Sensitivity" },
  { id: "diagnostics", label: "Diagnostics" },
  { id: "replicate", label: "Reproducibility" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const pct = (value: number) => `${(100 * value).toFixed(1)}%`;
const musd = (value: number) => `${value.toFixed(3)} M`;
const years = (value: number | null) => value == null ? "Not exercised" : `${value.toFixed(2)} y`;

function inputsMatchRun(result: ModelResult, params: Record<string, number>, seed: number, withSensitivity: boolean) {
  return seed === result.seed
    && withSensitivity === (result.sensitivity.length > 0)
    && Object.entries(params).every(([key, value]) => result.params_used[key] === value);
}

function downloadBlob(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function resultCsv(result: ModelResult) {
  const rows: (string | number)[][] = [
    ["section", "scenario", "asset", "metric", "value", "unit"],
  ];
  for (const { key: regime } of REGIMES) {
    for (const asset of ["pv", "joint"] as AssetKey[]) {
      const metric = result.regime_comparison[regime][asset];
      rows.push(["regime", regime, asset, "option_value", metric.option_value_musd, "M USD"]);
      rows.push(["regime", regime, asset, "exercise_rate", metric.exercise_rate, "share"]);
      rows.push(["regime", regime, asset, "mean_exercise_time", metric.mean_exercise_time ?? "", "years"]);
    }
  }
  for (const { key } of POLICIES) {
    for (const asset of ["pv", "joint"] as AssetKey[]) {
      const row = result.policy_comparison[key][asset];
      rows.push(["policy", key, asset, "exercise_rate", row.exercise_rate, "share"]);
      rows.push(["policy", key, asset, "mean_exercise_time", row.mean_exercise_time ?? "", "years"]);
      for (const field of ["option_value_musd", "immediate_npv_musd", "immediate_decision_value_musd", "pure_deferral_premium_musd", "gain_vs_forced_immediate_musd", "avoided_negative_npv_musd"] as const) {
        rows.push(["policy", key, asset, field, row[field], "M USD"]);
      }
    }
  }
  for (const { key: asset } of ASSETS) {
    const metric = result.switching[asset];
    metric.settlement.mean_annual_accrual_usd.forEach((balance, year) => {
      for (let month = 1; month <= 12; month++) {
        rows.push(["settlement", (year + month / 12).toFixed(6), asset, "mean_real_monthly_installment", balance / 12, "USD"]);
      }
    });
    rows.push(["switching", "one_year", asset, "premium", metric.premium_new_musd, "M USD"]);
    rows.push(["switching", "one_vs_four_year", asset, "reform_gain", metric.reform_gain_musd, "M USD"]);
    rows.push(["migration", "one_year", asset, "terminal_spot_share", metric.migration.new_share_spot_terminal, "share"]);
    rows.push(["migration", "one_year", asset, "mean_switches", metric.migration.new_mean_switches, "count"]);
  }
  for (const row of result.sensitivity) {
    rows.push(["sensitivity", row.sigma_spot, row.asset, "premium", row.premium_new_musd, "M USD"]);
    rows.push(["sensitivity", row.sigma_spot, row.asset, "reform_gain", row.reform_gain_musd, "M USD"]);
  }
  for (const [section, diagnostics] of [
    ["option_distribution", result.diagnostics.distributions],
    ["npv_distribution", result.diagnostics.npv_distributions],
  ] as const) {
    for (const { key: regime } of REGIMES) {
      for (const asset of ["pv", "joint"] as AssetKey[]) {
        const metric = diagnostics[regime][asset];
        for (const field of ["mean", "median", "p05", "p95", "zero_mass", "negative_mass"] as const) {
          rows.push([section, regime, asset, field, metric[field], field.endsWith("mass") ? "share" : "M USD"]);
        }
      }
    }
  }
  for (const { key: regime } of REGIMES) {
    for (const asset of ["pv", "joint"] as AssetKey[]) {
      const diagnostic = result.diagnostics.continuation[regime][asset];
      diagnostic.state.forEach((state, index) => {
        rows.push(["continuation", regime, asset, `year_${result.diagnostics.year}_state`, state, "USD/MWh"]);
        rows.push(["continuation", regime, asset, `bin_${index + 1}_exercise_payoff`, diagnostic.exercise_payoff[index], "M USD"]);
        rows.push(["continuation", regime, asset, `bin_${index + 1}_continuation_value`, diagnostic.continuation_value[index], "M USD"]);
      });
    }
  }
  return rows
    .map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
    .join("\n");
}

export default function Page() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [params, setParams] = useState<Record<string, number>>({});
  const [seed, setSeed] = useState(42);
  const [tab, setTab] = useState<Tab>("regimes");
  const [autoRun, setAutoRun] = useState(false);
  const [withSensitivity, setWithSensitivity] = useState(true);
  const [result, setResult] = useState<ModelResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [controlsOpen, setControlsOpen] = useState(false);
  const booted = useRef(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem("pmgd-bess-theme");
    const initial = stored === "light" || stored === "dark"
      ? stored
      : window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    setTheme(initial);
    document.documentElement.dataset.theme = initial;
  }, []);

  useEffect(() => {
    getMeta()
      .then((metadata) => {
        setMeta(metadata);
        setSeed(metadata.replication.seed);
        setParams(Object.fromEntries(metadata.parameters.map((p) => [p.name, p.default])));
      })
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await runModel(params, withSensitivity, seed));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, [params, seed, withSensitivity]);

  useEffect(() => {
    if (meta && !booted.current && Object.keys(params).length > 0) {
      booted.current = true;
      void run();
    }
  }, [meta, params, run]);

  useEffect(() => {
    if (!autoRun || !booted.current) return;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => void run(), 650);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [autoRun, params, run, seed, withSensitivity]);

  const groups = useMemo(() => {
    const grouped: Record<string, ParamMeta[]> = {};
    for (const parameter of meta?.parameters ?? []) {
      grouped[parameter.group] = [...(grouped[parameter.group] ?? []), parameter];
    }
    return Object.entries(grouped);
  }, [meta]);

  const inputsMatchPaper = Boolean(
    meta &&
    seed === meta.replication.seed &&
    meta.parameters.every((parameter) => params[parameter.name] === parameter.default),
  );

  const isPaperRun = Boolean(meta && result && result.seed === meta.replication.seed &&
    meta.parameters.every((parameter) => result.params_used[parameter.name] === parameter.default));
  const pendingInputs = Boolean(result && !inputsMatchRun(result, params, seed, withSensitivity));

  const loadPriceSensitivity = () => {
    if (!meta) return;
    const preset = Object.fromEntries(meta.parameters.map((p) => [p.name, p.default]));
    setParams({ ...preset, s0_spot: 50, s0_mep: 90 });
    setSeed(42);
    setTab("deferral");
  };

  const reset = () => {
    if (!meta) return;
    setParams(Object.fromEntries(meta.parameters.map((p) => [p.name, p.default])));
    setSeed(meta.replication.seed);
    setWithSensitivity(true);
  };

  const toggleTheme = () => {
    setTheme((current) => {
      const next = current === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      window.localStorage.setItem("pmgd-bess-theme", next);
      return next;
    });
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = TABS.length - 1;
    const nextIndex = event.key === "ArrowRight"
      ? (index + 1) % TABS.length
      : event.key === "ArrowLeft"
        ? (index - 1 + TABS.length) % TABS.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? last
            : null;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = TABS[nextIndex];
    setTab(next.id);
    window.requestAnimationFrame(() => document.getElementById(`tab-${next.id}`)?.focus());
  };

  return (
    <main className="app-shell" id="top">
      <a className="skip-link" href="#results">Skip to results</a>
      <header className="site-header">
        <div className="product-bar">
          <a className="brand-lockup" href="#top" aria-label="PMGD-BESS Policy Replication Lab, home">
            <span className="brand-mark" aria-hidden="true">PB</span>
            <span>
              <strong>PMGD-BESS</strong>
              <small>Policy replication lab</small>
            </span>
          </a>
          <div className="header-actions">
            <span className="program-label">FONDEF ID26I10727</span>
            <button
              className="theme-toggle"
              type="button"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
              title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
            >
              {theme === "light" ? <Moon aria-hidden="true" size={17} /> : <Sun aria-hidden="true" size={17} />}
              <span>{theme === "light" ? "Dark" : "Light"}</span>
            </button>
          </div>
        </div>
        <div className="hero">
          <div>
            <h1>Stabilization, switching and restitution</h1>
            <p className="hero-copy">
              A reproducible LSMC laboratory for Chilean distributed PV and integrated PV+BESS.
              Compare five policy configurations to distinguish stabilization support, reversible spot access,
              Balance MEP restitution and the investor’s decision to wait.
            </p>
          </div>
          <div className="hero-aside">
            <div className="model-badge" aria-label={`Model version ${meta?.model_version ?? "loading"}`}>
              <span>Model version</span>
              <strong>{meta?.model_version ?? "Loading"}</strong>
              <small>{meta ? meta.model_sha256.slice(0, 12) : "Reproducible build"}</small>
            </div>
          </div>
        </div>
      </header>

      <details className="policy-primer">
      <summary>How the three policy dimensions differ</summary>
      <section className="thesis-strip" aria-label="Policy dimensions">
        <article><h2>Stabilization support</h2><p>The level and shape of support can accelerate renewable PMGD adoption.</p></article>
        <article><h2>Reversible market access</h2><p>Switching adds operating flexibility; it does not by itself prevent excessive deployment.</p></article>
        <article><h2>Balance MEP restitution</h2><p>Repayment removes much of the acceleration from retaining price differences.</p></article>
      </section>
      </details>

      <div className="workspace-grid">
        <aside className="control-rail" data-expanded={controlsOpen} aria-label="Scenario controls">
          <div className="control-heading">
            <div>
              <h2>Scenario</h2>
              {inputsMatchPaper ? <span className="baseline-chip">Paper inputs</span> : <span className="custom-chip">Custom inputs</span>}
            </div>
            <button className="controls-toggle button-secondary" aria-expanded={controlsOpen} aria-controls="scenario-controls" onClick={() => setControlsOpen((open) => !open)}>
              <SlidersHorizontal size={16} aria-hidden="true" />
              {controlsOpen ? "Close parameters" : "Edit parameters"}
              <ChevronDown size={16} aria-hidden="true" />
            </button>
          </div>

          <div className="control-body" id="scenario-controls">
          <div className="button-row">
            <button className="button-primary" onClick={() => void run()} disabled={loading || !meta}>
              <Play size={15} aria-hidden="true" />
              {loading ? "Running model..." : "Run model"}
            </button>
            <button className="button-secondary" onClick={reset}>Paper baseline</button>
            <button className="button-secondary" onClick={loadPriceSensitivity}>Load paper prices ×2</button>
          </div>

          <p className="card-caption">Load a preset, then select Run model. Results retain the inputs of the last completed run.</p>
          <div className="run-options">
            <label htmlFor="seed">Random seed</label>
            <input
              id="seed"
              className="number-input seed-input"
              type="number"
              min={0}
              max={1_000_000}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
            />
          </div>
          <Toggle
            checked={autoRun}
            onChange={() => setAutoRun((value) => !value)}
            label="Auto-run"
            description="Recompute 0.65 s after an input changes."
          />
          <Toggle
            checked={withSensitivity}
            onChange={() => setWithSensitivity((value) => !value)}
            label="Volatility sensitivity"
            description="Adds the σ_S = 0.25, 0.35, 0.45 grid."
          />

          <div className="parameter-groups">
            {groups.map(([group, items], index) => (
              <details key={group} open={index === 0}>
                <summary>{group}<span>{items.length}</span><ChevronDown size={15} aria-hidden="true" /></summary>
                <div className="parameter-stack">
                  {items.map((parameter) => (
                    <ParamSlider
                      key={parameter.name}
                      meta={parameter}
                      value={params[parameter.name] ?? parameter.default}
                      onChange={(value) =>
                        setParams((current) => ({ ...current, [parameter.name]: value }))
                      }
                    />
                  ))}
                </div>
              </details>
            ))}
          </div>
          </div>
        </aside>

        <section className="results-column" id="results" aria-busy={loading}>
          {result ? (
            <div className="result-context" data-pending={pendingInputs && !loading}>
              <div>
                <h2>{isPaperRun ? "Paper baseline" : "Calculated scenario"}</h2>
                <p className="result-prices"><span>Spot <strong>{Number(result.params_used.s0_spot)} USD/MWh</strong></span><span>MEP <strong>{Number(result.params_used.s0_mep)} USD/MWh</strong></span><span><strong>{Number(result.params_used.n_paths).toLocaleString("en-US")}</strong> paths</span></p>
              </div>
              <p className="result-status" role="status">{loading ? "Updating results. Showing the last completed run." : pendingInputs ? "Inputs changed. Run model to update these results." : "Results match current inputs."}</p>
            </div>
          ) : null}
          <nav className="tab-list" aria-label="Result views" role="tablist">
            {TABS.map((item) => (
              <button
                key={item.id}
                id={`tab-${item.id}`}
                role="tab"
                data-active={tab === item.id}
                aria-selected={tab === item.id}
                aria-controls={`panel-${item.id}`}
                tabIndex={tab === item.id ? 0 : -1}
                onClick={() => setTab(item.id)}
                onKeyDown={(event) => handleTabKeyDown(event, TABS.indexOf(item))}
              >
                {item.label}
              </button>
            ))}
          </nav>

          {error ? (
            <div className="error-box" role="alert">
              <strong>The model could not run.</strong>
              <p>{error}</p>
            </div>
          ) : null}

          {!result && !error ? (
            <div className="loading-box" role="status">
              <p>Running the paper baseline...</p>
              <div className="loading-skeleton" aria-hidden="true"><span /><span /><span /></div>
            </div>
          ) : null}

          {result ? (
            <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
              {tab === "regimes" ? <RegimesPanel result={result} loading={loading} /> : null}
              {tab === "deferral" ? <DeferralPanel result={result} loading={loading} /> : null}
              {tab === "switching" ? <SwitchingPanel result={result} loading={loading} /> : null}
              {tab === "sensitivity" ? (
                <SensitivityPanel
                  result={result}
                  loading={loading}
                  onEnable={() => {
                    setWithSensitivity(true);
                    setTimeout(() => void runModel(params, true, seed).then(setResult), 0);
                  }}
                />
              ) : null}
              {tab === "diagnostics" ? <DiagnosticsPanel result={result} loading={loading} /> : null}
              {tab === "replicate" && meta ? (
                <ReplicationPanel result={result} meta={meta} isPaperRun={isPaperRun} />
              ) : null}
            </div>
          ) : null}

          {result ? (
            <p className="run-footer">
              Run <code>{result.run_id}</code> / {result.runtime_s.toFixed(2)} s / seed {result.seed} / {Number(result.params_used.n_paths).toLocaleString("en-US")} paths
            </p>
          ) : null}
        </section>
      </div>

      <footer className="site-footer">
        Companion to <em>Stabilization, Switching, and Restitution: Lessons from Chile for Distributed PV-Storage Investment</em>.
        Values are model outputs, not market forecasts.
      </footer>
    </main>
  );
}

function RegimesPanel({ result, loading }: { result: ModelResult; loading: boolean }) {
  return (
    <div className={`panel-stack ${loading ? "is-loading" : ""}`}>
      <div className="comparison-heading"><h2>Compare investment decisions</h2><p>The same project and price paths, across four policy configurations. Values in million USD; investment time is conditional on investing.</p></div>
      <div className="stat-grid policy-stat-grid">
        {POLICIES.filter(({ key }) => key !== "historical_flat").flatMap(({ key, label }) =>
          (["pv", "joint"] as const).map((asset) => {
            const row = result.policy_comparison[key][asset];
            const policyLabel = key === "fixed_mep_no_restitution"
              ? "MEP-only (time-block), no restitution"
              : key === "spot_only" ? "Spot-only, no switching or restitution" : label;
            return (
              <article className="stat-tile investment-card" data-policy={key} data-asset={asset} data-tone={key === "switching_with_restitution" ? "amber" : "blue"} key={`${key}-${asset}`}>
                <div className="investment-card-heading"><span className="asset-name">{asset === "pv" ? "PV" : "PV+BESS"}</span><h3>{policyLabel}</h3></div>
                <dl>
                  <div><dt>Immediate NPV N₀</dt><dd>{row.immediate_npv_musd.toFixed(4)} M USD</dd></div>
                  <div><dt>Exclusive deferral premium</dt><dd>{row.pure_deferral_premium_musd.toFixed(4)} M USD</dd></div>
                  <div><dt>Mean investment time, if exercised</dt><dd>{years(row.mean_exercise_time)}</dd></div>
                </dl>
                <p>Investment exercised on {pct(row.exercise_rate)} of simulated paths.</p>
              </article>
            );
          })
        )}
      </div>
      <DefinitionNote>MEP-only and spot-only permit investment deferral within a fixed remuneration regime. Switching adds MEP–spot choice after investment. The exclusive deferral premium is F₀ − max(N₀, 0), using the same operating rights for immediate investment and deferral. Investment time is measured from today, conditional on investing; 0 y means immediate investment. {result.definitions.exercise_rate} Historical flat uses a separate price calibration and appears in the comparison below.</DefinitionNote>
      <section className="result-card">
        <div className="section-heading"><div><h2>Entry timing across five policy configurations</h2><p className="card-caption">Fixed regimes permit investment deferral only. Switching configurations add operating regime choice. Mean time is conditional on exercise.</p></div><span>{Number(result.params_used.n_paths).toLocaleString("en-US")} paths</span></div>
        <div className="chart-grid-two"><RegimeChart data={result.policy_comparison} metric="exercise_rate" /><RegimeChart data={result.policy_comparison} metric="mean_exercise_time" /></div>
        <div className="table-scroll"><table className="policy-table"><caption>Controlled investment comparison; historical flat is separately calibrated</caption><thead><tr><th>Policy configuration</th><th>Asset</th><th>Option value (M USD)</th><th>Exercise rate</th><th>Mean time if exercised</th></tr></thead><tbody>
          {POLICIES.flatMap(({key,label}) => (["pv","joint"] as AssetKey[]).map((asset) => { const row=result.policy_comparison[key][asset]; return <tr key={`${key}-${asset}`}><th scope="row">{label}</th><td>{asset === "pv" ? "PV" : "PV+BESS"}</td><td>{row.option_value_musd.toFixed(4)}</td><td>{pct(row.exercise_rate)}</td><td>{years(row.mean_exercise_time)}</td></tr>; }))}
        </tbody></table></div>
      </section>
      <section className="interpretation-grid">
        <article><h3>Calibrate support and access</h3><p>Time-block support with reversible spot access is a candidate for emerging PMGD markets seeking greater renewable penetration. Transfer budgets and connection safeguards remain necessary.</p></article>
        <article><h3>Review support as needs change</h3><p>Restitution can moderate support where congestion, curtailment or transfer costs justify it, while useful storage and other services may still require remuneration.</p></article>
        <article><h3>Adapt policies to local evidence</h3><p>The contribution separates support, market access and repayment. It does not estimate an optimal deployment trajectory or establish a universal policy ranking.</p></article>
      </section>
    </div>
  );
}

function DeferralPanel({ result, loading }: { result: ModelResult; loading: boolean }) {
  return <div className={`panel-stack ${loading ? "is-loading" : ""}`}>
    <DefinitionNote>{result.definitions.pure_deferral_premium} {result.definitions.forced_immediate_gap}</DefinitionNote>
    <section className="result-card"><div className="section-heading"><div><h2>Invest immediately or retain the option to wait</h2><p className="card-caption">N₀: immediate expected NPV. F₀: compound investment-option value. Πwait = F₀ − max(N₀, 0). Each immediate benchmark retains the same operating rights as its deferral option.</p></div><span>M USD</span></div>
      <RegimeChart data={result.policy_comparison} metric="pure_deferral_premium_musd" />
      <div className="table-scroll"><table className="policy-table"><caption>Immediate investment and exclusive waiting premium; spot {Number(result.params_used.s0_spot)} USD/MWh, MEP {Number(result.params_used.s0_mep)} USD/MWh</caption><thead><tr><th>Configuration</th><th>Asset</th><th>N₀</th><th>F₀</th><th>Πwait</th><th>F₀ − N₀</th><th>Avoided negative NPV</th><th>Exercise</th><th>Mean time if exercised</th></tr></thead><tbody>
        {POLICIES.flatMap(({key,label}) => (["pv","joint"] as AssetKey[]).map((asset) => { const row=result.policy_comparison[key][asset]; return <tr key={`${key}-${asset}`}><th scope="row">{label}</th><td>{asset === "pv" ? "PV" : "PV+BESS"}</td><td>{row.immediate_npv_musd.toFixed(4)}</td><td>{row.option_value_musd.toFixed(4)}</td><td>{row.pure_deferral_premium_musd.toFixed(4)}</td><td>{row.gain_vs_forced_immediate_musd.toFixed(4)}</td><td>{row.avoided_negative_npv_musd.toFixed(4)}</td><td>{pct(row.exercise_rate)}</td><td>{years(row.mean_exercise_time)}</td></tr>; }))}
      </tbody></table></div>
    </section>
    <section className="scope-card"><h2>The positive-NPV timing comparison</h2><p>Load paper prices ×2 and run the model to reproduce the sensitivity with spot at 50 and MEP at 90 USD/MWh. At the paper calibration, fixed MEP and switching without restitution invest immediately, while spot only and switching with restitution retain positive waiting premiums despite positive immediate NPV.</p><p>Spot uncertainty already creates an incentive to wait. Restitution mainly removes the acceleration from support without repayment; it does not create all deferral or produce greater delay than spot in this sensitivity. Base-case fixed MEP does not imply immediate exercise on every path.</p></section>
  </div>;
}

function SwitchingPanel({ result, loading }: { result: ModelResult; loading: boolean }) {
  const joint = result.switching.joint;
  return (
    <div className={`panel-stack ${loading ? "is-loading" : ""}`}>
      <div className="stat-grid">
        <StatTile label="Integrated PV+BESS switching premium" value={musd(joint.premium_new_musd)} detail="net of restitution, versus best fixed remuneration" />
        <StatTile label="Integrated PV+BESS permanence gain" value={musd(joint.reform_gain_musd)} detail="1-year vs 4-year permanence" tone="amber" />
        <StatTile label="Terminal spot share" value={pct(joint.migration.new_share_spot_terminal)} detail="simulated optimal policy paths" tone="ink" />
        <StatTile label="Mean switches per path" value={joint.migration.new_mean_switches.toFixed(2)} detail="under 2026 switching (1-year permanence)" />
      </div>
      <section className="result-card">
        <div className="section-heading">
          <div>
            <h2>Operating value of remuneration flexibility</h2>
            <p className="card-caption">
              Net operating values for the PV energy stream, BESS energy stream and integrated PV+BESS. Four-year and one-year permanence use the same full Balance MEP repayment schedule.
            </p>
          </div>
          <span>M USD</span>
        </div>
        <SwitchingValueChart data={result.switching} />
        <SwitchingTable data={result.switching} />
      </section>
      <section className="result-card">
        <div className="section-heading">
          <div>
            <h2>Controlled permanence comparison</h2>
            <p className="card-caption">
              Investment-option results with four-year versus one-year permanence, holding the same restitution schedule fixed. This isolates permanence flexibility rather than reconstructing the entire former regulation.
            </p>
          </div>
        </div>
        <InvestmentTable data={result.switching} />
      </section>
      <section className="result-card"><h2>Balance MEP settlement ledger</h2><p>{result.definitions.balance_mep}</p><div className="table-scroll"><table><caption>Discounted gross receipts, repayment and terminal liability runoff (M USD)</caption><thead><tr><th>Asset</th><th>Gross value</th><th>Repayment value</th><th>Net value</th><th>Repayment after horizon</th></tr></thead><tbody>{ASSETS.map(({key,label}) => {const row=result.switching[key]; const ledger=row.settlement; return <tr key={key}><th scope="row">{label}</th><td>{(ledger.mean_gross_operating_pv_usd/1e6).toFixed(4)}</td><td>{(ledger.mean_repayments_pv_usd/1e6).toFixed(4)}</td><td>{row.switch_new_musd.toFixed(4)}</td><td>{(ledger.mean_tail_repayment_pv_usd/1e6).toFixed(4)}</td></tr>;})}</tbody></table></div></section>
      <DefinitionNote>
        {result.definitions.premium_new} {result.definitions.reform_gain} Terminal spot shares are transition diagnostics, not forecasts of a fully spot market.
      </DefinitionNote>
    </div>
  );
}

function SwitchingTable({ data }: { data: ModelResult["switching"] }) {
  return (
    <div className="table-scroll"><table><caption>Exact operating values and migration diagnostics</caption><thead><tr><th>Asset</th><th>{SWITCHING_SERIES.spotOnly}</th><th>{SWITCHING_SERIES.stabilizedOnly}</th><th>Four-year permanence</th><th>One-year permanence</th><th>Switching premium</th><th>Permanence gain</th><th>Spot share at T</th><th>Switches/path</th></tr></thead><tbody>
      {ASSETS.map(({ key, label }) => { const row = data[key]; return <tr key={key}><th scope="row">{label}</th><td>{row.spot_only_musd.toFixed(4)}</td><td>{row.mep_only_musd.toFixed(4)}</td><td>{row.switch_old_musd.toFixed(4)}</td><td>{row.switch_new_musd.toFixed(4)}</td><td>{row.premium_new_musd.toFixed(4)}</td><td>{row.reform_gain_musd.toFixed(4)}</td><td>{pct(row.migration.new_share_spot_terminal)}</td><td>{row.migration.new_mean_switches.toFixed(3)}</td></tr>; })}
    </tbody></table></div>
  );
}

function InvestmentTable({ data }: { data: ModelResult["switching"] }) {
  return (
    <div className="table-scroll"><table><caption>Compound investment-option results for assets with an investment layer</caption><thead><tr><th>Asset</th><th>Four-year-rule value (M USD)</th><th>Four-year-rule exercise</th><th>Four-year-rule timing</th><th>One-year value (M USD)</th><th>One-year exercise</th><th>One-year timing</th></tr></thead><tbody>
      {(["pv", "joint"] as SwitchingAssetKey[]).map((key) => { const row = data[key].investment; if (!row) return null; return <tr key={key}><th scope="row">{key === "pv" ? "PV" : "Integrated PV+BESS"}</th><td>{row.old_option_value_musd.toFixed(4)}</td><td>{pct(row.old_exercise_rate)}</td><td>{years(row.old_mean_exercise_time)}</td><td>{row.new_option_value_musd.toFixed(4)}</td><td>{pct(row.new_exercise_rate)}</td><td>{years(row.new_mean_exercise_time)}</td></tr>; })}
    </tbody></table></div>
  );
}

function SensitivityPanel({ result, loading, onEnable }: { result: ModelResult; loading: boolean; onEnable: () => void }) {
  if (result.sensitivity.length === 0) {
    return <div className="empty-card"><h2>Sensitivity grid was skipped</h2><p>Enable the three-point spot-volatility sweep to reproduce the paper volatility sensitivity.</p><button className="button-primary" onClick={onEnable}>Run sensitivity</button></div>;
  }
  return (
    <div className={`panel-stack ${loading ? "is-loading" : ""}`}>
      <section className="result-card">
        <div className="section-heading">
          <div>
            <h2>Value of flexibility rises with spot-price volatility</h2>
            <p className="card-caption">
              <strong>Spot-volatility sensitivity.</strong> Sensitivity of the switching premium and the incremental value of shortening minimum permanence from four years to one year across spot-price volatility calibrations (σ_S ∈ {`{0.25, 0.35, 0.45}`}). Values are measured relative to the better fixed operating regime.
            </p>
          </div>
          <span>σ_S ∈ {`{0.25, 0.35, 0.45}`}</span>
        </div>
        <SensitivityCharts rows={result.sensitivity} />
        <div className="table-scroll"><table><caption>Exact volatility-sensitivity values</caption><thead><tr><th>Spot-price volatility</th><th>Asset</th><th>Switching premium (M USD)</th><th>Permanence gain (M USD)</th></tr></thead><tbody>
          {result.sensitivity.map((row) => <tr key={`${row.sigma_spot}-${row.asset}`}><th scope="row">{row.sigma_spot.toFixed(2)}</th><td>{ASSETS.find((asset) => asset.key === row.asset)?.label}</td><td>{row.premium_new_musd.toFixed(4)}</td><td>{row.reform_gain_musd.toFixed(4)}</td></tr>)}
        </tbody></table></div>
      </section>
      <DefinitionNote>Volatility changes option value in this calibration. It does not identify a causal policy effect because price levels, market design, and other state processes remain model assumptions.</DefinitionNote>
    </div>
  );
}

function DiagnosticsPanel({ result, loading }: { result: ModelResult; loading: boolean }) {
  const [asset, setAsset] = useState<AssetKey>("pv");
  const [distributionKind, setDistributionKind] = useState<"option" | "npv">("option");
  const distributions = distributionKind === "option"
    ? result.diagnostics.distributions
    : result.diagnostics.npv_distributions;
  const riskField = distributionKind === "option" ? "zero_mass" : "negative_mass";
  const spotRisk = distributions.spot_only[asset][riskField];
  const dualRisk = distributions.dual_switching[asset][riskField];
  const assetLabel = asset === "pv" ? "PV" : "Integrated PV+BESS";

  return (
    <div className={`panel-stack ${loading ? "is-loading" : ""}`}>
      <div className="stat-grid">
        <StatTile label={`${assetLabel} / flat-price stabilization mean`} value={musd(distributions.flat_stabilization[asset].mean)} detail={distributionKind === "option" ? "compound investment-option value" : "immediate-investment NPV"} tone="amber" />
        <StatTile label={`${assetLabel} / spot-only risk mass`} value={pct(spotRisk)} detail={distributionKind === "option" ? "paths that never exercise" : "paths with realized NPV below zero"} tone="ink" />
        <StatTile label={`${assetLabel} / dual-remuneration risk mass`} value={pct(dualRisk)} detail={distributionKind === "option" ? "paths that never exercise" : "paths with realized NPV below zero"} />
        <StatTile label="Dual-remuneration reduction vs spot-only" value={`${(100 * (spotRisk - dualRisk)).toFixed(1)} pp`} detail="difference in the displayed risk mass" />
      </div>

      <section className="result-card">
        <div className="section-heading">
          <div>
            <h2>Pathwise investment distributions</h2>
            <p className="card-caption">
              <strong>Distribution diagnostics.</strong> Empirical PDF and CDF distributions of compound investment-option value and immediate-investment NPV. PDF panels use histograms for non-degenerate distributions and vertical markers for deterministic atoms; legends report mass at zero or realized negative NPV share. Displayed over the pooled 1st–99th percentile range.
            </p>
          </div>
          <span>pooled P1-P99 view</span>
        </div>
        <div className="diagnostic-toolbar" aria-label="Distribution controls">
          <div className="segmented-control" aria-label="Distribution measure">
            <button data-active={distributionKind === "option"} onClick={() => setDistributionKind("option")}>Option value</button>
            <button data-active={distributionKind === "npv"} onClick={() => setDistributionKind("npv")}>Immediate NPV</button>
          </div>
          <div className="segmented-control" aria-label="Asset">
            <button data-active={asset === "pv"} onClick={() => setAsset("pv")}>PV</button>
            <button data-active={asset === "joint"} onClick={() => setAsset("joint")}>Integrated PV+BESS</button>
          </div>
        </div>
        <DistributionCharts data={distributions} asset={asset} kind={distributionKind} />
        <DistributionTable data={distributions} asset={asset} kind={distributionKind} />
      </section>

      <DefinitionNote>
        {distributionKind === "option" ? result.definitions.option_distribution : result.definitions.npv_distribution}
        {" "}The chart window is restricted to the pooled 1st-99th percentile range; the summary statistics use all paths.
      </DefinitionNote>

      <section className="result-card">
        <div className="section-heading">
          <div>
            <h2>Exercise payoff versus continuation value</h2>
            <p className="card-caption">
              <strong>Continuation diagnostics.</strong> Year-{result.diagnostics.year} LSMC exercise-payoff and fitted continuation-value diagnostics. Points are conditional means within 15 quantile bins of the primary price state and include only in-the-money paths used by the regression.
            </p>
          </div>
          <span>{assetLabel} / ITM paths only</span>
        </div>
        <ContinuationCharts data={result.diagnostics.continuation} asset={asset} year={result.diagnostics.year} />
        <ContinuationTable data={result.diagnostics.continuation} asset={asset} year={result.diagnostics.year} />
      </section>
      <DefinitionNote>{result.definitions.continuation_diagnostic}</DefinitionNote>
    </div>
  );
}

function DistributionTable({
  data,
  asset,
  kind,
}: {
  data: ModelResult["diagnostics"]["distributions"];
  asset: AssetKey;
  kind: "option" | "npv";
}) {
  return (
    <div className="table-scroll">
      <table>
        <caption>Exact full-sample distribution statistics for the selected asset</caption>
        <thead><tr><th>Architecture</th><th>Mean</th><th>Median</th><th>P5</th><th>P95</th><th>{kind === "option" ? "Mass at zero" : "NPV below zero"}</th></tr></thead>
        <tbody>
          {REGIMES.map(({ key, label }) => {
            const row = data[key][asset];
            return <tr key={key}><th scope="row">{label}</th><td>{row.mean.toFixed(4)}</td><td>{row.median.toFixed(4)}</td><td>{row.p05.toFixed(4)}</td><td>{row.p95.toFixed(4)}</td><td>{pct(kind === "option" ? row.zero_mass : row.negative_mass)}</td></tr>;
          })}
        </tbody>
      </table>
    </div>
  );
}

function ContinuationTable({
  data,
  asset,
  year,
}: {
  data: ModelResult["diagnostics"]["continuation"];
  asset: AssetKey;
  year: number;
}) {
  return (
    <details className="audit-details diagnostic-details">
      <summary>Exact year-{year} continuation bins</summary>
      <div className="table-scroll">
        <table>
          <caption>Conditional means by quantile bin of the primary price state</caption>
          <thead><tr><th>Architecture</th><th>State (USD/MWh)</th><th>Exercise payoff (M USD)</th><th>Continuation value (M USD)</th><th>Exercise share in bin</th></tr></thead>
          <tbody>
            {REGIMES.flatMap(({ key, label }) => data[key][asset].state.map((state, index) => (
              <tr key={`${key}-${index}`}><th scope="row">{label}</th><td>{state.toFixed(3)}</td><td>{data[key][asset].exercise_payoff[index].toFixed(4)}</td><td>{data[key][asset].continuation_value[index].toFixed(4)}</td><td>{pct(data[key][asset].exercise_share[index])}</td></tr>
            )))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function ReplicationPanel({ result, meta, isPaperRun }: { result: ModelResult; meta: Meta; isPaperRun: boolean }) {
  const json = JSON.stringify(result, null, 2);
  return (
    <div className="panel-stack">
      <div className="stat-grid">
        <StatTile label="Run status" value={isPaperRun ? "Baseline" : "Custom"} detail={isPaperRun ? "matches displayed paper inputs" : "export records all overrides"} tone={isPaperRun ? "blue" : "amber"} />
        <StatTile label="Seed" value={String(result.seed)} detail={`${Number(result.params_used.n_paths).toLocaleString("en-US")} Monte Carlo paths`} tone="ink" />
        <StatTile label="Runtime" value={`${result.runtime_s.toFixed(2)} s`} detail={`run ${result.run_id}`} />
        <StatTile label="Model checksum" value={result.model_sha256.slice(0, 10)} detail={result.model_version} tone="ink" />
      </div>
      <section className="result-card repro-card">
        <div className="section-heading"><div><h2>App glossary and nomenclature</h2><p className="card-caption">Definitions used in the controls, charts, result cards and exports. Expand a group to consult its terms.</p></div></div>
        {GLOSSARY.map(({ title, entries }, index) => (
          <details className="glossary-group" key={title} open={index === 0}>
            <summary>{title}<span>{entries.length} terms</span><ChevronDown size={16} aria-hidden="true" /></summary>
            <dl className="glossary-list">{entries.map(([term, definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl>
          </details>
        ))}
      </section>
      <section className="result-card repro-card">
        <div className="section-heading">
          <div>
            <h2>Trace every displayed number to the paper code</h2>
            <p className="card-caption">
              Replication Protocol. Execute the exact one-command test suite to verify model parity against the current manuscript results.
            </p>
          </div>
        </div>
        <div className="command-row"><code>{meta.replication.command}</code></div>
        <div className="button-row export-row">
          <button className="button-secondary" onClick={() => downloadBlob(`pmgd-bess-${result.run_id}.json`, json, "application/json")}>Download run JSON</button>
          <button className="button-secondary" onClick={() => downloadBlob(`pmgd-bess-${result.run_id}.csv`, resultCsv(result), "text/csv")}>Download results CSV</button>
        </div>
        <div className="table-scroll"><table><caption>Manuscript-to-code map</caption><thead><tr><th>Paper artifact</th><th>Code/output</th><th>What it reproduces</th></tr></thead><tbody>
          <tr><th scope="row">Five policy configurations</th><td><code>restitution_comparison()</code></td><td>Common-path entry, timing, immediate NPV and exclusive waiting premiums; historical flat is separate</td></tr>
          <tr><th scope="row">Operating and settlement values</th><td><code>run_all()</code></td><td>Net operating values, signed annual balances, twelve monthly installments and liability runoff</td></tr>
          <tr><th scope="row">Price sensitivity</th><td><code>s0_spot=50, s0_mep=90</code></td><td>Positive-NPV timing comparison using the same scientific model</td></tr>
          <tr><th scope="row">Distributions and continuation</th><td><code>run_all(collect_diagnostics=True)</code></td><td>Historical flat, spot only and selected settled switching policy; diagnostics are fitted in sample</td></tr>
          <tr><th scope="row">Volatility sensitivity</th><td><code>sensitivity()</code></td><td>Net switching premiums and permanence gains under full restitution</td></tr>
          <tr><th scope="row">Supplement</th><td><code>supplementary_material_v8.tex</code></td><td>Algorithm, calibration, definitions and robustness interpretation</td></tr>
        </tbody></table></div>
        <details className="audit-details"><summary>Parameters used in this run</summary><pre>{JSON.stringify(result.params_used, null, 2)}</pre></details>
        <details className="audit-details"><summary>Full SHA-256 model fingerprint</summary><code>{result.model_sha256}</code></details>
      </section>
      <section className="scope-card">
        <div className="section-heading">
          <div>
            <h2>What this app does not establish</h2>
            <p className="card-caption">
              Scope boundaries and model assumptions per manuscript methodology.
            </p>
          </div>
        </div>
        <ul>{result.scope.map((item) => <li key={item}>{item}</li>)}</ul>
      </section>
    </div>
  );
}
