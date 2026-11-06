"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  AssetKey,
  DistributionDiagnostic,
  ModelResult,
  RegimeKey,
  SensitivityRow,
} from "@/lib/api";
import { ASSETS, REGIMES, POLICIES, SWITCHING_SERIES } from "@/lib/terminology";

const COLORS = {
  pv: "#d97706",
  joint: "#2278b5",
  bess: "#6d28d9",
  spot: "#738197",
  mep: "#94a3b8",
  old: "#d97706",
  newer: "#2278b5",
};
const GRID = "var(--chart-grid)";
const INK = "var(--chart-ink)";
const TOOLTIP = {
  backgroundColor: "var(--chart-tooltip-bg)",
  border: "1px solid var(--chart-tooltip-border)",
  borderRadius: 6,
  color: "var(--ink)",
  fontSize: 12,
};
const LEGEND = { fontSize: 12, color: "var(--ink-soft)" };
const legendLabel = (label: React.ReactNode) => <span style={{ color: INK }}>{label}</span>;
const AXIS = {
  stroke: INK,
  fontSize: 12,
  tickLine: false as const,
  axisLine: { stroke: GRID },
};

const REGIME_LINES: Record<RegimeKey, { color: string; dash?: string }> = {
  flat_stabilization: { color: "#d97706" },
  spot_only: { color: "#738197", dash: "8 5" },
  dual_switching: { color: "#2278b5", dash: "10 4 2 4" },
};

