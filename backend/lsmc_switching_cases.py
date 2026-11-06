#!/usr/bin/env python3
"""
Price-regime switching with Balance MEP restitution under Decreto 1/2026.

Annual energy accruals are assigned to December and repaid in twelve monthly
installments in the following year, including after switching or project end.
Real CPI-indexed principal uses a constant real CLP/USD conversion. Guarantee
fees, intrayear dispatch, inflation/FX basis risk and counterparty default are
not modeled; this is an annual approximation, not an operator billing engine.

Generalizes lsmc_switching.py to the paper's three case studies. A single MGPE
connection elects ONE remuneration regime (spot vs MEP) for all its injections
and storage-charging withdrawals, so the integrated PV+BESS installation makes
a joint regime election.

Assets valued (operating, then compound investment option where meaningful):
  1. PV energy stream          — solar-weighted block prices (as in the
                                 original Case-4 analysis).
  2. BESS energy stream        — discharge at the evening peak blocks, charge
                                 in the solar trough; opposite block weighting
                                 to PV (energiE 2025, Figs. 11-12).
  3. Integrated PV+BESS        — joint regime election; trivariate state
                                 (X_spot, X_mep, S_p) adds the regime-
                                 independent capacity-payment stream.

Block-price calibration (2024 hourly profiles, energiE 2025 Figs. 11-12):
  solar-weighted:    spot ~25, mep ~45  USD/MWh   (PV injections)
  peak discharge:    spot ~85, mep ~110 USD/MWh   (BESS, 2 h evening peak)
  solar-trough charge: spot ~15, mep ~35 USD/MWh  (BESS charging)
Intraday shape is held constant: discharge/charge prices are fixed multiples
of the two stochastic state processes (X_s anchored at 25, X_m at 45).
"""

import logging
import os
import time
from dataclasses import dataclass, replace

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Keep figure labels legible at the journal's full two-column width.
plt.rcParams.update({"font.size": 13, "axes.labelsize": 13,
                     "xtick.labelsize": 12, "ytick.labelsize": 12,
                     "pdf.fonttype": 42, "ps.fonttype": 42})

from lsmc_switching import SwitchConfig

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.environ.get(
    "PMGD_OUTPUT_DIR", os.path.dirname(os.path.abspath(__file__))
)
SEED = 42


@dataclass(frozen=True)
class CaseParams:
    """Extends the Case-4 calibration with BESS blocks and capacity price."""
    base: SwitchConfig = SwitchConfig()
    # BESS energy stream (block prices as multiples of X_s / X_m anchors)
    dis_mult_spot: float = 85.0 / 25.0
    dis_mult_mep: float = 110.0 / 45.0
    chg_mult_spot: float = 15.0 / 25.0
    chg_mult_mep: float = 35.0 / 45.0
    e_dis_annual: float = 2.0 * 365 * 0.9   # MWh/yr discharged (1 cycle/day)
    bess_eff: float = 0.90
    bess_om: float = 15_000.0
    ci_bess: float = 750_000.0
    bess_salvage_frac: float = 0.15
    # Capacity stream (paper Case-2 parameters)
    # CNE, precio de nudo de la potencia en Quillota 220 kV (misma barra que los
    # anclajes de energia): 8.016,64 CLP/kW-mes / 917,88 CLP/USD x 12 = 104.8 kUSD/MW-ano
    # (ITD PNCP 2S-2024, Tabla 31; = Pbpot Centro-Norte 8,8203 x factor 0,9902).
    s0_p: float = 104_800.0
    mu_p: float = 0.07543
    sigma_p: float = 0.14465
    rho_ep: float = 0.3            # energy-capacity correlation (paper)
    bess_power: float = 1.0
    # DS 70 capacity-sufficiency recognition used in the manuscript.
    # This is an accredited-power factor, so round-trip efficiency is not
    # applied a second time in capacity_rev().
    peak_shave: float = 1.0 / 3.0
    # Integrated case
    ci_combined: float = 4_400_000.0 + 750_000.0 * 0.9
    combined_salvage: float = 0.20 * 4_400_000.0 + 0.15 * 750_000.0
    synergy_revenue: float = 0.15
    # Flat-price stabilization calibration used in the three-regime comparison.
    # Kept explicit so the companion app can reproduce and stress-test the
    # manuscript calibration without maintaining a second implementation.
    # PNCP zona centro (Alto Jahuel / Quillota 220), 2024: 67 USD/MWh.
    flat_s0: float = 67.0
    flat_sigma: float = 0.116267
    # False is the explicit no-restitution policy counterfactual.
    restitution: bool = True


def trivariate_gbm(p: CaseParams, seed: int = SEED):
    """(X_s, X_m) correlated pair + S_p correlated rho_ep with X_s."""
    cfg = p.base
    rng = np.random.default_rng(seed)
    n, t = cfg.n_paths, cfg.t_years
    z1 = rng.standard_normal((n, t))
    z2 = cfg.rho * z1 + np.sqrt(1 - cfg.rho**2) * rng.standard_normal((n, t))
    z3 = p.rho_ep * z1 + np.sqrt(1 - p.rho_ep**2) * rng.standard_normal((n, t))

    def build(s0, mu, sigma, z):
        log_paths = np.cumsum((mu - 0.5 * sigma**2) + sigma * z, axis=1)
        return np.hstack([np.full((n, 1), s0), s0 * np.exp(log_paths)])

    xs = build(cfg.s0_spot, cfg.mu_spot, cfg.sigma_spot, z1)
    xm = build(cfg.s0_mep, cfg.mu_mep, cfg.sigma_mep, z2)
    sp = build(p.s0_p, p.mu_p, p.sigma_p, z3)
    return xs, xm, sp


# ── Revenue streams (arrays over paths, at a time column t) ──────

