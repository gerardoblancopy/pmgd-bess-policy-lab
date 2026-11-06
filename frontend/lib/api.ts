export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8811";

export interface ParamMeta {
  group: string;
  name: string;
  label: string;
  unit: string;
  step: number;
  min: number;
  max: number;
  default: number;
}

export type RegimeKey =
  | "flat_stabilization"
  | "spot_only"
  | "dual_switching";
export type PolicyKey =
  | "historical_flat"
  | "spot_only"
  | "fixed_mep_no_restitution"
  | "switching_no_restitution"
  | "switching_with_restitution";

export interface PolicyMetric extends RegimeMetric {
  immediate_npv_musd: number;
  immediate_decision_value_musd: number;
  pure_deferral_premium_musd: number;
  gain_vs_forced_immediate_musd: number;
  avoided_negative_npv_musd: number;
}

export interface Settlement {
  enabled: boolean;
  discount_factor: number;
  mean_annual_accrual_usd: number[];
  mean_annual_repayment_usd: number[];
  mean_gross_operating_pv_usd: number;
  mean_repayments_pv_usd: number;
  mean_final_year_accrual_usd: number;
  mean_tail_repayment_pv_usd: number;
  max_accounting_error_usd: number;
}

export type AssetKey = "pv" | "joint";
export type SwitchingAssetKey = "pv" | "bess_energy" | "joint";

export interface RegimeMetric {
  option_value_musd: number;
  exercise_rate: number;
  mean_exercise_time: number | null;
}

export interface SwitchingAsset {
  settlement: Settlement;
  spot_only_musd: number;
  mep_only_musd: number;
  switch_old_musd: number;
  switch_new_musd: number;
  premium_new_musd: number;
  reform_gain_musd: number;
  migration: {
    old_share_spot_terminal: number;
    new_share_spot_terminal: number;
    old_mean_switches: number;
    new_mean_switches: number;
  };
  investment: null | {
    old_option_value_musd: number;
    old_exercise_rate: number;
    old_mean_exercise_time: number | null;
    new_option_value_musd: number;
    new_exercise_rate: number;
    new_mean_exercise_time: number | null;
  };
}

export interface SensitivityRow {
  sigma_spot: number;
  asset: SwitchingAssetKey;
  premium_new_musd: number;
  reform_gain_musd: number;
}

export interface DistributionDiagnostic {
  pdf_x: number[];
  pdf_y: number[];
  cdf_x: number[];
  cdf_y: number[];
  mean: number;
  median: number;
  p01: number;
  p05: number;
  p95: number;
  p99: number;
  zero_mass: number;
  negative_mass: number;
}

export interface ContinuationDiagnostic {
  state: number[];
  exercise_payoff: number[];
  continuation_value: number[];
  exercise_share: number[];
  n_itm: number;
}

export interface Diagnostics {
  year: number;
  distributions: Record<RegimeKey, Record<AssetKey, DistributionDiagnostic>>;
  npv_distributions: Record<RegimeKey, Record<AssetKey, DistributionDiagnostic>>;
  continuation: Record<RegimeKey, Record<AssetKey, ContinuationDiagnostic>>;
}

export interface Meta {
  model_version: string;
  model_sha256: string;
  parameters: ParamMeta[];
  paper_baseline: {
    regime_comparison: Record<RegimeKey, Record<AssetKey, RegimeMetric>>;
  policy_comparison: Record<PolicyKey, Record<AssetKey, PolicyMetric>>;
    switching: Record<
      SwitchingAssetKey,
      { premium_new_musd: number; reform_gain_musd: number }
    >;
  };
  replication: {
    command: string;
    source: string;
    seed: number;
    n_paths: number;
    horizon_years: number;
    outputs: string[];
  };
}

export interface ModelResult {
  model_version: string;
  model_sha256: string;
  run_id: string;
  seed: number;
  runtime_s: number;
  params_used: Record<string, number | boolean>;
  regime_comparison: Record<RegimeKey, Record<AssetKey, RegimeMetric>>;
  policy_comparison: Record<PolicyKey, Record<AssetKey, PolicyMetric>>;
  switching: Record<SwitchingAssetKey, SwitchingAsset>;
  diagnostics: Diagnostics;
  sensitivity: SensitivityRow[];
  definitions: Record<string, string>;
  scope: string[];
}

async function responseJson<T>(response: Response, context: string): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${context}: HTTP ${response.status}${body ? `: ${body}` : ""}`);
  }
  return response.json() as Promise<T>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasPolicyComparison(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const policies = ["historical_flat", "spot_only", "fixed_mep_no_restitution", "switching_no_restitution", "switching_with_restitution"];
  return policies.every((key) => {
    const assets = value[key];
    return isRecord(assets) && ["pv", "joint"].every((asset) => {
      const row = assets[asset];
      return isRecord(row) &&
        ["option_value_musd", "immediate_npv_musd", "immediate_decision_value_musd", "pure_deferral_premium_musd", "gain_vs_forced_immediate_musd", "avoided_negative_npv_musd", "exercise_rate"].every((field) => typeof row[field] === "number" && Number.isFinite(row[field])) &&
        (row.mean_exercise_time === null || (typeof row.mean_exercise_time === "number" && Number.isFinite(row.mean_exercise_time)));
    });
  });
}

function assertMeta(value: unknown): asserts value is Meta {
  if (!isRecord(value) || !Array.isArray(value.parameters) || !isRecord(value.replication) || !isRecord(value.paper_baseline) || !hasPolicyComparison(value.paper_baseline.policy_comparison)) {
    throw new Error("Metadata request failed: incompatible API payload");
  }
}

function assertModelResult(value: unknown): asserts value is ModelResult {
  if (!isRecord(value) || !isRecord(value.regime_comparison)) {
    throw new Error("Model run failed: incompatible API payload");
  }
  const comparison = value.regime_comparison;
  const regimes = ["flat_stabilization", "spot_only", "dual_switching"];
  const hasRegimes = regimes.every((key) => {
    const regime = comparison[key];
    return isRecord(regime) && isRecord(regime.pv) && isRecord(regime.joint);
  });
  if (
    !hasRegimes ||
    !hasPolicyComparison(value.policy_comparison) ||
    !isRecord(value.switching) ||
    !["pv", "bess_energy", "joint"].every((asset) => {
      const row = isRecord(value.switching) ? value.switching[asset] : null;
      return isRecord(row) && isRecord(row.settlement);
    }) ||
    !isRecord(value.diagnostics) ||
    !Array.isArray(value.sensitivity) ||
    !isRecord(value.definitions) ||
    !Array.isArray(value.scope)
  ) {
    throw new Error("Model run failed: incompatible API payload");
  }
}

export async function getMeta(): Promise<Meta> {
  const value = await responseJson<unknown>(await fetch(`${API_URL}/api/meta`), "Metadata request failed");
  assertMeta(value);
  return value;
}

export async function runModel(
  params: Record<string, number>,
  withSensitivity: boolean,
  seed = 42,
): Promise<ModelResult> {
  const response = await fetch(`${API_URL}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ params, seed, with_sensitivity: withSensitivity }),
  });
  const value = await responseJson<unknown>(response, "Model run failed");
  assertModelResult(value);
  return value;
}
