import type { RegimeKey, SwitchingAssetKey, PolicyKey } from "@/lib/api";

export const REGIMES: ReadonlyArray<{ key: RegimeKey; label: string }> = [
  { key: "flat_stabilization", label: "Historical flat (separate calibration)" },
  { key: "spot_only", label: "Spot-only remuneration" },
  { key: "dual_switching", label: "Switching with Balance MEP restitution" },
];

export const POLICIES: ReadonlyArray<{ key: PolicyKey; label: string; shortLabel: string }> = [
  { key: "historical_flat", label: "Historical flat, no restitution (separate calibration)", shortLabel: "Historical flat" },
  { key: "spot_only", label: "Spot only, deferral only", shortLabel: "Spot only" },
  { key: "fixed_mep_no_restitution", label: "Fixed time-block MEP, no restitution", shortLabel: "Fixed MEP / no restitution" },
  { key: "switching_no_restitution", label: "Switching, no restitution", shortLabel: "Switching / no restitution" },
  { key: "switching_with_restitution", label: "Switching with Balance MEP restitution", shortLabel: "Switching / restitution" },
];

export const ASSETS: ReadonlyArray<{ key: SwitchingAssetKey; label: string }> = [
  { key: "pv", label: "PV" },
  { key: "bess_energy", label: "BESS energy stream" },
  { key: "joint", label: "Integrated PV+BESS" },
];

export const SWITCHING_SERIES = {
  spotOnly: "Spot-only remuneration",
  stabilizedOnly: "Stabilized remuneration (MEP)",
  formerRule: "Four-year permanence (same restitution)",
  reform2026: "One-year permanence (same restitution)",
} as const;

