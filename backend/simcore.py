"""Reproducible API wrapper for the IEEE Access manuscript's settlement and investment experiment.

The scientific implementation lives in ``lsmc_switching_cases.py``.  This
module only validates request parameters, calls that implementation, converts
units, and attaches an audit trail suitable for JSON export.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict

import numpy as np

from lsmc_switching import SwitchConfig
from lsmc_switching_cases import CaseParams, run_all, sensitivity, restitution_comparison

MODEL_VERSION = "ieee-access-2026-10-16"
MODEL_FILES = (
    Path(__file__).with_name("lsmc_switching.py"),
    Path(__file__).with_name("lsmc_switching_cases.py"),
)
_model_digest = hashlib.sha256()
for _model_file in MODEL_FILES:
    _model_digest.update(_model_file.name.encode())
    _model_digest.update(b"\0")
    _model_digest.update(_model_file.read_bytes())
MODEL_SHA256 = _model_digest.hexdigest()

# The numerical engine is CPU-bound. A lock prevents concurrent requests from
# exhausting the single-worker deployment used by the companion application.
_LOCK = threading.Lock()


def _default_params() -> Dict[str, float]:
    p = CaseParams()
    return {
        **asdict(p.base),
        **{k: v for k, v in asdict(p).items() if k != "base"},
    }


PAPER_DEFAULTS = _default_params()

PUBLIC_TO_MODEL_PARAM = {}
MODEL_TO_PUBLIC_PARAM = {
    model_name: public_name
    for public_name, model_name in PUBLIC_TO_MODEL_PARAM.items()
}
PARAM_ALIASES = {
    # Backward-compatible request aliases; responses use the manuscript terms.
    "pre_reform_s0": "flat_s0",
    "pre_reform_sigma": "flat_sigma",
    "legacy_s0": "flat_s0",
    "legacy_sigma": "flat_sigma",
}
PUBLIC_DEFAULTS = {
    MODEL_TO_PUBLIC_PARAM.get(name, name): value
    for name, value in PAPER_DEFAULTS.items()
}

REGIME_KEY_MAP = {
    # The old keys are accepted only for compatibility with archived outputs.
    "pre_reform_stabilized": "flat_stabilization",
    "flat_stabilization": "flat_stabilization",
    "legacy_guarantee": "flat_stabilization",
    "spot_only": "spot_only",
    "dual_switching": "dual_switching",
}

# Bounds are deployment guards, not econometric confidence intervals.
PARAM_BOUNDS = {
    "n_paths": (500, 10_000),
    "t_years": (5, 25),
    "r": (0.01, 0.15),
    "s0_spot": (5.0, 80.0),
    "mu_spot": (-0.05, 0.20),
    "sigma_spot": (0.05, 0.60),
    "s0_mep": (20.0, 100.0),
    "mu_mep": (-0.05, 0.20),
    "sigma_mep": (0.02, 0.40),
    "rho": (-0.90, 0.90),
    "gen_annual_mwh": (1_000.0, 15_000.0),
    "fpm": (0.50, 1.20),
    "om_annual": (10_000.0, 400_000.0),
    "ci": (1_000_000.0, 12_000_000.0),
    "salvage_frac": (0.0, 0.50),
    "s0_p": (20_000.0, 200_000.0),
    "mu_p": (-0.05, 0.20),
    "sigma_p": (0.01, 0.60),
    "rho_ep": (-0.90, 0.90),
    "peak_shave": (0.05, 0.95),
    "ci_combined": (2_000_000.0, 15_000_000.0),
    "synergy_revenue": (0.0, 0.50),
    "flat_s0": (20.0, 150.0),
    "flat_sigma": (0.01, 0.40),
}


PARAM_META = [
    # group, name, label, unit, step
    ("Remuneration prices", "flat_s0", "Flat-price stabilization level", "USD/MWh", 1),
    ("Remuneration prices", "flat_sigma", "Flat-price stabilization volatility", "", 0.01),
    ("Remuneration prices", "s0_spot", "Generation-weighted spot price X₀ˢ", "USD/MWh", 1),
    ("Remuneration prices", "sigma_spot", "Spot-price volatility σ_S", "", 0.01),
    ("Remuneration prices", "s0_mep", "MEP stabilized price X₀ᴹ", "USD/MWh", 1),
    ("Remuneration prices", "sigma_mep", "MEP stabilized-price volatility σ_M", "", 0.01),
    ("Remuneration prices", "rho", "Spot-MEP price correlation ρ_SM", "", 0.05),
    ("Simulation", "n_paths", "Monte Carlo paths", "", 500),
    ("Simulation", "t_years", "Investment horizon T", "years", 1),
    ("Simulation", "r", "Discount rate r", "", 0.005),
    ("PV project", "ci", "PV investment cost", "USD", 100_000),
    ("PV project", "gen_annual_mwh", "Annual PV generation", "MWh/year", 100),
    ("PV project", "om_annual", "PV O&M", "USD/year", 5_000),
    ("Integrated PV+BESS", "ci_combined", "Integrated investment cost", "USD", 100_000),
    ("Integrated PV+BESS", "s0_p", "Initial capacity price", "USD/MW-year", 1_000),
    ("Integrated PV+BESS", "sigma_p", "Capacity-price volatility σ_P", "", 0.01),
    ("Integrated PV+BESS", "peak_shave", "Capacity-sufficiency factor", "", 0.01),
    ("Integrated PV+BESS", "synergy_revenue", "Joint energy-revenue uplift", "", 0.01),
]


def _policy_comparison(regimes: dict) -> dict:
    """Convert the paper's policy comparison to million-USD display units."""
    return {
        policy: {
            asset: {
                (name if name in ("exercise_rate", "mean_exercise_time") else name + "_musd"):
                round(float(value) if name in ("exercise_rate", "mean_exercise_time") else float(value) / 1e6, 6)
                for name, value in metrics.items()
            }
            for asset, metrics in assets.items()
        }
        for policy, assets in regimes.items()
    }


