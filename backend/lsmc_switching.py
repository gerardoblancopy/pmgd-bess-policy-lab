#!/usr/bin/env python3
"""
LEGACY GROSS-PRICE ANALYSIS (no Balance MEP). Only SwitchConfig is imported
by lsmc_switching_cases.py, the authoritative settled manuscript model.

LSMC Optimal Switching — Case 4: simplified PMGD price-regime option motivated by Decreto 1/2026
================================================================================
Values the right of a PMGD (PV 4 MW) to switch between:
  (a) spot regime  : injections valued at generation-weighted marginal cost
  (b) MEP regime   : injections valued at "precio basico de energia por
                     intervalo temporal" (stabilization mechanism, DS 88 as
                     amended by Decreto 1/2026)

Two regulatory designs compared:
  OLD (DS 88, art. 12)         : minimum permanence 4 years, 6-month notice
  NEW (Decreto 1/2026, art. 12) : minimum permanence 1 year,  6-month notice

The unchanged six-month notice is approximated by a one-period decision lag,
so the isolated effect measured here is the permanence constraint (4y vs 1y).
Balance MEP restitution, indexation, and guarantees are outside this model.

Calibration (energiE/PPU 2025 report, Figs. 11-15; year 2024, north+central):
  - Gen-weighted precio basico (solar blocks 35-39 USD/MWh + shoulders): ~45
  - Gen-weighted marginal cost during solar hours (1-20 USD/MWh):        ~25
  - sigma_spot ~ 0.35 (monthly CMg 2020-2024 swung 30->190->35 USD/MWh)
  - sigma_basico ~ 0.12 (administrative, semiannual updates)
  - rho ~ 0.7 (basico tracks 48-month expected marginal costs)

Method: Longstaff-Schwartz LSMC for optimal switching (Carmona & Ludkovski,
2008): one continuation regression per (regime, permanence-counter) state,
plus a compound layer where the investment option's exercise payoff is the
optimally-switched operating value.
"""

import logging
import os
import time
from dataclasses import dataclass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.environ.get(
    "PMGD_OUTPUT_DIR", os.path.dirname(os.path.abspath(__file__))
)

SEED = 42


@dataclass(frozen=True)
class SwitchConfig:
    """Case-4 configuration (base calibration, energiE 2025 Figs. 11-15)."""
    # Simulation (matched to lsmc_pmgd.py)
    n_paths: int = 5000
    t_years: int = 15
    r: float = 0.05
    # Spot regime: generation-weighted marginal cost, USD/MWh
    s0_spot: float = 25.0
    mu_spot: float = 0.073022      # long-run drift, matched to paper PMM MLE
    sigma_spot: float = 0.35
    # MEP regime: gen-weighted precio basico por intervalo temporal, USD/MWh
    s0_mep: float = 45.0
    mu_mep: float = 0.073022
    sigma_mep: float = 0.12
    rho: float = 0.7
    # PV asset (matched to Case 1, incl. marginal loss factor FPM)
    gen_annual_mwh: float = 5_774.0
    fpm: float = 0.95
    om_annual: float = 88_000.0
    ci: float = 4_400_000.0
    salvage_frac: float = 0.20
    # Regime-switching constraints (years of minimum permanence)
    permanence_old: int = 4        # DS 88 art. 12
    permanence_new: int = 1        # Decreto 1/2026 art. 12


def correlated_gbm(cfg: SwitchConfig, seed: int = SEED):
    """Simulate correlated GBM paths (spot, mep), shape (n_paths, T+1)."""
    rng = np.random.default_rng(seed)
    n, t = cfg.n_paths, cfg.t_years
    z1 = rng.standard_normal((n, t))
    z2 = cfg.rho * z1 + np.sqrt(1 - cfg.rho**2) * rng.standard_normal((n, t))

    def build(s0, mu, sigma, z):
        log_incr = (mu - 0.5 * sigma**2) + sigma * z
        log_paths = np.cumsum(log_incr, axis=1)
        return np.hstack([np.full((n, 1), s0),
                          s0 * np.exp(log_paths)])

    return (build(cfg.s0_spot, cfg.mu_spot, cfg.sigma_spot, z1),
            build(cfg.s0_mep, cfg.mu_mep, cfg.sigma_mep, z2))