export const GLOSSARY = [
  {
    title: "Investment values and decisions",
    entries: [
      ["N₀ · Immediate NPV", "Expected net present value of investing today, after the asset's investment cost and with the operating rights of the selected policy. It can be negative. NPV is VPN (valor presente neto) in Spanish."],
      ["U₀ = max(N₀, 0)", "Best value available today from investing immediately or rejecting the project. Rejection is valued at zero."],
      ["F₀ · Investment-option value", "Total value of the right to invest now or later, or never invest. Switching policies also include the operating choice after investment. F₀ is not the exclusive deferral premium."],
      ["Πwait = F₀ − max(N₀, 0)", "Exclusive deferral premium: the additional value of retaining the right to invest later, relative to the best immediate invest-or-reject decision. Both benchmarks retain identical operating rights."],
      ["F₀ − N₀ · Forced-immediate gap", "Value difference against compulsory investment today. It includes the exclusive deferral premium plus max(−N₀, 0), the value of avoiding a negative immediate NPV."],
      ["Exercise rate", "Share of simulated paths on which the investment policy invests at an allowed date. It is not a forecast investment probability, a market entry rate, or the share investing immediately."],
      ["Mean investment time · τ", "Average investment date among paths that invest, measured in years from today. Zero means immediate investment. Not exercised means no path invests; it does not mean year zero."],
      ["Operating switching premium", "Net operating value with one-year switching minus the better fixed remuneration regime, with the same restitution treatment in both benchmarks. This is distinct from the investment-deferral premium."],
      ["Permanence gain", "Net operating value with one-year minimum permanence minus the value with four-year permanence, holding the same restitution schedule fixed. It does not measure the benefit of the entire regulatory reform."],
      ["Terminal spot share", "Share of operating-policy paths remunerated at spot at the final operating date. This migration diagnostic is distinct from investment exercise."],
      ["Mean switches per path", "Average number of remuneration-regime changes along an operating-policy path. It counts operating choices, not new investments."],
    ],
  },
  {
    title: "Policy configurations and settlement",
    entries: [
      ["Historical flat", "Historical monomic-price benchmark without restitution, using a separate price calibration. Flat refers to the remuneration shape, not an absence of price uncertainty. It is not a current new-project entitlement or a matched control for switching alone."],
      ["Spot-only", "The project remains under spot remuneration, with no switching or stabilization restitution. The investor may still defer entry."],
      ["MEP-only · Fixed time-block MEP", "The project remains under time-block stabilized remuneration without restitution in this controlled counterfactual. Fixed refers to the regime; the stabilized price still follows its simulated process. Investment may be deferred."],
      ["Switching without restitution", "Investment deferral plus reversible MEP–spot operating choice, retaining the modeled stabilization price differences without a repayment obligation."],
      ["Switching with restitution", "The same reversible operating choice with Balance MEP settlement. A switch to spot stops new stabilization accruals but preserves previous repayment obligations."],
      ["Balance MEP · Bₜ", "Signed stabilization energy balance: modeled metered net-energy revenue under MEP minus its spot counterpart while MEP is selected. Positive is payable; negative is receivable. Capacity income and other non-energy items are excluded."],
      ["Restitution and liability runoff", "The app aggregates balances annually and schedules twelve monthly installments in the following year. Accrued obligations survive switching and the final operating date; outstanding installments remain in valuation."],
      ["q(r)", "Present-value factor for twelve next-year monthly installments: q(r) = (1/12) Σₖ₌₁¹² exp(−rk/12). It discounts settlement timing; it is not a reduction of the principal owed."],
      ["Minimum permanence", "Minimum time in a remuneration regime before a modeled change is permitted. The controlled operating comparison uses one versus four years with identical restitution."],
      ["Prices ×2 preset", "Sets initial spot and time-block MEP prices to 50 and 90 USD/MWh and restores the other paper inputs and seed 42. The separately calibrated historical flat price and the capacity price are not doubled."],
    ],
  },
  {
    title: "Price, project and simulation notation",
    entries: [
      ["X₀ˢ, X₀ᴹ, X₀ᴾ", "Initial spot energy price, stabilized energy price and capacity price. Energy inputs are generation-weighted reference prices in USD/MWh; capacity is quoted in USD/(MW·year)."],
      ["σ_S, σ_M, σ_P", "Annualized volatilities of the spot, stabilized and capacity price processes. A value of 0.35 means 35% annualized volatility, not 35% expected price growth."],
      ["ρ_SM", "Correlation between the simulated spot and stabilized price shocks. It does not measure the level difference between their prices."],
      ["r", "Real, continuously compounded appraisal discount rate per year. A value of 0.05 denotes a 5% rate."],
      ["T", "Final operating date in years. The modeled investment dates are 0 through T−1; installments already owed may extend beyond T."],
      ["G · Annual PV generation", "Annual photovoltaic energy production, in MWh/year, before the model's marginal-loss adjustment."],
      ["CI · Investment cost", "Upfront capital cost in USD. PV and integrated PV+BESS have separate investment-cost inputs."],
      ["Capacity-sufficiency factor", "Scenario factor approximating the battery's accredited capacity relative to its power limit. It is a simplified modeling input, not a full regulatory accreditation calculation."],
      ["u · Joint energy-revenue uplift", "Scenario proxy for co-located services, not an estimated causal synergy. In the four matched time-block/spot cases its base is independent of the elected energy regime; the historical flat benchmark uses its own base."],
      ["Monte Carlo paths · N", "Number of simulated price trajectories used to estimate values and policies. More paths improve numerical sampling; they do not remove uncertainty in model assumptions."],
      ["Random seed", "Initialization of the pseudo-random price draws. Reproduction requires the same seed, inputs, model version and numerical environment."],
      ["Continuation value", "LSMC regression estimate of the value of keeping the investment option alive rather than exercising at the current date. Displayed continuation curves are in-sample diagnostics."],
      ["P5 and P95", "Fifth and ninety-fifth percentiles of the simulated distribution. They describe model outcomes and are not confidence bounds for a market forecast."],
    ],
  },
  {
    title: "Acronyms and units",
    entries: [
      ["BESS", "Battery energy storage system."],
      ["CAPEX", "Capital expenditure; the upfront investment cost."],
      ["CDF", "Cumulative distribution function: the share of simulated outcomes at or below a given value."],
      ["CPI", "Consumer price index. CPI-indexed settlement is represented in constant purchasing-power units under the paper's real-currency assumptions."],
      ["FPM", "Marginal-loss adjustment factor (factor de penalización marginal), applied to PV energy revenue."],
      ["GBM", "Geometric Brownian motion, the stochastic process used to simulate price uncertainty."],
      ["ITM", "In the money: states with a positive immediate exercise payoff used in the LSMC continuation regression."],
      ["LSMC", "Least squares Monte Carlo, the simulation-and-regression method used to estimate exercise and switching policies."],
      ["MEP", "Price-stabilization mechanism (mecanismo de estabilización de precios)."],
      ["O&M", "Operation and maintenance costs, normally quoted per year."],
      ["PDF", "Probability density function in the distribution charts."],
      ["PMGD", "Small distributed generators under the Chilean framework (Pequeños Medios de Generación Distribuida)."],
      ["PV / PV+BESS", "Photovoltaic generation / the integrated photovoltaic and battery-storage project. In this app, PV as an asset label does not mean present value."],
      ["USD / M USD", "United States dollars / one million United States dollars. Export fields ending in _musd use million USD; settlement fields ending in _usd use USD."],
      ["MW / MWh", "Megawatt, a unit of power / megawatt-hour, a unit of energy. USD/MWh is an energy price; USD/(MW·year) is an annual capacity price."],
    ],
  },
  {
    title: "Reproducibility and exported files",
    entries: [
      ["CSV / JSON", "Comma-separated values for tabular analysis / JavaScript Object Notation for the structured run record. Exports contain the last completed result, including its recorded inputs."],
      ["Model version / SHA-256", "The human-readable model revision / the cryptographic fingerprint of the scientific source files. Together they identify the model used to produce a run."],
      ["Run ID", "Identifier associated with the model version, source fingerprint, inputs, seed and sensitivity setting. It distinguishes result records; it is not a measure of statistical accuracy."],
    ],
  },
] as const;
