# PMGD–BESS Policy Replication Lab — frontend

Next.js 16 interface for the manuscript-v8 LSMC experiment. It presents the
three remuneration architectures, switching decomposition, volatility
sensitivity, option/NPV PDF and CDF charts, continuation-value diagnostics,
and a complete run audit.

```bash
npm ci
npm run dev
```

The API defaults to `http://localhost:8811`. Override it in `.env.local`:

```text
NEXT_PUBLIC_API_URL=https://your-api.example
```

Production verification:

```bash
npm run build
```

The UI provides exact tables behind every chart and exports JSON and CSV with
the seed, inputs, run ID and model fingerprint.
