# TODO

Snapshot of the near-term follow-up work after the host tuning and docs pass on 2026-04-08.

## High Priority

## Host And Runtime Polish

- [ ] Add a short reference mapping from `aistackd host` tuning flags to the underlying `llama-server` flags.
- [ ] Consider surfacing the launched backend command in more host lifecycle outputs, not just `host serve`.
- [ ] Add a few documented tuning presets for common cases such as low-VRAM GPUs, CPU-only fallback, and a conservative default debug profile.
- [ ] Review whether the persisted tuning UX should distinguish between "unset", "explicit false", and "use backend default" more visibly.

## Client And Control Plane

- [ ] Decide whether any host-managed tool execution should move beyond the current client-managed function-call loop.

## Docs

- [ ] Add a dedicated `host tune` section to the operator docs beyond the README quick examples.
- [ ] Keep the GPU OOM checklist updated as live tuning guidance changes.
- [ ] Document the important state files under `.aistackd/host/` for debugging and manual inspection.

## Broader Roadmap

- [ ] Continue the broader frontend polish work after the OpenHands adapter.
- [ ] Expand the validated host matrix beyond the current same-machine Linux reference path.
- [ ] Tighten the release-readiness story around host bootstrap, frontend sync, and operator troubleshooting.