def pv_rev(p: CaseParams, x_regime: np.ndarray) -> np.ndarray:
    cfg = p.base
    return cfg.gen_annual_mwh * cfg.fpm * x_regime - cfg.om_annual


def bess_energy_rev(p: CaseParams, x_regime: np.ndarray, spot: bool) -> np.ndarray:
    dis = p.dis_mult_spot if spot else p.dis_mult_mep
    chg = p.chg_mult_spot if spot else p.chg_mult_mep
    return (p.e_dis_annual * dis * x_regime
            - (p.e_dis_annual / p.bess_eff) * chg * x_regime)


def capacity_rev(p: CaseParams, sp_col: np.ndarray) -> np.ndarray:
    return p.bess_power * sp_col * p.peak_shave - p.bess_om


def saldo_installments(balance):
    """Signed real principal: positive means payable, negative receivable."""
    return np.asarray(balance)[..., None] * np.ones(12) / 12


def settlement_discount(r):
    """PV at December of twelve next-year month-end installments."""
    return float(np.exp(-r * np.arange(1, 13) / 12).mean())


def saldo_balance(p, xs, xm, asset):
    """Metered net-energy valuation difference; charging enters negatively."""
    pv = p.base.gen_annual_mwh * p.base.fpm * (xm - xs)
    battery = bess_energy_rev(p, xm, False) - bess_energy_rev(p, xs, True)
    if asset == "pv":
        return pv
    if asset == "bess_energy":
        return battery
    if asset == "joint":
        return pv + battery
    raise ValueError(f"Unknown asset: {asset}")


def net_mep_revenue(p, revenue, balance):
    # Future settlement is irrevocable and linear, so its PV is booked at accrual.
    return revenue - settlement_discount(p.base.r) * balance if p.restitution else revenue


# ── Generic optimal-switching engine ─────────────────────────────

def _basis(cols):
    """Polynomial degree-2 basis with cross terms over 2 or 3 state vars."""
    out = [np.ones_like(cols[0])]
    out += list(cols)
    out += [c * c for c in cols]
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            out.append(cols[i] * cols[j])
    return np.column_stack(out)


def _fit(v_next, cols):
    return _basis(cols) @ _fit_coefficients(v_next, cols)


def _fit_coefficients(v_next, cols):
    """Fit the continuation regression and expose coefficients for diagnostics."""
    a = _basis(cols)
    # Capacity-price squares otherwise dwarf the intercept and energy columns.
    scale = np.sqrt(np.mean(a * a, axis=0))
    scale[scale == 0] = 1
    beta, *_ = np.linalg.lstsq(a / scale, v_next, rcond=None)
    return beta / scale


def switching_generic(p: CaseParams, rev_funcs, state_cols_at, permanence: int,
                      terminal: float):
    """
    rev_funcs: annual PV contributions; MEP includes its future settlement liability.
    state_cols_at: f(t) -> list of state columns for the regression basis.
    terminal: salvage added at t = T.
    Returns (v0 per starting regime with entry permanence, fitted entry values, policy masks),
    where policy[(t, m)] is the per-path switch decision at the free state.
    """
    cfg = p.base
    n, t_yrs = cfg.n_paths, cfg.t_years
    disc = np.exp(-cfg.r)
    c_states = list(range(1, permanence + 1))
    v_next = {(m, c): rev_funcs[m](t_yrs) + terminal
              for m in (0, 1) for c in c_states}
    v_at_t = {}
    policy = {}

    for t in range(t_yrs - 1, -1, -1):
        cols = state_cols_at(t)
        cf = {m: rev_funcs[m](t) for m in (0, 1)}
        cont = {k: _fit(v_next[k], cols) for k in v_next}
        v_now = {}
        for m in (0, 1):
            other = 1 - m
            for c in c_states:
                c_next = min(c + 1, permanence)
                if c >= permanence:
                    do_switch = cont[(other, 1)] > cont[(m, c_next)]
                    realized = np.where(do_switch, v_next[(other, 1)],
                                        v_next[(m, c_next)])
                    if c == permanence:
                        policy[(t, m)] = do_switch
                else:
                    realized = v_next[(m, c_next)]
                v_now[(m, c)] = cf[m] + disc * realized
        # A newly commissioned asset must satisfy its initial permanence too.
        v_at_t[t] = {
            m: cf[m] + disc * (np.maximum(cont[(m, 1)], cont[(1 - m, 1)])
                              if permanence == 1 else cont[(m, 2)])
            for m in (0, 1)
        }
        v_next = v_now

    return {m: v_next[(m, 1)] for m in (0, 1)}, v_at_t, policy


def policy_regimes(p: CaseParams, policy, permanence: int, start_m: int = 1):
    """
    Replay the optimal switching policy forward from COD in regime start_m
    (default MEP, the optimal entry today). A switch decided at t becomes
    effective at t+1; the permanence counter then restarts.
    Returns each path's regime at every operating date.
    """
    cfg = p.base
    n, t_yrs = cfg.n_paths, cfg.t_years
    m = np.full(n, start_m)
    c = np.ones(n, dtype=int)
    regimes = np.full((n, t_yrs + 1), start_m, dtype=int)
    for t in range(t_yrs):
        free = c >= permanence
        do_switch = np.zeros(n, dtype=bool)
        for regime in (0, 1):
            mask = free & (m == regime) & policy.get((t, regime),
                                                     np.zeros(n, dtype=bool))
            do_switch |= mask
        m = np.where(do_switch, 1 - m, m)
        c = np.where(do_switch, 1, np.minimum(c + 1, permanence))
        regimes[:, t + 1] = m
    return regimes


def migration_stats(p, policy, permanence, start_m=1):
    regimes = policy_regimes(p, policy, permanence, start_m)
    return {"share_spot_T": float((regimes[:, -1] == 0).mean()),
            "mean_switches": float(np.count_nonzero(np.diff(regimes, axis=1), axis=1).mean())}