_REFERENCE = json.loads(Path(__file__).with_name("paper_reference.json").read_text())
PAPER_BASELINE = {
    "policy_comparison": _policy_comparison(_REFERENCE["regimes"]),
    "switching": {
        asset: {"premium_new_musd": round(row["premium_new"] / 1e6, 6),
                "reform_gain_musd": round(row["decree_gain"] / 1e6, 6)}
        for asset, row in _REFERENCE["operating"].items()
    },
}
PAPER_BASELINE["regime_comparison"] = {
    key: PAPER_BASELINE["policy_comparison"][policy]
    for key, policy in (("flat_stabilization", "historical_flat"),
                        ("spot_only", "spot_only"),
                        ("dual_switching", "switching_with_restitution"))
}


def parameter_schema() -> list[dict]:
    rows = []
    for group, name, label, unit, step in PARAM_META:
        lo, hi = PARAM_BOUNDS[name]
        rows.append({
            "group": group,
            "name": name,
            "label": label,
            "unit": unit,
            "step": step,
            "min": lo,
            "max": hi,
            "default": PUBLIC_DEFAULTS[name],
        })
    return rows


def _clamp(overrides: Dict[str, float]) -> Dict[str, float]:
    clean: Dict[str, float] = {}
    for requested_name, value in overrides.items():
        name = PARAM_ALIASES.get(requested_name, requested_name)
        if name not in PARAM_BOUNDS:
            continue
        if not math.isfinite(float(value)):
            raise ValueError(f"Parameter {requested_name} must be finite")
        lo, hi = PARAM_BOUNDS[name]
        clean[name] = min(max(float(value), lo), hi)
    for name in ("n_paths", "t_years"):
        if name in clean:
            clean[name] = int(clean[name])
    return clean


def _case_params(overrides: Dict[str, float]) -> tuple[CaseParams, Dict[str, float]]:
    public_values = {**PUBLIC_DEFAULTS, **_clamp(overrides)}
    values = {
        PUBLIC_TO_MODEL_PARAM.get(name, name): value
        for name, value in public_values.items()
    }
    base_names = {f.name for f in fields(SwitchConfig)}
    case_names = {f.name for f in fields(CaseParams)} - {"base"}
    base = SwitchConfig(**{k: values[k] for k in base_names})
    case = CaseParams(base=base, **{k: values[k] for k in case_names})
    return case, public_values


def _native(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(v) for v in value]
    return value


def _musd(value: float) -> float:
    return round(float(value) / 1e6, 6)


def _comparison(raw: dict) -> dict:
    return {
        REGIME_KEY_MAP[regime]: {
            asset: {
                "option_value_musd": _musd(metrics["option_value"]),
                "exercise_rate": round(float(metrics["exercise_rate"]), 6),
                "mean_exercise_time": round(float(metrics["mean_exercise_time"]), 6),
            }
            for asset, metrics in assets.items()
        }
        for regime, assets in raw["regime_comparison"].items()
    }


def _diagnostics(raw: dict) -> dict:
    result = {"year": raw["year"]}
    for section in ("distributions", "npv_distributions", "continuation"):
        result[section] = {
            REGIME_KEY_MAP[regime]: assets
            for regime, assets in raw[section].items()
        }
    return result


