# Host State Files

This is a quick reference for the important files under `.aistackd/host/`.

Use it when debugging host bootstrap, model activation, backend launches, control-plane state, or response-follow-up behavior.

## Root Layout

The host runtime state lives under:

```text
.aistackd/host/
```

Important files and directories:

- `runtime.json`
- `installed_models.json`
- `installed_tools.json`
- `backend_installation.json`
- `backend_process.json`
- `control_plane_process.json`
- `model_receipts/`
- `models/`
- `backends/`
- `logs/`
- `responses/`

## Files

### `runtime.json`

The central host runtime record.

What it typically contains:

- the active model selection
- persisted backend tuning defaults
- activation state
- high-level runtime metadata used to rebuild `host` status output

Look here when:

- `host tune show` does not match what you expected
- a persisted tuning override seems stuck
- activation state looks wrong after install or activate

### `installed_models.json`

The managed model inventory.

What it tracks:

- installed model names
- source and acquisition method
- managed artifact paths
- install timestamps and status

Look here when:

- a model appears missing from `aistackd models` or `aistackd host`
- a model path or status looks stale
- you need to confirm what the host thinks is installed

### `installed_tools.json`

The operator-tool inventory for things like `llmfit` and `hf`.

Look here when:

- `host inspect` or bootstrap reports a tool mismatch
- you want to confirm which executable path is currently managed

### `backend_installation.json`

The adopted or managed `llama.cpp` installation record.

What it tracks:

- backend root
- server binary path
- optional CLI binary path
- acquisition method

Look here when:

- backend discovery or acquisition looks wrong
- `host validate` says the backend is stale or missing
- the managed host is launching the wrong `llama-server`

### `backend_process.json`

The last known managed backend-process record.

What it tracks:

- pid and process status
- launch command
- active model and artifact path
- bind host and port
- active backend tuning values
- stop time and exit code when known

Look here when:

- the backend is failing to launch
- tuning flags do not appear to have been applied
- you need the exact launch command used by the managed host

### `control_plane_process.json`

The last known managed control-plane process record.

What it tracks:

- pid and process status
- launch command
- bind host and port
- log path
- stop time and exit code when known

Look here when:

- `host start`, `host stop`, or `host restart --service` behaves unexpectedly
- you need to confirm which flags were passed into the managed control plane

## Directories

### `model_receipts/`

One receipt per installed model.

Useful for:

- acquisition provenance
- confirming how a specific model entered managed state
- debugging mismatches between the inventory and a single installed artifact

### `models/`

Managed model workspaces and artifacts.

Useful for:

- confirming the host-side managed GGUF path
- checking whether an expected artifact is actually present on disk

### `backends/`

Managed backend workspaces.

Typical subtrees include install, extract, source, and build roots for the adopted or acquired backend.

Useful for:

- backend acquisition debugging
- confirming whether a backend came from prebuilt copy, archive extraction, or source fallback

### `logs/`

Persisted log files for the managed backend and control plane.

Typical files:

- `llama-cpp.log`
- `control-plane.log`

These are usually the first place to look when a launch fails.

### `responses/`

Persisted response-follow-up state used for Responses tool-call continuation across control-plane restarts.

Look here when:

- follow-up `previous_response_id` requests fail unexpectedly
- response-state retention or pruning looks wrong

## Practical Debug Flow

When something feels off, this order is usually fastest:

1. Run `PYTHONPATH=src python -m aistackd host`.
2. Check `PYTHONPATH=src python -m aistackd host logs backend --lines 200`.
3. Inspect `backend_process.json` and `control_plane_process.json`.
4. Inspect `runtime.json` for persisted tuning and activation state.
5. Inspect `backend_installation.json` or `installed_models.json` if the problem looks like setup rather than launch.

## Related Docs

- [host-tuning.md](host-tuning.md)
- [gpu-oom-debug-checklist.md](gpu-oom-debug-checklist.md)
- [README.md](../README.md)