def fixed_generic(p: CaseParams, rev_func, terminal: float) -> np.ndarray:
    cfg = p.base
    t_yrs = cfg.t_years
    disc = np.exp(-cfg.r * np.arange(t_yrs + 1))
    total = np.zeros(cfg.n_paths)
    for t in range(t_yrs + 1):
        total += disc[t] * rev_func(t)
    return total + terminal * disc[-1]


def fixed_investment_option(p: CaseParams, rev_func, state_cols_at,
                            terminal: float, ci: float,
                            diagnostic_years=()):
    """Investment option when the remuneration regime cannot be changed.

    The operating value offered at exercise is a fitted conditional value,
    not a pathwise perfect-foresight NPV.  This makes the fixed-regime and
    switching-regime investment layers directly comparable.
    """
    cfg = p.base
    disc = np.exp(-cfg.r)
    realized = rev_func(cfg.t_years) + terminal
    v_at_t = {}
    for t in range(cfg.t_years - 1, -1, -1):
        cols = state_cols_at(t)
        conditional = rev_func(t) + disc * _fit(realized, cols)
        v_at_t[t] = {0: conditional, 1: conditional}
        realized = rev_func(t) + disc * realized
    return invest_option(p, v_at_t, state_cols_at, ci,
                         diagnostic_years=diagnostic_years)


def invest_option(p: CaseParams, v_at_t, state_cols_at, ci: float,
                  diagnostic_years=()):
    """American option to pay CI and receive the switched asset."""
    cfg = p.base
    t_yrs, disc = cfg.t_years, np.exp(-cfg.r)
    payoff = lambda t: np.maximum(v_at_t[t][0], v_at_t[t][1]) - ci
    ev = payoff(t_yrs - 1)
    cash = np.maximum(ev, 0.0)
    ex_time = np.where(ev > 0, t_yrs - 1, -1)
    diagnostics = {}
    for t in range(t_yrs - 2, -1, -1):
        ev = payoff(t)
        itm = ev > 0
        cash *= disc
        if itm.sum() > 50:
            cols_all = state_cols_at(t)
            cols_itm = [c[itm] for c in cols_all]
            beta = _fit_coefficients(cash[itm], cols_itm)
            cont = _basis(cols_itm) @ beta
            if t in diagnostic_years:
                cont_all = _basis(cols_all) @ beta
                diagnostics[t] = {
                    "state_primary": cols_all[0][itm].copy(),
                    "exercise_payoff": ev[itm].copy(),
                    "continuation_value": cont_all[itm].copy(),
                }
            ex_now = ev[itm] > cont
            idx = np.where(itm)[0][ex_now]
            cash[idx] = ev[itm][ex_now]
            ex_time[idx] = t
    return cash, ex_time, diagnostics


def deferral_metrics(option_value, immediate_npv):
    """Timing value above the ex-ante invest-now-or-reject alternative."""
    option_value, immediate_npv = float(option_value), float(immediate_npv)
    immediate_value = max(immediate_npv, 0.0)
    return {
        "immediate_npv": immediate_npv,
        "immediate_decision_value": immediate_value,
        "pure_deferral_premium": option_value - immediate_value,
        "gain_vs_forced_immediate": option_value - immediate_npv,
        "avoided_negative_npv": max(-immediate_npv, 0.0),
    }


def _empirical_distribution(values, bins=50, cdf_points=201):
    """Compact PDF/CDF representation of pathwise option values in USD M."""
    vals = np.asarray(values, dtype=float) / 1e6
    hist, edges = np.histogram(vals, bins=bins, density=True)
    centers = 0.5 * (edges[:-1] + edges[1:])
    ordered = np.sort(vals)
    idx = np.linspace(0, len(ordered) - 1,
                      min(cdf_points, len(ordered))).astype(int)
    return {
        "pdf_x": centers.tolist(),
        "pdf_y": hist.tolist(),
        "cdf_x": ordered[idx].tolist(),
        "cdf_y": ((idx + 1) / len(ordered)).tolist(),
        "mean": float(vals.mean()),
        "median": float(np.median(vals)),
        "p01": float(np.percentile(vals, 1)),
        "p05": float(np.percentile(vals, 5)),
        "p95": float(np.percentile(vals, 95)),
        "p99": float(np.percentile(vals, 99)),
        "zero_mass": float(np.mean(np.isclose(vals, 0.0, atol=1e-10))),
        "negative_mass": float(np.mean(vals < 0.0)),
    }


def _continuation_bins(diagnostic, n_bins=15):
    """Quantile-bin the LSMC exercise and continuation values for display.

    Only in-the-money paths are included because the LSMC exercise regression
    is estimated on that set. Values are conditional bin means, not structural
    derivatives or out-of-sample predictions.
    """
    if diagnostic is None:
        return {"state": [], "exercise_payoff": [],
                "continuation_value": [], "exercise_share": [],
                "n_itm": 0}
    x = np.asarray(diagnostic["state_primary"], dtype=float)
    exercise = np.asarray(diagnostic["exercise_payoff"], dtype=float) / 1e6
    continuation = np.asarray(diagnostic["continuation_value"], dtype=float) / 1e6
    finite = np.isfinite(x) & np.isfinite(exercise) & np.isfinite(continuation)
    x, exercise, continuation = x[finite], exercise[finite], continuation[finite]
    edges = np.unique(np.quantile(x, np.linspace(0, 1, n_bins + 1)))
    rows = []
    for i in range(len(edges) - 1):
        if i == len(edges) - 2:
            mask = (x >= edges[i]) & (x <= edges[i + 1])
        else:
            mask = (x >= edges[i]) & (x < edges[i + 1])
        if not mask.any():
            continue
        rows.append((float(x[mask].mean()),
                     float(exercise[mask].mean()),
                     float(continuation[mask].mean()),
                     float((exercise[mask] > continuation[mask]).mean())))
    return {
        "state": [row[0] for row in rows],
        "exercise_payoff": [row[1] for row in rows],
        "continuation_value": [row[2] for row in rows],
        "exercise_share": [row[3] for row in rows],
        "n_itm": int(len(x)),
    }


