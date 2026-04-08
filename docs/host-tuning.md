# Host Tuning

This guide covers the managed backend tuning workflow exposed through `aistackd host tune`, plus the one-off override flags accepted by `host start`, `host restart`, and `host serve`.

Use this alongside [gpu-oom-debug-checklist.md](gpu-oom-debug-checklist.md) when you are actively debugging load failures or GPU memory pressure.

## Mental Model

There are three layers to keep in mind:

- documented defaults: the built-in baseline used when nothing has been persisted
- persisted tuning: values saved into `.aistackd/host/runtime.json` by `host tune set`
- one-off launch overrides: flags passed directly to `host start`, `host restart`, or `host serve`

Precedence is:

1. one-off launch flags
2. persisted tuning
3. documented defaults

For the optional pass-through knobs, "unset" means `aistackd` does not pass that flag to `llama-server`, so the backend uses its own default behavior.

## Inspect The Current State

Use these commands before changing anything:

```bash
PYTHONPATH=src python -m aistackd host tune show
PYTHONPATH=src python -m aistackd host
PYTHONPATH=src python -m aistackd host logs backend --lines 200
```

What they show:

- `host tune show`: the resolved persisted baseline used by future lifecycle commands
- `host`: both persisted `configured_backend_*` values and the active backend process `backend_*` values
- `host logs backend`: recent backend launch output and model-load failures

In `host tune show` text output, optional pass-through fields are printed as `unset` when they are not currently persisted. That makes the operator-facing distinction visible without reading raw state files:

- `unset`: no persisted override exists for that field
- `False`: `aistackd` is persisting the non-disabled state
- `True`: `aistackd` is persisting the disabled `no_*` state

If the control plane is running, `GET /admin/runtime` and `GET /health` also expose the active backend tuning in JSON.

## Core Knobs

These are the baseline knobs that always resolve to a concrete value:

- `--backend-context-size`
- `--backend-predict-limit`
- `--backend-parallel`

Example:

```bash
PYTHONPATH=src python -m aistackd host tune set \
  --backend-context-size 16384 \
  --backend-predict-limit 2048 \
  --backend-parallel 2
```

## Optional Pass-Through Knobs

These are only passed to `llama-server` when explicitly set:

- `--backend-batch-size`
- `--backend-ubatch-size`
- `--backend-gpu-layers`
- `--backend-fit-target`
- `--backend-cache-ram`
- `--backend-no-kv-offload`
- `--backend-kv-offload`
- `--backend-no-op-offload`
- `--backend-op-offload`

Example:

```bash
PYTHONPATH=src python -m aistackd host tune set \
  --backend-context-size 16384 \
  --backend-predict-limit 2048 \
  --backend-parallel 1 \
  --backend-batch-size 512 \
  --backend-ubatch-size 256 \
  --backend-gpu-layers 0 \
  --backend-no-kv-offload
```

## Clear One Optional Override

You do not need to reset the whole profile just to remove one optional override.

Use the matching clear flag:

- `--clear-backend-batch-size`
- `--clear-backend-ubatch-size`
- `--clear-backend-gpu-layers`
- `--clear-backend-fit-target`
- `--clear-backend-cache-ram`
- `--clear-backend-kv-offload`
- `--clear-backend-op-offload`

Example:

```bash
PYTHONPATH=src python -m aistackd host tune set --clear-backend-batch-size
```

That removes only the persisted batch-size override. The other saved tuning fields remain intact.

## Reset Everything

To remove all persisted tuning and go back to the documented baseline:

```bash
PYTHONPATH=src python -m aistackd host tune reset
```

## One-Off Experiments

Use lifecycle commands when you want to test a configuration without changing the persisted baseline:

```bash
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host restart --service \
  --backend-context-size 16384 \
  --backend-predict-limit 2048 \
  --backend-batch-size 512 \
  --backend-ubatch-size 256 \
  --backend-gpu-layers 0
```

That launch uses the explicit flags for this run only. Future `host start` and `host restart` runs still fall back to the persisted tuning profile.

When a managed launch happens, the lifecycle output now also prints the resolved command line when it is available:

- `host start` and `host restart --service`: `control_plane_command`
- `host restart`: `backend_command`
- `host serve`: `backend_command`

That gives you a quick way to confirm which flags actually made it into the launch without immediately digging through `.aistackd/host/` state files.

## Flag Mapping

`aistackd` ultimately launches `llama-server` with the managed backend command built from these mappings:

| `aistackd` flag | `llama-server` flag | Notes |
| --- | --- | --- |
| `--backend-context-size` | `--ctx-size` | Always resolved to a concrete value. |
| `--backend-predict-limit` | `--predict` | Always resolved to a concrete value. |
| `--backend-parallel` | `--parallel` | Always resolved to a concrete value. |
| `--backend-batch-size` | `--batch-size` | Only passed when explicitly set or persisted. |
| `--backend-ubatch-size` | `--ubatch-size` | Only passed when explicitly set or persisted. |
| `--backend-gpu-layers` | `--gpu-layers` | Only passed when explicitly set or persisted. |
| `--backend-fit-target` | `--fit-target` | Only passed when explicitly set or persisted. |
| `--backend-cache-ram` | `--cache-ram` | Only passed when explicitly set or persisted. |
| `--backend-no-kv-offload` | `--no-kv-offload` | Passed only when the resolved value is `true`. |
| `--backend-kv-offload` | no backend flag | This clears a persisted disable and leaves KV offload at the backend default behavior. |
| `--backend-no-op-offload` | `--no-op-offload` | Passed only when the resolved value is `true`. |
| `--backend-op-offload` | no backend flag | This clears a persisted disable and leaves operator offload at the backend default behavior. |

For direct backend behavior, the important distinction is:

- resolved `true` for a `no_*_offload` field adds the disabling backend flag
- resolved `false` adds no disabling backend flag
- resolved `None` also adds no backend flag because the setting is unset

That means `false` and `unset` both look the same at the raw `llama-server` command layer, even though they are different states in persisted `aistackd` tuning.

## Recommended Workflow

Use this loop when tuning a new model:

1. Start with `host tune show` and `host`.
2. Make a one-off change with `host restart --service ...`.
3. Check `host`, `/admin/runtime`, `/health`, and backend logs.
4. If the change helps, persist it with `host tune set`.
5. If one optional override was a bad idea, remove only that field with a `--clear-*` flag.
6. If the whole profile drifted too far, use `host tune reset`.

## Related Docs

- [gpu-oom-debug-checklist.md](gpu-oom-debug-checklist.md)
- [host-state-files.md](host-state-files.md)
- [README.md](../README.md)