def _switching(raw: dict) -> dict:
    result = {}
    for asset in ("pv", "bess_energy", "joint"):
        row = raw[asset]
        item = {
            "spot_only_musd": _musd(row["spot_only"]),
            "mep_only_musd": _musd(row["mep_only"]),
            "switch_old_musd": _musd(row["switch_old_4yr"]),
            "switch_new_musd": _musd(row["switch_new_1yr"]),
            "premium_new_musd": _musd(row["premium_new"]),
            "reform_gain_musd": _musd(row["decree_gain"]),
            "migration": {
                "old_share_spot_terminal": round(float(row["mig_old_4yr_share_spot"]), 6),
                "new_share_spot_terminal": round(float(row["mig_new_1yr_share_spot"]), 6),
                "old_mean_switches": round(float(row["mig_old_4yr_switches"]), 6),
                "new_mean_switches": round(float(row["mig_new_1yr_switches"]), 6),
            },
            "investment": None,
            "settlement": row["settlement"],
        }
        if f"opt_new_1yr" in row:
            item["investment"] = {
                "old_option_value_musd": _musd(row["opt_old_4yr"]),
                "old_exercise_rate": round(float(row["opt_old_4yr_pex"]), 6),
                "old_mean_exercise_time": round(float(row["opt_old_4yr_mean_t"]), 6),
                "new_option_value_musd": _musd(row["opt_new_1yr"]),
                "new_exercise_rate": round(float(row["opt_new_1yr_pex"]), 6),
                "new_mean_exercise_time": round(float(row["opt_new_1yr_mean_t"]), 6),
            }
        result[asset] = item
    return result


def run_model(
    overrides: Dict[str, float],
    seed: int = 42,
    with_sensitivity: bool = True,
) -> dict:
    """Run the current paper policy experiment and return a JSON-ready audit record."""
    p, params_used = _case_params(overrides)
    with _LOCK:
        raw = run_all(p, seed=seed, collect_diagnostics=True)
        comparison = restitution_comparison(p, seed=seed)
        sens_raw = sensitivity(p, seed=seed) if with_sensitivity else []

    sens = [
        {
            "sigma_spot": float(row["sigma_spot"]),
            "asset": row["case"],
            "premium_new_musd": _musd(row["premium_new"]),
            "reform_gain_musd": _musd(row["decree_gain"]),
        }
        for row in sens_raw
    ]
    fingerprint_payload = json.dumps(
        {
            "model": MODEL_SHA256,
            "version": MODEL_VERSION,
            "seed": seed,
            "params": params_used,
            "with_sensitivity": with_sensitivity,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    result = {
        "model_version": MODEL_VERSION,
        "model_sha256": MODEL_SHA256,
        "run_id": hashlib.sha256(fingerprint_payload).hexdigest()[:16],
        "seed": seed,
        "params_used": params_used,
        "regime_comparison": _comparison(raw),
        "policy_comparison": _policy_comparison(comparison["regimes"]),
        "switching": _switching(raw),
        "diagnostics": _diagnostics(raw["diagnostics"]),
        "sensitivity": sens,
        "definitions": {
            "pure_deferral_premium": "F0 - max(N0, 0): value of retaining the right to invest later above investing or rejecting today, with matching operating rights.",
            "forced_immediate_gap": "F0 - N0 includes the pure waiting premium plus max(-N0, 0) of avoided negative NPV; it is not a pure timing premium.",
            "balance_mep": "Signed metered energy-price differences accrue annually in this approximation and are repaid in twelve monthly installments in the following year. Accrued liabilities survive switching and the operating horizon. CPI adjustment is represented in real units.",
            "exercise_rate": (
                "Share of simulated paths on which the LSMC policy exercises; "
                "it is not a forecast investment probability or an entry rate."
            ),
            "premium_new": (
                "Net operating value with one-year switching minus the better fixed "
                "remuneration, with identical Balance MEP restitution in every case."
            ),
            "reform_gain": (
                "Net operating value with one-year permanence minus four-year permanence, "
                "holding restitution fixed; this is not the benefit of the entire reform."
            ),
            "option_distribution": (
                "Pathwise compound-option values under the estimated exercise policy; "
                "the mass at zero equals the share of paths that never exercise."
            ),
            "npv_distribution": (
                "Realized discounted NPV conditional on investing at year 0; the dual "
                "initial regime is selected ex ante, never with pathwise hindsight."
            ),
            "continuation_diagnostic": (
                "Year-5 in-sample LSMC conditional means for in-the-money paths; "
                "curve crossings are numerical diagnostics, not structural thresholds."
            ),
        },
        "scope": [
            "Single-project, partial-equilibrium valuation; no feeder congestion or welfare equilibrium.",
            "The four spot/time-block configurations share price paths and project assumptions; historical flat has a separate price and volatility calibration.",
            "No-restitution support is a hypothetical policy, not a current entitlement for new Chilean projects.",
            "Spot-only uncertainty can motivate waiting despite positive immediate NPV; restitution removes much of the acceleration from support without repayment.",
            "Policy transfer requires local calibration, transfer budgets and locational/technical safeguards; no optimal deployment trajectory or welfare ranking is estimated.",
            "Annual accrual omits intrayear seasonality, hourly dispatch, guarantee costs, liquidity constraints and inflation/exchange-rate basis risk.",
            "The 15% co-location services proxy is valued from spot flows independently of the elected regime; historical flat retains a separate proxy. It is an assumption, not an estimated causal synergy.",
            "Terminal spot shares describe simulated policy paths, not a prediction of a 100% spot market.",
        ],
    }
    return _native(result)