# ── Case runners ─────────────────────────────────────────────────

def run_all(p: CaseParams = CaseParams(), seed: int = SEED,
            collect_diagnostics: bool = False,
            diagnostic_year: int = 5) -> dict:
    cfg = p.base
    xs, xm, sp = trivariate_gbm(p, seed)
    out = {}
    diagnostic_paths = {
        "flat_stabilization": {}, "spot_only": {}, "dual_switching": {}
    }
    diagnostic_npvs = {
        "flat_stabilization": {}, "spot_only": {}, "dual_switching": {}
    }
    diagnostic_continuation = {
        "flat_stabilization": {}, "spot_only": {}, "dual_switching": {}
    }
    diagnostic_years = (diagnostic_year,) if collect_diagnostics else ()

    def analyze(label, rev_funcs, cols_at, terminal, ci=None, gross_funcs=None):
        v_spot = fixed_generic(p, rev_funcs[0], terminal).mean()
        v_mep = fixed_generic(p, rev_funcs[1], terminal).mean()
        row = {"spot_only": v_spot, "mep_only": v_mep}
        for tag, perm in (("old_4yr", 4), ("new_1yr", 1)):
            v0, v_at_t, policy = switching_generic(p, rev_funcs, cols_at,
                                                   perm, terminal)
            v_flex = max(v0[0].mean(), v0[1].mean())
            row[f"switch_{tag}"] = v_flex
            mig = migration_stats(p, policy, perm, start_m=1)
            row[f"mig_{tag}_share_spot"] = mig["share_spot_T"]
            row[f"mig_{tag}_switches"] = mig["mean_switches"]
            if ci is not None:
                years = diagnostic_years if tag == "new_1yr" else ()
                cash, ex_t, diag = invest_option(
                    p, v_at_t, cols_at, ci, diagnostic_years=years
                )
                row[f"opt_{tag}"] = cash.mean()
                row[f"opt_{tag}_pex"] = float((ex_t >= 0).mean())
                exercised = ex_t[ex_t >= 0]
                row[f"opt_{tag}_mean_t"] = (
                    float(exercised.mean()) if exercised.size else float("nan")
                )
                if collect_diagnostics and tag == "new_1yr" and label in ("pv", "joint"):
                    diagnostic_paths["dual_switching"][label] = cash.copy()
                    diagnostic_continuation["dual_switching"][label] = diag.get(diagnostic_year)
                    # The initial regime is selected ex ante by expected value;
                    # selecting the better v0 path by path would leak foresight.
                    start_regime = 0 if v0[0].mean() >= v0[1].mean() else 1
                    diagnostic_npvs["dual_switching"][label] = (
                        v0[start_regime].copy() - ci
                    )
            if tag == "new_1yr" and gross_funcs is not None:
                start_regime = 0 if v0[0].mean() >= v0[1].mean() else 1
                regimes = policy_regimes(p, policy, perm, start_regime)
                balances = np.where((regimes == 1) & p.restitution,
                                    saldo_balance(p, xs, xm, label), 0)
                gross = np.column_stack([
                    np.where(regimes[:, t] == 1, gross_funcs[1](t), gross_funcs[0](t))
                    for t in range(cfg.t_years + 1)
                ])
                discount = np.exp(-cfg.r * np.arange(cfg.t_years + 1))
                # Explicit monthly payments include all twelve after the last operating date.
                payments = saldo_installments(balances)
                times = np.arange(cfg.t_years + 1)[:, None] + np.arange(1, 13)/12
                repayments_pv = (payments * np.exp(-cfg.r * times)).sum(axis=(1, 2))
                actual = gross @ discount - repayments_pv + terminal * discount[-1]
                row["settlement"] = {
                    "enabled": p.restitution,
                    "initial_regime": int(start_regime),
                    "discount_factor": settlement_discount(cfg.r),
                    "mean_annual_accrual_usd": balances.mean(axis=0).tolist(),
                    "mean_annual_repayment_usd": np.r_[0, balances.mean(axis=0)].tolist(),
                    "mean_gross_operating_pv_usd": float((gross @ discount + terminal * discount[-1]).mean()),
                    "mean_repayments_pv_usd": float(repayments_pv.mean()),
                    "mean_final_year_accrual_usd": float(balances[:, -1].mean()),
                    "mean_tail_repayment_pv_usd": float((balances[:, -1] * discount[-1] * settlement_discount(cfg.r)).mean()),
                    "max_accounting_error_usd": float(np.max(np.abs(actual - v0[start_regime]))),
                }
        row["premium_new"] = row["switch_new_1yr"] - max(v_spot, v_mep)
        row["decree_gain"] = row["switch_new_1yr"] - row["switch_old_4yr"]
        out[label] = row

    # 1. PV energy stream with the energy-balance liability (2-var basis)
    pv_gross = {0: lambda t: pv_rev(p, xs[:, t]),
                1: lambda t: pv_rev(p, xm[:, t])}
    pv_funcs = {0: pv_gross[0], 1: lambda t: net_mep_revenue(
        p, pv_gross[1](t), saldo_balance(p, xs[:, t], xm[:, t], "pv"))}
    cols2 = lambda t: [xs[:, t], xm[:, t]]
    analyze("pv", pv_funcs, cols2, cfg.salvage_frac * cfg.ci, ci=cfg.ci, gross_funcs=pv_gross)

    # 2. BESS energy stream (2-var basis); no invest layer (capacity stream
    #    carries the investment case and is regime-independent)
    bess_gross = {0: lambda t: bess_energy_rev(p, xs[:, t], spot=True),
                  1: lambda t: bess_energy_rev(p, xm[:, t], spot=False)}
    bess_funcs = {0: bess_gross[0], 1: lambda t: net_mep_revenue(
        p, bess_gross[1](t), saldo_balance(p, xs[:, t], xm[:, t], "bess_energy"))}
    analyze("bess_energy", bess_funcs, cols2, 0.0, gross_funcs=bess_gross)

    # 3. Integrated PV+BESS, joint regime election (3-var basis)
    def joint(m_spot):
        def f(t):
            x = xs[:, t] if m_spot else xm[:, t]
            energy = pv_rev(p, x) + bess_energy_rev(p, x, spot=m_spot)
            services = p.synergy_revenue * (pv_rev(p, xs[:, t])
                         + bess_energy_rev(p, xs[:, t], spot=True))
            return energy + services + capacity_rev(p, sp[:, t])
        return f
    joint_gross = {0: joint(True), 1: joint(False)}
    joint_funcs = {0: joint_gross[0], 1: lambda t: net_mep_revenue(
        p, joint_gross[1](t), saldo_balance(p, xs[:, t], xm[:, t], "joint"))}
    cols3 = lambda t: [xs[:, t], xm[:, t], sp[:, t]]
    analyze("joint", joint_funcs, cols3, p.combined_salvage, ci=p.ci_combined, gross_funcs=joint_gross)

    # Policy-facing comparison of three remuneration architectures.
    # Flat-price stabilization is represented by the paper's
    # stable monomic-price calibration (67 USD/MWh, sigma 0.116267).
    # Spot-only and dual switching
    # use the same spot and MEP paths as the switching analysis above.
    rng = np.random.default_rng(seed)
    z_g = rng.standard_normal((cfg.n_paths, cfg.t_years))
    log_g = np.cumsum(
        (cfg.mu_mep - 0.5 * p.flat_sigma**2) + p.flat_sigma * z_g,
        axis=1,
    )
    xg = np.hstack([
        np.full((cfg.n_paths, 1), p.flat_s0),
        p.flat_s0 * np.exp(log_g),
    ])
    cols_g_pv = lambda t: [xg[:, t]]
    cols_g_joint = lambda t: [xg[:, t], sp[:, t]]

    pv_flat = lambda t: pv_rev(p, xg[:, t])
    joint_flat = lambda t: (
        (1 + p.synergy_revenue)
        * (pv_rev(p, xg[:, t]) + bess_energy_rev(p, xg[:, t], spot=False))
        + capacity_rev(p, sp[:, t])
    )

    if collect_diagnostics:
        diagnostic_npvs["flat_stabilization"] = {
            "pv": fixed_generic(p, pv_flat,
                                cfg.salvage_frac * cfg.ci) - cfg.ci,
            "joint": fixed_generic(p, joint_flat,
                                   p.combined_salvage) - p.ci_combined,
        }
        diagnostic_npvs["spot_only"] = {
            "pv": fixed_generic(p, pv_funcs[0],
                                cfg.salvage_frac * cfg.ci) - cfg.ci,
            "joint": fixed_generic(p, joint_funcs[0],
                                   p.combined_salvage) - p.ci_combined,
        }

    def fixed_row(regime, asset, rev, cols, terminal, ci):
        cash, ex_t, diag = fixed_investment_option(
            p, rev, cols, terminal, ci,
            diagnostic_years=diagnostic_years,
        )
        if collect_diagnostics and regime in diagnostic_paths:
            diagnostic_paths[regime][asset] = cash.copy()
            diagnostic_continuation[regime][asset] = diag.get(diagnostic_year)
        exercised = ex_t[ex_t >= 0]
        return {
            "option_value": float(cash.mean()),
            "exercise_rate": float((ex_t >= 0).mean()),
            "mean_exercise_time": (
                float(exercised.mean()) if exercised.size else float("nan")
            ),
            **deferral_metrics(cash.mean(),
                               fixed_generic(p, rev, terminal).mean() - ci),
        }

    flat = {
        "pv": fixed_row("flat_stabilization", "pv",
                        pv_flat, cols_g_pv,
                        cfg.salvage_frac * cfg.ci, cfg.ci),
        "joint": fixed_row("flat_stabilization", "joint",
                           joint_flat, cols_g_joint,
                           p.combined_salvage, p.ci_combined),
    }
    spot_only = {
        "pv": fixed_row("spot_only", "pv", pv_funcs[0], cols2,
                        cfg.salvage_frac * cfg.ci, cfg.ci),
        "joint": fixed_row("spot_only", "joint", joint_funcs[0], cols3,
                           p.combined_salvage, p.ci_combined),
    }
    out["fixed_mep_investment"] = {
        "pv": fixed_row("fixed_mep", "pv", pv_funcs[1], cols2,
                        cfg.salvage_frac * cfg.ci, cfg.ci),
        "joint": fixed_row("fixed_mep", "joint", joint_funcs[1], cols3,
                           p.combined_salvage, p.ci_combined),
    }
    # Compare whole feasible policies ex ante, never select pathwise hindsight.
    # A finite-sample fitted switching policy can underperform simply staying spot.
    for asset in ("pv", "joint"):
        row = out[asset]
        row["raw_switching_option"] = {
            "option_value": row["opt_new_1yr"],
            "exercise_rate": row["opt_new_1yr_pex"],
            "mean_exercise_time": row["opt_new_1yr_mean_t"],
        }
        row["investment_policy"] = "fitted_switching"
        if spot_only[asset]["option_value"] > row["opt_new_1yr"]:
            row["investment_policy"] = "fixed_spot_fallback"
            for key, source in (("opt_new_1yr", "option_value"),
                                ("opt_new_1yr_pex", "exercise_rate"),
                                ("opt_new_1yr_mean_t", "mean_exercise_time")):
                row[key] = spot_only[asset][source]
            if collect_diagnostics:
                diagnostic_paths["dual_switching"][asset] = diagnostic_paths["spot_only"][asset].copy()
                diagnostic_continuation["dual_switching"][asset] = diagnostic_continuation["spot_only"][asset]
    dual = {}
    for asset, ci in (("pv", cfg.ci), ("joint", p.ci_combined)):
        row = out[asset]
        dual[asset] = {
            "option_value": row["opt_new_1yr"],
            "exercise_rate": row["opt_new_1yr_pex"],
            "mean_exercise_time": row["opt_new_1yr_mean_t"],
            # Initial regime choice uses expected operating values, not hindsight.
            **deferral_metrics(row["opt_new_1yr"], row["switch_new_1yr"] - ci),
        }
    out["regime_comparison"] = {
        "flat_stabilization": flat,
        "spot_only": spot_only,
        "dual_switching": dual,
    }

    if collect_diagnostics:
        out["diagnostics"] = {
            "year": diagnostic_year,
            "distributions": {
                regime: {
                    asset: _empirical_distribution(values)
                    for asset, values in assets.items()
                }
                for regime, assets in diagnostic_paths.items()
            },
            "npv_distributions": {
                regime: {
                    asset: _empirical_distribution(values)
                    for asset, values in assets.items()
                }
                for regime, assets in diagnostic_npvs.items()
            },
            "continuation": {
                regime: {
                    asset: _continuation_bins(diag)
                    for asset, diag in assets.items()
                }
                for regime, assets in diagnostic_continuation.items()
            },
        }

    return out


