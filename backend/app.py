"""FastAPI companion API for the IEEE Access manuscript (2026-10-16)."""

import logging
import os
import time
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import simcore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PMGD remuneration-design replication API",
    description=(
        "LSMC replication of five stabilization, switching and Balance MEP restitution "
        "configurations for Chilean PV and PV+BESS, including exclusive investment-deferral premiums."
    ),
    version="3.0.0",
)

_origins = os.environ.get("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _origins.split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    params: Dict[str, float] = Field(default_factory=dict)
    seed: int = Field(default=42, ge=0, le=1_000_000)
    with_sensitivity: bool = True


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "model_version": simcore.MODEL_VERSION,
        "model_sha256": simcore.MODEL_SHA256,
    }


@app.get("/api/meta")
def meta() -> dict:
    return {
        "model_version": simcore.MODEL_VERSION,
        "model_sha256": simcore.MODEL_SHA256,
        "parameters": simcore.parameter_schema(),
        "paper_baseline": simcore.PAPER_BASELINE,
        "replication": {
            "command": "python lsmc_switching_cases.py",
            "source": "lsmc_switching_cases.py",
            "seed": 42,
            "n_paths": 5000,
            "horizon_years": 15,
            "outputs": [
                "results_switching_cases.txt",
                "fig_three_regimes_v8.png",
                "fig_restitution_comparison.pdf",
                "fig_switching_cases.png",
                "fig_v8_option_pdf_cdf.pdf",
                "fig_v8_npv_pdf_cdf.pdf",
                "fig_v8_continuation_sensitivity.pdf",
                "fig_v8_spot_volatility_sensitivity.pdf",
            ],
        },
    }


@app.post("/api/run")
def run(req: RunRequest) -> dict:
    t0 = time.time()
    try:
        result = simcore.run_model(
            req.params,
            seed=req.seed,
            with_sensitivity=req.with_sensitivity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("model run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    result["runtime_s"] = round(time.time() - t0, 3)
    logger.info("run %s completed in %.3fs", result["run_id"], result["runtime_s"])
    return result


# Compatibility alias for bookmarked early prototypes. The response follows
# the current schema above rather than the superseded Cases 1–4 schema.
@app.post("/api/simulate", include_in_schema=False)
def simulate_compat(req: RunRequest) -> dict:
    return run(req)