export function RegimeChart({ data, metric }: {
  data: ModelResult["policy_comparison"];
  metric: "exercise_rate" | "mean_exercise_time" | "option_value_musd" | "pure_deferral_premium_musd";
}) {
  const rows = POLICIES.map(({ key, shortLabel }) => ({
    label: shortLabel,
    PV: metric === "exercise_rate" ? data[key].pv[metric] * 100 : data[key].pv[metric],
    "Integrated PV+BESS": metric === "exercise_rate" ? data[key].joint[metric] * 100 : data[key].joint[metric],
  }));
  const label = {
    exercise_rate: "Exercise rate (%)",
    mean_exercise_time: "Mean time if exercised (years)",
    option_value_musd: "Investment-option value (M USD)",
    pure_deferral_premium_musd: "Exclusive waiting premium (M USD)",
  }[metric];
  return (
    <div className="chart-frame" role="img" aria-label={`${label} across five policy configurations`}>
      <ResponsiveContainer width="100%" height={350}>
        <BarChart layout="vertical" data={rows} margin={{ top: 12, right: 18, left: 0, bottom: 22 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 4" horizontal={false} />
          <YAxis dataKey="label" type="category" {...AXIS} width={145} interval={0} />
          <XAxis type="number" {...AXIS} domain={metric === "exercise_rate" ? [0, 100] : [0, "auto"]}
            label={{ value: label, position: "insideBottom", offset: -15, fill: INK, fontSize: 10 }} />
          <Tooltip contentStyle={TOOLTIP} formatter={(value) => [value == null ? "Not exercised" : `${Number(value).toFixed(3)}${metric === "exercise_rate" ? "%" : metric === "mean_exercise_time" ? " years" : " M USD"}`]} />
          <Legend wrapperStyle={LEGEND} formatter={legendLabel} />
          <Bar dataKey="PV" fill={COLORS.pv} radius={[0, 4, 4, 0]} />
          <Bar dataKey="Integrated PV+BESS" fill={COLORS.joint} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function normalizedPoints(
  xs: number[],
  ys: number[],
  cumulative: boolean,
) {
  const merged = new Map<number, number[]>();
  xs.forEach((x, index) => merged.set(x, [...(merged.get(x) ?? []), ys[index]]));
  return [...merged.entries()]
    .sort(([a], [b]) => a - b)
    .map(([x, values]) => ({
      x,
      y: cumulative
        ? Math.max(...values)
        : values.reduce((sum, value) => sum + value, 0) / values.length,
    }));
}

function interpolate(
  points: { x: number; y: number }[],
  x: number,
  cumulative: boolean,
) {
  if (points.length === 0) return null;
  if (x < points[0].x) return 0;
  if (x > points[points.length - 1].x) return cumulative ? 1 : 0;
  let high = points.findIndex((point) => point.x >= x);
  if (high <= 0) return points[0].y;
  const low = high - 1;
  const span = points[high].x - points[low].x;
  if (span === 0) return points[high].y;
  const weight = (x - points[low].x) / span;
  return points[low].y + weight * (points[high].y - points[low].y);
}

function distributionRows(
  data: Record<RegimeKey, Record<AssetKey, DistributionDiagnostic>>,
  asset: AssetKey,
  metric: "pdf" | "cdf",
) {
  const min = Math.min(...REGIMES.map(({ key }) => data[key][asset].p01));
  const max = Math.max(...REGIMES.map(({ key }) => data[key][asset].p99));
  const span = Math.max(max - min, 1e-6);
  const lower = min < 0 ? min - span * 0.04 : 0;
  const upper = max + span * 0.04;
  const series = Object.fromEntries(
    REGIMES.map(({ key }) => {
      const dist = data[key][asset];
      const atom = Math.abs(dist.p99 - dist.p01) < 1e-10;
      return [
        key,
        {
          atom,
          mean: dist.mean,
          points: normalizedPoints(dist[`${metric}_x`], dist[`${metric}_y`], metric === "cdf"),
        },
      ];
    }),
  ) as Record<RegimeKey, { atom: boolean; mean: number; points: { x: number; y: number }[] }>;
  const rows = Array.from({ length: 141 }, (_, index) => {
    const x = lower + (span * 1.08 * index) / 140;
    const row: Record<string, number | null> = { x };
    for (const { key } of REGIMES) {
      row[key] = series[key].atom
        ? null
        : interpolate(series[key].points, x, metric === "cdf");
    }
    return row;
  });
  return { rows, lower, upper, series };
}

export function DistributionCharts({
  data,
  asset,
  kind,
}: {
  data: Record<RegimeKey, Record<AssetKey, DistributionDiagnostic>>;
  asset: AssetKey;
  kind: "option" | "npv";
}) {
  const panels = (["pdf", "cdf"] as const).map((metric) => ({
    metric,
    title: metric === "pdf" ? "Probability density (PDF)" : "Cumulative distribution (CDF)",
    yLabel: metric === "pdf" ? "Empirical density" : "Cumulative probability",
    ...distributionRows(data, asset, metric),
  }));
  const xLabel = kind === "option" ? "Option value (M USD)" : "Immediate NPV (M USD)";
  return (
    <>
      <div className="chart-legend" aria-label="Remuneration architecture legend">
        {REGIMES.map(({ key, label }) => (
          <span key={key}><i style={{ background: REGIME_LINES[key].color }} />{label}</span>
        ))}
      </div>
      <div className="chart-grid-two">
        {panels.map((panel) => (
          <div className="chart-frame" key={panel.metric} role="img" aria-label={`${panel.title} for ${asset === "pv" ? "PV" : "integrated PV plus BESS"}`}>
            <h3>{panel.title}</h3>
            <ResponsiveContainer width="100%" height={285}>
              <LineChart data={panel.rows} margin={{ top: 8, right: 16, left: 2, bottom: 12 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 4" vertical={false} />
                <XAxis dataKey="x" type="number" domain={[panel.lower, panel.upper]} {...AXIS} tickFormatter={(value) => Number(value).toFixed(1)} label={{ value: xLabel, position: "insideBottom", offset: -7, fill: INK, fontSize: 10 }} />
                <YAxis {...AXIS} width={50} domain={panel.metric === "cdf" ? [0, 1] : [0, "auto"]} label={{ value: panel.yLabel, angle: -90, position: "insideLeft", fill: INK, fontSize: 10 }} />
                <Tooltip contentStyle={TOOLTIP} labelFormatter={(value) => `${xLabel}: ${Number(value).toFixed(3)}`} formatter={(value, name) => [Number(value).toFixed(3), REGIMES.find(({ key }) => key === name)?.label ?? name]} />
                {kind === "npv" ? <ReferenceLine x={0} stroke={INK} strokeDasharray="2 3" /> : null}
                {REGIMES.map(({ key }) => panel.series[key].atom ? (
                  <ReferenceLine key={`${key}-atom`} x={panel.series[key].mean} stroke={REGIME_LINES[key].color} strokeWidth={2.5} strokeDasharray={REGIME_LINES[key].dash} />
                ) : (
                  <Line key={key} dataKey={key} stroke={REGIME_LINES[key].color} strokeWidth={2.5} strokeDasharray={REGIME_LINES[key].dash} dot={false} type="linear" connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    </>
  );
}

export function ContinuationCharts({
  data,
  asset,
  year,
}: {
  data: ModelResult["diagnostics"]["continuation"];
  asset: AssetKey;
  year: number;
}) {
  return (
    <>
      <div className="chart-legend" aria-label="Continuation value legend">
        <span><i style={{ background: "#d97706" }} />Exercise payoff</span>
        <span><i style={{ background: "#2278b5" }} />Continuation value</span>
      </div>
      <div className="chart-grid-three">
        {REGIMES.map(({ key, label }) => {
          const diagnostic = data[key][asset];
          const rows = diagnostic.state.map((state, index) => ({
            state,
            exercise: diagnostic.exercise_payoff[index],
            continuation: diagnostic.continuation_value[index],
          }));
          return (
            <div className="chart-frame" key={key} role="img" aria-label={`Year ${year} exercise and continuation values under ${label}`}>
              <h3>{label} / {diagnostic.n_itm.toLocaleString("en-US")} ITM paths</h3>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={rows} margin={{ top: 8, right: 14, left: 0, bottom: 12 }}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 4" vertical={false} />
                  <XAxis dataKey="state" type="number" domain={["dataMin", "dataMax"]} {...AXIS} label={{ value: key === "flat_stabilization" ? "Flat-price stabilization (USD/MWh)" : "Generation-weighted spot price (USD/MWh)", position: "insideBottom", offset: -7, fill: INK, fontSize: 10 }} />
                  <YAxis {...AXIS} width={48} label={{ value: "Conditional value (M USD)", angle: -90, position: "insideLeft", fill: INK, fontSize: 10 }} />
                  <Tooltip contentStyle={TOOLTIP} labelFormatter={(value) => `Price state: ${Number(value).toFixed(2)} USD/MWh`} formatter={(value, name) => [`${Number(value).toFixed(3)} M USD`, name === "exercise" ? "Exercise payoff" : "Continuation value"]} />
                  <Line dataKey="exercise" stroke="#d97706" strokeWidth={2.4} dot={{ r: 3 }} />
                  <Line dataKey="continuation" stroke="#2278b5" strokeWidth={2.4} strokeDasharray="7 4" dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function SwitchingValueChart({ data }: { data: ModelResult["switching"] }) {
  const rows = ASSETS.map(({ key, label }) => ({
    label,
    [SWITCHING_SERIES.spotOnly]: data[key].spot_only_musd,
    [SWITCHING_SERIES.stabilizedOnly]: data[key].mep_only_musd,
    [SWITCHING_SERIES.formerRule]: data[key].switch_old_musd,
    [SWITCHING_SERIES.reform2026]: data[key].switch_new_musd,
  }));
  return (
    <div className="chart-frame" role="img" aria-label="Operating values by asset and remuneration option">
      <ResponsiveContainer width="100%" height={330}>
        <BarChart data={rows} margin={{ top: 12, right: 12, left: 0, bottom: 10 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 4" vertical={false} />
          <XAxis dataKey="label" {...AXIS} />
          <YAxis
            {...AXIS}
            width={48}
            label={{ value: "Operating value (M USD)", angle: -90, position: "insideLeft", fill: INK, fontSize: 10 }}
          />
          <Tooltip
            contentStyle={TOOLTIP}
            formatter={(value) => [`${Number(value).toFixed(3)} M USD`]}
          />
          <Legend wrapperStyle={LEGEND} formatter={legendLabel} />
          <Bar dataKey={SWITCHING_SERIES.spotOnly} fill={COLORS.spot} radius={[3, 3, 0, 0]} />
          <Bar dataKey={SWITCHING_SERIES.stabilizedOnly} fill={COLORS.mep} radius={[3, 3, 0, 0]} />
          <Bar dataKey={SWITCHING_SERIES.formerRule} fill={COLORS.old} radius={[3, 3, 0, 0]} />
          <Bar dataKey={SWITCHING_SERIES.reform2026} fill={COLORS.newer} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function sensitivityData(rows: SensitivityRow[]) {
  const sigmas = [...new Set(rows.map((row) => row.sigma_spot))].sort((a, b) => a - b);
  return sigmas.map((sigma) => {
    const sameSigma = rows.filter((row) => row.sigma_spot === sigma);
    const output: Record<string, number> = { sigma };
    for (const row of sameSigma) {
      output[`${row.asset}_premium`] = row.premium_new_musd;
      output[`${row.asset}_gain`] = row.reform_gain_musd;
    }
    return output;
  });
}

export function SensitivityCharts({ rows }: { rows: SensitivityRow[] }) {
  const data = sensitivityData(rows);
  const panels = [
    { suffix: "premium", title: "Switching premium", yLabel: "Premium (M USD)" },
    { suffix: "gain", title: "Permanence gain", yLabel: "Permanence gain (M USD)" },
  ];
  return (
    <div className="chart-grid-two">
      {panels.map((panel) => (
        <div className="chart-frame" key={panel.suffix} role="img" aria-label={`${panel.title} by spot-price volatility`}>
          <h3>{panel.title}</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data} margin={{ top: 8, right: 14, left: 0, bottom: 8 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 4" vertical={false} />
              <XAxis
                dataKey="sigma"
                {...AXIS}
                label={{ value: "Spot-price volatility σ_S", position: "insideBottom", offset: -4, fill: INK, fontSize: 10 }}
              />
              <YAxis
                {...AXIS}
                width={48}
                label={{ value: panel.yLabel, angle: -90, position: "insideLeft", fill: INK, fontSize: 10 }}
              />
              <Tooltip
                contentStyle={TOOLTIP}
                formatter={(value) => [`${Number(value).toFixed(3)} M USD`]}
                labelFormatter={(value) => `σ_S = ${Number(value).toFixed(2)}`}
              />
              <Legend wrapperStyle={LEGEND} formatter={legendLabel} />
              <Line
                name="PV"
                dataKey={`pv_${panel.suffix}`}
                stroke={COLORS.pv}
                strokeWidth={2.5}
                dot={{ r: 4 }}
              />
              <Line
                name="BESS energy stream"
                dataKey={`bess_energy_${panel.suffix}`}
                stroke={COLORS.bess}
                strokeWidth={2.5}
                strokeDasharray="5 4"
                dot={{ r: 4 }}
              />
              <Line
                name="Integrated PV+BESS"
                dataKey={`joint_${panel.suffix}`}
                stroke={COLORS.joint}
                strokeWidth={2.5}
                strokeDasharray="2 3"
                dot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ))}
    </div>
  );
}