def restitution_comparison(p: CaseParams = CaseParams(), seed: int = SEED):
    """Common-path comparison; the historical flat package changes price inputs."""
    settled = run_all(replace(p, restitution=True), seed=seed)
    supported = run_all(replace(p, restitution=False), seed=seed)
    return {
        "seed": seed, "n_paths": p.base.n_paths,
        "scope": "Common price paths and current assumptions for block-price cases; historical flat is a separate calibration. No welfare or aggregate entry model.",
        "regimes": {
            "historical_flat": settled["regime_comparison"]["flat_stabilization"],
            "spot_only": settled["regime_comparison"]["spot_only"],
            "fixed_mep_no_restitution": supported["fixed_mep_investment"],
            "switching_no_restitution": supported["regime_comparison"]["dual_switching"],
            "switching_with_restitution": settled["regime_comparison"]["dual_switching"],
        },
        "ledger_checks": {
            str(enabled): {asset: result[asset]["settlement"]["max_accounting_error_usd"]
                           for asset in ("pv", "bess_energy", "joint")}
            for enabled, result in ((True, settled), (False, supported))
        },
    }


def make_restitution_comparison_figure(comparison):
    keys = list(comparison["regimes"])
    labels = ["Historical flat\n(no restitution)", "Spot only",
              "Fixed block MEP\n(no restitution)", "Switching\n(no restitution)",
              "Switching\n(with restitution)"]
    x, width = np.arange(len(keys)), .36
    fig, axes = plt.subplots(2, 1, figsize=(10.2, 6.4), sharex=True)
    for j, (asset, label, color) in enumerate((("pv", "PV", "#D97706"),
                                              ("joint", "Integrated PV+BESS", "#6D28D9"))):
        values = [comparison["regimes"][key][asset] for key in keys]
        axes[0].bar(x + (j - .5) * width, [100*v["exercise_rate"] for v in values], width, label=label, color=color)
        axes[1].bar(x + (j - .5) * width, [v["mean_exercise_time"] for v in values], width, color=color)
    axes[0].set_ylabel("Simulated exercise rate (%)")
    axes[1].set_ylabel("Mean time if exercised (yr)")
    axes[0].legend(frameon=False, fontsize=11)
    axes[1].set_xticks(x, labels, fontsize=11)
    for ax in axes:
        ax.grid(axis="y", alpha=.22)
        ax.axvline(.5, color="#64748B", linestyle=":", linewidth=1)
    fig.tight_layout()
    _save_figure(fig, "fig_restitution_comparison")


