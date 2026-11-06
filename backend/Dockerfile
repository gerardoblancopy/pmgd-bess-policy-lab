# PMGD-BESS Real Options API — Hugging Face Docker Space
FROM python:3.12-slim

RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --chmod: some sources are 600 on the host; the container runs as non-root
COPY --chmod=644 lsmc_switching.py lsmc_switching_cases.py simcore.py app.py test_parity.py test_saldo_mep.py paper_reference.json ./

# lsmc scripts create OUTPUT_DIR at import; point it somewhere writable
ENV PMGD_OUTPUT_DIR=/tmp/pmgd_out
ENV MPLCONFIGDIR=/tmp/mpl
ENV OPENBLAS_NUM_THREADS=1

USER user
EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