def annual_cf(cfg: SwitchConfig, price_col: np.ndarray) -> np.ndarray:
    """Operating cash flow for one year at the given regime price."""
    return cfg.gen_annual_mwh * cfg.fpm * price_col - cfg.om_annual


def _basis(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """2-D polynomial basis up to degree 2 with cross term (as in paper)."""
    return np.column_stack([
        np.ones_like(x1), x1, x2, x1**2, x2**2, x1 * x2,
    ])


def _fitted_continuation(v_next: np.ndarray, s: np.ndarray,
                         m: np.ndarray) -> np.ndarray:
    """OLS regression of next-period value on price basis -> E[V|prices]."""
    a = _basis(s, m)
    beta, *_ = np.linalg.lstsq(a, v_next, rcond=None)
    return a @ beta


def switching_value(cfg: SwitchConfig, spot: np.ndarray, mep: np.ndarray,
                    permanence: int, collect_policy: bool = False):
    """
    Optimal-switching value of the OPERATING asset from t=0, per path.

    State: (regime m in {0=spot, 1=mep}, years-in-regime c in 1..permanence).
    A switch requested at t (allowed only if c >= permanence) becomes
    effective at t+1 (notice lag). Returns dict with:
      v0[m]     : t=0 value per path if starting in regime m (c=permanence,
                  i.e. free to request a switch immediately)
      v_fun     : per-(t) fitted values needed by the compound layer
      switches  : avg number of switches per path (optimal start regime)
    """
    n, t_yrs = spot.shape[0], cfg.t_years
    disc = np.exp(-cfg.r)
    c_states = list(range(1, permanence + 1))  # years already in regime
    # Terminal (t = T): final year's cash flow in the prevailing regime
    # plus salvage, so the switching asset and the fixed-regime benchmark
    # both span T+1 annual cash flows.
    salvage = cfg.salvage_frac * cfg.ci
    cf_T = {0: annual_cf(cfg, spot[:, t_yrs]),
            1: annual_cf(cfg, mep[:, t_yrs])}
    v_next = {(m, c): cf_T[m] + salvage for m in (0, 1) for c in c_states}
    policy = []  # (t, switch_mask_spot, switch_mask_mep) for c=permanence
    v_at_t = []  # fitted E[V] at each t for compound layer (both regimes)

    for t in range(t_yrs - 1, -1, -1):
        s_t, m_t = spot[:, t], mep[:, t]
        cf = {0: annual_cf(cfg, s_t), 1: annual_cf(cfg, m_t)}
        # Fitted continuations for every next-period state
        cont = {k: _fitted_continuation(v_next[k], s_t, m_t)
                for k in v_next}
        v_now = {}
        pol_t = {}
        for m in (0, 1):
            other = 1 - m
            for c in c_states:
                c_next = min(c + 1, permanence)
                stay = cont[(m, c_next)]
                if c >= permanence:
                    # switch effective next year -> arrive with c=1
                    switch = cont[(other, 1)]
                    do_switch = switch > stay
                    best_cont = np.where(do_switch, switch, stay)
                    # realized (not fitted) value carried backward
                    realized = np.where(do_switch,
                                        v_next[(other, 1)],
                                        v_next[(m, c_next)])
                    pol_t[m] = do_switch
                else:
                    best_cont = stay
                    realized = v_next[(m, c_next)]
                    _ = best_cont  # fitted used only for the decision
                v_now[(m, c)] = cf[m] + disc * realized
        if collect_policy:
            policy.append((t, pol_t.get(0), pol_t.get(1)))
        # store fitted total value at t (free state c=permanence) for compound
        fit = {m: cf[m] + disc *
               np.maximum(cont[(m, min(permanence, permanence))],
                          cont[(1 - m, 1)])
               for m in (0, 1)}
        v_at_t.append((t, fit))
        v_next = v_now

    v0 = {m: v_next[(m, permanence)] for m in (0, 1)}
    v_at_t = dict((t, f) for t, f in v_at_t)
    return {"v0": v0, "v_fitted": v_at_t, "policy": policy}


def fixed_regime_value(cfg: SwitchConfig, prices: np.ndarray) -> np.ndarray:
    """No-switching benchmark: PV operated forever in one regime."""
    n, t_yrs = prices.shape[0], cfg.t_years
    disc = np.exp(-cfg.r * np.arange(1, t_yrs + 1))
    cf = (cfg.gen_annual_mwh * cfg.fpm * prices[:, 1:]
          - cfg.om_annual)
    value = cf @ disc + cfg.salvage_frac * cfg.ci * np.exp(-cfg.r * t_yrs)
    # add year-0 cash flow at t=0 price (consistent with switching_value)
    value += annual_cf(cfg, prices[:, 0])
    return value


def investment_option(cfg: SwitchConfig, spot: np.ndarray, mep: np.ndarray,
                      permanence: int) -> dict:
    """
    Compound layer: American option to invest CI and receive the optimally
    switched operating asset (entry regime chosen at COD).
    Standard LSMC over (spot, mep) with exercise payoff from the fitted
    switching values.
    """
    sw = switching_value(cfg, spot, mep, permanence)
    n, t_yrs = spot.shape[0], cfg.t_years
    disc = np.exp(-cfg.r)

    def payoff(t):
        f = sw["v_fitted"][t]
        return np.maximum(f[0], f[1]) - cfg.ci

    # terminal
    ev = payoff(t_yrs - 1)
    cash = np.maximum(ev, 0.0)
    ex_time = np.where(ev > 0, t_yrs - 1, -1)

    for t in range(t_yrs - 2, -1, -1):
        ev = payoff(t)
        itm = ev > 0
        cash *= disc
        if itm.sum() > 50:
            cont_hat = _fitted_continuation(cash[itm], spot[itm, t],
                                            mep[itm, t])
            ex_now = ev[itm] > cont_hat
            idx = np.where(itm)[0][ex_now]
            cash[idx] = ev[itm][ex_now]
            ex_time[idx] = t
    option = cash
    return {"option_paths": option, "exercise_time": ex_time,
            "switch_v0": sw["v0"]}


def run_case4(cfg: SwitchConfig = SwitchConfig()) -> dict:
    """Full Case-4 run: benchmarks, old vs new switching, compound option."""
    t0 = time.time()
    np.random.seed(SEED)
    spot, mep = correlated_gbm(cfg)

    v_spot_only = fixed_regime_value(cfg, spot)
    v_mep_only = fixed_regime_value(cfg, mep)
    best_fixed = np.maximum(v_spot_only.mean(), v_mep_only.mean())

    res = {}
    for label, perm in (("old_4yr", cfg.permanence_old),
                        ("new_1yr", cfg.permanence_new)):
        sw = switching_value(cfg, spot, mep, perm)
        # Starting regime chosen at t=0 with t=0 information only:
        # max of means, NOT pathwise max (which would be foresight bias).
        v_flex = max(sw["v0"][0].mean(), sw["v0"][1].mean())
        inv = investment_option(cfg, spot, mep, perm)
        res[label] = {
            "v_flex_mean": v_flex,
            "flex_premium": v_flex - best_fixed,
            "invest_option_mean": inv["option_paths"].mean(),
            "invest_option_se": inv["option_paths"].std(ddof=1)
                                / np.sqrt(cfg.n_paths),
            "exercise_prob": (inv["exercise_time"] >= 0).mean(),
            "mean_ex_time": (inv["exercise_time"]
                             [inv["exercise_time"] >= 0].mean()
                             if (inv["exercise_time"] >= 0).any()
                             else np.nan),
        }

    out = {
        "v_spot_only": v_spot_only.mean(),
        "v_mep_only": v_mep_only.mean(),
        **{f"{k}_{kk}": vv for k, v in res.items() for kk, vv in v.items()},
        "decree_gain": res["new_1yr"]["v_flex_mean"]
                       - res["old_4yr"]["v_flex_mean"],
        "decree_gain_option": res["new_1yr"]["invest_option_mean"]
                              - res["old_4yr"]["invest_option_mean"],
        "runtime_s": time.time() - t0,
    }
    return out


def sensitivity(base: SwitchConfig) -> list:
    """Grid over rho, sigma_spot, s0_spot."""
    rows = []
    grids = {
        "rho": [0.3, 0.5, 0.7, 0.9],
        "sigma_spot": [0.25, 0.35, 0.45],
        "s0_spot": [15.0, 25.0, 35.0],
    }
    for param, values in grids.items():
        for v in values:
            cfg = SwitchConfig(**{**base.__dict__, param: v})
            r = run_case4(cfg)
            rows.append({
                "param": param, "value": v,
                "flex_old": r["old_4yr_v_flex_mean"],
                "flex_new": r["new_1yr_v_flex_mean"],
                "decree_gain": r["decree_gain"],
                "opt_old": r["old_4yr_invest_option_mean"],
                "opt_new": r["new_1yr_invest_option_mean"],
            })
            logger.info("  sens %s=%.2f  gain=%.3fM", param, v,
                        rows[-1]["decree_gain"] / 1e6)
    return rows


def make_figures(results: dict, sens: list) -> None:
    """Figure 1: value decomposition bars. Figure 2: sensitivity."""
    fig, ax = plt.subplots(figsize=(7, 4.2))
    labels = ["Spot only", "MEP only",
              "Switching\n(DS 88, 4 yr)", "Switching\n(D1/2026, 1 yr)"]
    vals = np.array([results["v_spot_only"], results["v_mep_only"],
                     results["old_4yr_v_flex_mean"],
                     results["new_1yr_v_flex_mean"]]) / 1e6
    colors = ["#888888", "#bbbbbb", "#4477aa", "#228833"]
    ax.bar(labels, vals, color=colors)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=9)
    ax.set_ylabel("Operating asset value (USD M)")
    ax.set_title("PV 4 MW: value of the price-regime switching option")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "fig_switching_decomposition.png"),
                dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharey=True)
    for ax, param, xlabel in zip(
            axes, ["rho", "sigma_spot", "s0_spot"],
            [r"$\rho$", r"$\sigma_{spot}$", r"$S_0^{spot}$ (USD/MWh)"]):
        rows = [r for r in sens if r["param"] == param]
        x = [r["value"] for r in rows]
        ax.plot(x, [r["flex_old"] / 1e6 for r in rows], "o-",
                color="#4477aa", label="DS 88 (4 yr)")
        ax.plot(x, [r["flex_new"] / 1e6 for r in rows], "s-",
                color="#228833", label="D1/2026 (1 yr)")
        ax.set_xlabel(xlabel)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Switching value (USD M)")
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "fig_switching_sensitivity.png"),
                dpi=200)
    plt.close(fig)


def main() -> None:
    cfg = SwitchConfig()
    logger.info("=== Case 4: regime-switching option (Decreto 1/2026) ===")
    results = run_case4(cfg)
    for k, v in results.items():
        if "prob" in k or "time" in k or k == "runtime_s":
            logger.info("%-32s %10.3f", k, v)
        else:
            logger.info("%-32s %10.3f M", k, v / 1e6)

    logger.info("--- sensitivity ---")
    sens = sensitivity(cfg)
    make_figures(results, sens)

    with open(os.path.join(OUTPUT_DIR, "results_switching.txt"), "w") as f:
        f.write("Case 4: regime-switching option under Decreto 1/2026\n")
        f.write(f"seed={SEED}, n_paths={cfg.n_paths}, T={cfg.t_years}\n\n")
        for k, v in results.items():
            f.write(f"{k}: {v:.4f}\n")
        f.write("\nSensitivity:\n")
        for r in sens:
            f.write(f"{r}\n")
    logger.info("Saved figures + results_switching.txt to %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