def sensitivity(base: CaseParams, seed: int = SEED) -> list:
    rows = []
    for sigma in (0.25, 0.35, 0.45):
        cfg = SwitchConfig(**{**base.base.__dict__, "sigma_spot": sigma})
        r = run_all(CaseParams(**{**base.__dict__, "base": cfg}), seed=seed)
        for label in ("pv", "bess_energy", "joint"):
            rows.append({"sigma_spot": sigma, "case": label,
                         "premium_new": r[label]["premium_new"],
                         "decree_gain": r[label]["decree_gain"]})
            logger.info("  sens sigma=%.2f %-12s premium=%.3fM gain=%.3fM",
                        sigma, label, rows[-1]["premium_new"] / 1e6,
                        rows[-1]["decree_gain"] / 1e6)
    return rows


def make_figure(res: dict) -> None:
    labels = ["Spot only", "MEP only", "Switch 4 yr", "Switch 1 yr"]
    keys = ["spot_only", "mep_only", "switch_old_4yr", "switch_new_1yr"]
    cases = [("pv", "PV energy stream"),
             ("bess_energy", "BESS energy stream"),
             ("joint", "Integrated PV+BESS")]
    colors = ["#888888", "#bbbbbb", "#4477aa", "#228833"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    for ax, (key, title) in zip(axes, cases):
        vals = [res[key][k] / 1e6 for k in keys]
        ax.bar(labels, vals, color=colors)
        ax.set_yscale('log')
        for i, v in enumerate(vals):
            ax.text(i, v * 1.15, f"{v:.2f}", ha="center", fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", labelsize=7, rotation=20)
        # Ensure y-axis ticks look nice on log scale
        ax.yaxis.set_major_formatter(plt.ScalarFormatter())
    axes[0].set_ylabel("Operating value (USD M)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "fig_switching_cases.png"), dpi=200)
    plt.close(fig)


def make_regime_figure(res: dict) -> None:
    """Policy-facing comparison without calling exercise a market probability."""
    regimes = ["Historical flat\n(no restitution)", "Spot only", "Dual with\nBalance MEP"]
    regime_keys = ["flat_stabilization", "spot_only", "dual_switching"]
    cases = [("pv", "PV"), ("joint", "Integrated PV+BESS")]
    colors = ["#d95f02", "#7570b3", "#1b9e77"]
    data = res["regime_comparison"]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8))
    width = 0.36
    x = np.arange(len(regimes))
    for j, (case, label) in enumerate(cases):
        rates = [100 * data[k][case]["exercise_rate"] for k in regime_keys]
        axes[0].bar(x + (j - 0.5) * width, rates, width,
                    label=label, color=colors[j])
        times = [data[k][case]["mean_exercise_time"] for k in regime_keys]
        axes[1].bar(x + (j - 0.5) * width, times, width,
                    label=label, color=colors[j])
    axes[0].set_ylabel("Simulated exercise rate (%)")
    axes[1].set_ylabel("Mean time if exercised (yr)")
    for ax in axes:
        ax.set_xticks(x, regimes)
        ax.tick_params(axis="x", labelsize=11)
        ax.grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False, fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "fig_three_regimes_v8.png"), dpi=300)
    plt.close(fig)


