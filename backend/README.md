---
title: PMGD-BESS Policy Replication API
emoji: 🔋
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# PMGD–BESS IEEE Access companion API

Local scientific revision `ieee-access-2026-10-16`. The FastAPI adapter calls
the same `lsmc_switching_cases.py` as the revised manuscript, with full signed
Balance MEP settlement and fixed-regime deferral controls.

- `GET /healthz`: revision and scientific-source SHA-256.
- `GET /api/meta`: parameter schema and archived manuscript comparison.
- `POST /api/run`: five-policy comparison, immediate NPV and pure deferral
  decomposition; net operating values and settlement ledger; three-architecture
  diagnostics and optional spot-volatility grid.

Request the baseline with `{"params":{},"seed":42,"with_sensitivity":true}`.
For the positive-NPV sensitivity, use `s0_spot=50` and `s0_mep=90`; all other
inputs and random shocks remain unchanged. Historical flat stays separate.

Monetary display fields ending `_musd` are million USD. Settlement fields
ending `_usd` are USD. Exercise rates are shares, not market entry forecasts;
conditional exercise time is null when no simulated path exercises.

Set `ALLOWED_ORIGINS` to restrict CORS. Supported parameters are bounded for
deployment, unknown parameters remain ignored for compatibility, and nonfinite
inputs are rejected. Exported `params_used` records the actual bounded values.

Run `MPLCONFIGDIR=/tmp/pmgd-mpl OPENBLAS_NUM_THREADS=1 python3 -m unittest discover -v`.
The Docker image includes the reference JSON. The manuscript is kept private;
the API exposes no manuscript download endpoint or PDF asset.
See the top-level README for the authoritative `replication/` source directory.
