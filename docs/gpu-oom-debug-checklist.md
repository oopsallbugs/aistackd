# GPU OOM Debug Checklist

Use this when `llama-server` fails to start, exits during model load, or reports GPU out-of-memory errors.

## Inspect First

Check the persisted baseline, the live runtime state, and the recent backend log:

```bash
PYTHONPATH=src python -m aistackd host tune show
PYTHONPATH=src python -m aistackd host
PYTHONPATH=src python -m aistackd host logs backend --lines 200
```

If the control plane is already running, the same state is also visible at `GET /admin/runtime`.

## Start With The Cheap Reductions

The safest first steps are the knobs that directly reduce prompt-time memory pressure:

- lower `--backend-context-size`
- lower `--backend-predict-limit`
- keep `--backend-parallel` at `1` while debugging
- lower `--backend-batch-size`
- lower `--backend-ubatch-size`

For a one-off experiment, restart the service with tighter limits:

```bash
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host restart --service \
  --backend-context-size 16384 \
  --backend-predict-limit 2048 \
  --backend-parallel 1 \
  --backend-batch-size 512 \
  --backend-ubatch-size 256
```

If that stabilizes the load, persist the same settings:

```bash
PYTHONPATH=src python -m aistackd host tune set \
  --backend-context-size 16384 \
  --backend-predict-limit 2048 \
  --backend-parallel 1 \
  --backend-batch-size 512 \
  --backend-ubatch-size 256
```

## If VRAM Is Still The Bottleneck

Use the advanced pass-through controls exposed by `aistackd`:

- lower `--backend-gpu-layers`; set `0` to confirm the failure is GPU-memory-specific
- try `--backend-no-kv-offload` if KV cache placement is the problem
- try `--backend-no-op-offload` if operator placement is the problem
- use `--backend-kv-offload` and `--backend-op-offload` to force those paths back on while comparing runs
- experiment with `--backend-fit-target`
- experiment with `--backend-cache-ram`

Example:

```bash
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host restart --service \
  --backend-context-size 16384 \
  --backend-predict-limit 2048 \
  --backend-batch-size 512 \
  --backend-ubatch-size 256 \
  --backend-gpu-layers 0 \
  --backend-no-kv-offload
```

## Make The Result Visible

After each change, confirm what actually launched:

```bash
PYTHONPATH=src python -m aistackd host
PYTHONPATH=src python -m aistackd host logs backend --lines 200
```

`aistackd host` shows:

- `configured_backend_*` for the persisted defaults
- `backend_*` for the currently tracked backend process

`aistackd host serve` also prints the exact `backend_command` it launched.

## Reset To The Baseline

If the tuning experiments get messy, clear the persisted overrides and start again from the documented defaults:

```bash
PYTHONPATH=src python -m aistackd host tune reset
```