def _save_figure(fig, stem: str) -> None:
    """Save a vector paper figure and a high-resolution app/preview copy."""
    fig.savefig(os.path.join(OUTPUT_DIR, f"{stem}.pdf"), bbox_inches="tight")
    fig.savefig(os.path.join(OUTPUT_DIR, f"{stem}.png"), dpi=300,
                bbox_inches="tight")
    plt.close(fig)


def make_diagnostic_figures(res: dict, sens: list) -> None:
    """Distribution, continuation-regression, and sensitivity diagnostics."""
    diagnostics = res["diagnostics"]
    regimes = [
        ("flat_stabilization", "Flat-price stabilization", "#D55E00", "-"),
        ("spot_only", "Spot-only remuneration", "#64748B", "--"),
        ("dual_switching", "Dual with Balance MEP", "#0072B2", "-."),
    ]
    assets = [("pv", "PV"), ("joint", "Integrated PV+BESS")]

    def distribution_figure(key, stem, xlabel, allow_negative=False):
        fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.2),
                                 layout="constrained")
        for row, (asset, asset_label) in enumerate(assets):
            ax_pdf, ax_cdf = axes[row]
            pooled_p01 = min(
                diagnostics[key][regime][asset].get("p01",
                    diagnostics[key][regime][asset]["p05"])
                for regime, _, _, _ in regimes
            )
            pooled_p99 = max(
                diagnostics[key][regime][asset]["p99"]
                for regime, _, _, _ in regimes
            )
            span = max(pooled_p99 - pooled_p01, 1e-6)
            x_min = pooled_p01 - 0.05 * span if allow_negative else 0.0
            x_max = pooled_p99 + 0.05 * span
            for regime, label, color, linestyle in regimes:
                dist = diagnostics[key][regime][asset]
                if key == "distributions":
                    zero = 100 * dist["zero_mass"]
                    legend = f"{label} (zero={zero:.1f}%)"
                else:
                    negative = 100 * dist["negative_mass"]
                    legend = f"{label} (NPV<0={negative:.1f}%)"
                if abs(dist["p99"] - dist["p01"]) < 1e-10:
                    # A deterministic option value is a probability atom, not
                    # an ordinary density. Draw its Dirac mass as a vertical
                    # marker so the continuous histograms remain readable.
                    ax_pdf.axvline(dist["mean"], color=color,
                                   linestyle=linestyle, linewidth=2.2,
                                   label=legend)
                else:
                    ax_pdf.step(dist["pdf_x"], dist["pdf_y"], where="mid",
                                color=color, linestyle=linestyle, linewidth=1.8,
                                label=legend)
                ax_cdf.plot(dist["cdf_x"], dist["cdf_y"], color=color,
                            linestyle=linestyle, linewidth=1.8, label=label)
            panel = 2 * row
            ax_pdf.set_title(f"({chr(97 + panel)}) {asset_label}: PDF",
                             loc="left", fontweight="bold", pad=7)
            ax_cdf.set_title(f"({chr(98 + panel)}) {asset_label}: CDF",
                             loc="left", fontweight="bold", pad=7)
            ax_pdf.set_ylabel("Empirical density")
            ax_cdf.set_ylabel("Cumulative probability")
            for ax in (ax_pdf, ax_cdf):
                ax.set_xlabel(xlabel)
                ax.set_xlim(left=x_min, right=x_max)
                ax.axvline(0, color="#334155", linewidth=0.8,
                           linestyle=":")
                ax.grid(axis="y", alpha=0.22)
            ax_pdf.legend(frameon=False, fontsize=11, loc="upper right")
        _save_figure(fig, stem)

    distribution_figure(
        "distributions", "fig_v8_option_pdf_cdf",
        "Option value (USD M)", allow_negative=False,
    )
    distribution_figure(
        "npv_distributions", "fig_v8_npv_pdf_cdf",
        "Immediate NPV (USD M)", allow_negative=True,
    )

    fig, axes = plt.subplots(2, 3, figsize=(12.2, 6.8), sharey="row")
    for row, (asset, asset_label) in enumerate(assets):
        for col, (regime, label, _, _) in enumerate(regimes):
            ax = axes[row, col]
            diag = diagnostics["continuation"][regime][asset]
            ax.plot(diag["state"], diag["exercise_payoff"], color="#D97706",
                    linewidth=1.9, marker="o", markersize=3,
                    label="Exercise payoff")
            ax.plot(diag["state"], diag["continuation_value"], color="#1E40AF",
                    linewidth=1.9, linestyle="--", marker="s", markersize=3,
                    label="Continuation value")
            panel = row * 3 + col
            ax.text(0.02, 0.96, f"({chr(97 + panel)}) {asset_label}\n{label}",
                    transform=ax.transAxes, va="top", fontsize=11,
                    fontweight="bold")
            state_label = ("Flat-price stabilization\n(USD/MWh)"
                           if regime == "flat_stabilization"
                           else "Generation-weighted spot price\n(USD/MWh)")
            ax.set_xlabel(state_label)
            if col == 0:
                ax.set_ylabel("Conditional value (USD M)")
            ax.grid(axis="y", alpha=0.22)
            if row == 0 and col == 0:
                ax.legend(frameon=False, fontsize=11, loc="lower right")
    fig.tight_layout()
    _save_figure(fig, "fig_v8_continuation_sensitivity")

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    asset_styles = [
        ("pv", "PV", "#D97706", "o", "-"),
        ("bess_energy", "BESS energy stream", "#6D28D9", "s", "--"),
        ("joint", "Integrated PV+BESS", "#1E40AF", "^", "-."),
    ]
    for asset, label, color, marker, linestyle in asset_styles:
        rows = sorted((r for r in sens if r["case"] == asset),
                      key=lambda r: r["sigma_spot"])
        sigma = [r["sigma_spot"] for r in rows]
        axes[0].plot(sigma, [r["premium_new"] / 1e6 for r in rows],
                     color=color, marker=marker, linestyle=linestyle,
                     linewidth=1.9, label=label)
        axes[1].plot(sigma, [r["decree_gain"] / 1e6 for r in rows],
                     color=color, marker=marker, linestyle=linestyle,
                     linewidth=1.9, label=label)
    axes[0].text(0.02, 0.96, "(a) Switching premium",
                 transform=axes[0].transAxes, va="top", fontweight="bold")
    axes[1].text(0.02, 0.96, "(b) Minimum-permanence gain",
                 transform=axes[1].transAxes, va="top", fontweight="bold")
    for ax in axes:
        ax.set_xlabel(r"Spot-price volatility $\sigma_S$")
        ax.set_ylabel("Value (USD M)")
        ax.grid(axis="y", alpha=0.22)
    axes[0].legend(frameon=False, fontsize=11, loc="lower right")
    fig.tight_layout()
    _save_figure(fig, "fig_v8_spot_volatility_sensitivity")


