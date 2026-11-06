# PMGD BESS Policy Lab

Companion to the manuscript **Stabilization, Switching, and
Restitution: Lessons from Chile for Distributed PV-Storage Investment**,
app revision 16 October 2026. The app calls the manuscript's scientific
implementation directly; the API converts display units and attaches provenance.

[Open the app](https://pmgd-bess-policy-lab.vercel.app)

## Features

- Five investment configurations: historical flat, spot only, fixed time-block
  MEP without restitution, switching without restitution, and switching with
  Balance MEP restitution. Historical flat has a separate calibration.
- Immediate NPV, total investment-option value, exclusive waiting premium
  `F0 - max(N0, 0)`, forced-immediate gap and avoided negative NPV for PV/PV+BESS.
- **Load paper prices ×2**, then **Run model**, reproduces the positive-NPV
  sensitivity (spot 50, MEP 90 USD/MWh), resetting other displayed inputs to
  the paper defaults. Historical flat remains separately calibrated.
- Net operating values, signed Balance MEP settlement, twelve following-year
  monthly installments and payments after the operating horizon.
- Conditional policy interpretation: support, reversible market access and
  repayment are separate choices. Switching alone does not prevent excessive
  deployment. No welfare optimum or aggregate deployment forecast is estimated.
- JSON and CSV exports include all five policies; CSV includes the 576 mean
  monthly installment records for the 15-year baseline (three energy streams).

## Run locally

Backend:

```bash
cd backend
python3 -m pip install -r requirements.txt
MPLCONFIGDIR=/tmp/pmgd-mpl OPENBLAS_NUM_THREADS=1 python3 -m uvicorn app:app --port 8811
```

Frontend (another terminal):

```bash
cd frontend
npm ci
npm run dev
```

The frontend defaults to `http://localhost:8811`. Set `NEXT_PUBLIC_API_URL`
before building if another backend is required. The app provides JSON and CSV
exports of model results.

## Verify

```bash
cd backend
MPLCONFIGDIR=/tmp/pmgd-mpl OPENBLAS_NUM_THREADS=1 python3 -m unittest discover -v
cd ../frontend
npm test
npm run build
```

Parity tests compare fresh calculations with archived manuscript results at
seed 42 and 5,000 paths, test the positive-NPV timing contrast, verify monthly
settlement and reject invalid inputs. Frontend tests reject the previous API
contract before it can be rendered. Parameter changes create new results;
those are scenarios, not empirical recalibrations.

## Authoritative scientific source

The authoritative scripts are in the revised manuscript's `replication/`
directory, NOT the older scripts next to this app. To synchronize a future
approved scientific revision, set its actual directory explicitly:

```bash
PMGD_REPLICATION_DIR="/absolute/path/to/revised-manuscript/replication"
cp "$PMGD_REPLICATION_DIR/lsmc_switching.py" "$PMGD_REPLICATION_DIR/lsmc_switching_cases.py" backend/
cp "$PMGD_REPLICATION_DIR/test_saldo_mep.py" backend/
```

`backend/paper_reference.json` is an archived reference for the current paper,
not simulation input. Update it from verified manuscript outputs only when the
manuscript changes, then rerun all checks. `/healthz`, `/api/meta` and every run
identify revision `ieee-access-2026-10-16` and the scientific-source SHA-256.
The run ID includes revision, sources, seed, parameters and sensitivity option.