def main() -> None:
    t0 = time.time()
    p = CaseParams()
    res = run_all(p, collect_diagnostics=True)
    for label in ("pv", "bess_energy", "joint"):
        row = res[label]
        logger.info("== %s ==", label)
        for k, v in row.items():
            if not isinstance(v, (int, float)):
                logger.info("  %s: %s", k, v)
                continue
            if "pex" in k or "share_spot" in k:
                unit, val = "", v
            elif "switches" in k or "mean_t" in k:
                unit, val = "", v
            else:
                unit, val = " M", v / 1e6
            logger.info("  %-18s %10.4f%s", k, val, unit)
    logger.info("--- sensitivity (sigma_spot) ---")
    sens = sensitivity(p)
    make_figure(res)
    make_regime_figure(res)
    make_diagnostic_figures(res, sens)
    make_restitution_comparison_figure(restitution_comparison(p))

    with open(os.path.join(OUTPUT_DIR, "results_switching_cases.txt"), "w") as f:
        f.write("Switching analyses with twelve-month Balance MEP restitution\n")
        f.write(f"seed={SEED}, n_paths={p.base.n_paths}, T={p.base.t_years}\n\n")
        for label in ("pv", "bess_energy", "joint"):
            row = res[label]
            f.write(f"[{label}]\n")
            for k, v in row.items():
                text_value = f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
                f.write(f"  {k}: {text_value}\n")
        f.write("\n[regime_comparison]\n")
        for regime, assets in res["regime_comparison"].items():
            f.write(f"  {regime}\n")
            for asset, metrics in assets.items():
                f.write(f"    {asset}: {metrics}\n")
        f.write("\n[distribution_diagnostics]\n")
        for regime, assets in res["diagnostics"]["distributions"].items():
            for asset, metrics in assets.items():
                f.write(
                    f"  {regime}/{asset}: mean={metrics['mean']:.6f}M, "
                    f"median={metrics['median']:.6f}M, "
                    f"p05={metrics['p05']:.6f}M, "
                    f"p95={metrics['p95']:.6f}M, "
                    f"zero_mass={metrics['zero_mass']:.6f}\n"
                )
        f.write("\n[npv_distribution_diagnostics]\n")
        for regime, assets in res["diagnostics"]["npv_distributions"].items():
            for asset, metrics in assets.items():
                f.write(
                    f"  {regime}/{asset}: mean={metrics['mean']:.6f}M, "
                    f"median={metrics['median']:.6f}M, "
                    f"p05={metrics['p05']:.6f}M, "
                    f"p95={metrics['p95']:.6f}M, "
                    f"negative_mass={metrics['negative_mass']:.6f}\n"
                )
        f.write(f"\n[continuation_diagnostics_year_{res['diagnostics']['year']}]\n")
        for regime, assets in res["diagnostics"]["continuation"].items():
            for asset, metrics in assets.items():
                f.write(f"  {regime}/{asset}: n_itm={metrics['n_itm']}\n")
        f.write("\nSensitivity:\n")
        for r in sens:
            f.write(f"{r}\n")
    logger.info("done in %.1fs -> results_switching_cases.txt", time.time() - t0)


if __name__ == "__main__":
    main()
