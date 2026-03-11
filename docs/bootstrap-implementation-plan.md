# V1 Plan: Host/Client AI Stack With Frontend Sync

Status: Draft
Last updated: 2026-03-06
Supersedes: prior bootstrap stage-status plan

## 1. Summary

This repository will be rebuilt as a two-plane local AI platform:

1. a runtime plane that provisions and operates a local or LAN-hosted inference backend
2. an interaction plane that syncs provider config, baseline skills, and baseline tools into supported agent frontends

The runtime plane is responsible for taking a prepared machine from documented prerequisites to a working host or client setup. The interaction plane is responsible for making that runtime immediately usable from supported frontends.

This plan is the canonical repo direction for v1.

Naming conventions for all new implementation work are defined in `docs/naming-conventions.md`.

## 2. Product Goal

Deliver a system that supports these operator stories:

1. Configure a Linux machine as an AI host that can run a local backend and expose it to other machines on the same LAN.
2. Configure a laptop or workstation as a client that targets a local host or a remote LAN host through a named profile.
3. Sync frontend configuration so Codex and OpenCode can use the selected backend immediately.
4. Ship a small baseline of useful shared skills and tools, including `find-skills`, then allow project-specific skill installs on top.

## 3. Scope And Non-Goals

### In Scope

1. `host`, `client`, and `hybrid` operating modes
2. `llmfit` for hardware detection and model recommendation
3. `llama.cpp` acquisition and runtime management
4. `llmfit`-first model search and download with Hugging Face fallback
5. a managed control-plane service that exposes an Open Responses-compatible API plus repo-owned extensions
6. Codex and OpenCode config sync
7. baseline shared skills and tools
8. project-local discovery of additional skills via `find-skills`

### Out Of Scope For V1

1. embeddings, reranking, DAG, and RAG systems
2. OpenHands support
3. auto-discovery of LAN hosts
4. TLS termination inside the platform
5. full machine bootstrap from a bare OS
6. canonical baseline agents

### Permanent Scope Boundary

Host-side prerequisite installation is out of scope by design. The repo will validate and document host prerequisites, but it will not own installation of Python, Node, compilers, CUDA drivers, or other OS-level build toolchains.

## 4. Supported Environment

### Host

1. broad design target: `systemd` Linux
2. reference and CI host: Ubuntu 24.04
3. other Linux distros: best-effort
4. Arch Linux: explicit manual acceptance target because it may be the real deployment host

### Client

1. modern Linux
2. modern macOS

### Required Host Prerequisites

1. Python
2. Node
3. build tools required for `llama.cpp` source fallback
4. network access for model and binary acquisition when needed
5. working GPU driver stack when GPU acceleration is expected

## 5. Core Architecture Decisions

### Runtime Shape

1. use a Python-first monorepo
2. expose one control-plane service and one CLI
3. support explicit runtime modes:
   - `host`
   - `client`
   - `hybrid`

### Northbound API

1. base contract: Open Responses
2. support `type: "function"` tool calling on streaming and non-streaming Responses requests
3. repo-owned extensions:
   - `GET /health`
   - `GET /v1/models`
   - authenticated admin endpoints for model management and runtime state

### Authentication And Transport

1. require a non-empty API key everywhere
2. use HTTP plus API key for v1 LAN traffic
3. treat reverse proxies and TLS as later additions

### Model Serving

1. support text generation only in v1
2. serve one active model per host process
3. active-model changes happen through controlled restart or process swap
4. support the basic function-call loop on the northbound Responses surface for both streaming and non-streaming requests
5. keep function-tool execution client-managed in v1; the host transports tool calls but does not execute or advertise repo-owned server tools
6. defer non-function tools and broader orchestration beyond the basic function-call loop
7. persist bounded `previous_response_id` state on the host so client-managed tool loops can continue across control-plane restarts and return actionable diagnostics when state is missing
8. reconcile stale backend-process receipts after crashes or host reboots, and expose explicit stop/restart controls for the managed backend lifecycle
9. support a managed background control-plane service with explicit start/stop/restart controls and stale-receipt reconciliation after crashes or host reboots

### Frontend Tooling Notes

1. tool calling is client-managed only
2. the host transports function calls but does not own or advertise executable repo tools
3. synced `tools/` scripts are operator utilities, not model-executed server tools
4. the next near-term focus is frontend ergonomics and remote-usage polish for the remote-backend/local-frontend workflow

### Backend Acquisition

1. `llama.cpp` policy: prebuilt first, source fallback
2. model acquisition policy: `llmfit` first, Hugging Face fallback
3. keep `detect/recommend` and `search/download` behind separate provider boundaries so model-source strategy can change later without a rewrite

### Model Acquisition Shape

1. separate model catalog and recommendation from artifact acquisition
2. model catalog adapters return normalized model descriptors, not file paths
3. artifact acquisition must try candidates in this order:
   - explicit local GGUF path
   - discovered local model roots
   - `llmfit` acquisition provider
   - Hugging Face fallback provider
4. local GGUF inputs are first-class installs, not a separate legacy path
5. every successful install must end in one managed artifact root under `.aistackd/host/models/<model-key>/`
6. the runtime must serve managed artifacts only, never arbitrary external paths directly
7. each installed-model record must preserve:
   - model identifier
   - source provider
   - acquisition method
   - managed artifact path
   - file size
   - content hash
   - install timestamp
   - install status
8. `models install` is the mutating boundary for model artifacts; search and recommendation remain read-only
9. `models search` and `models recommend` are `llmfit`-backed only in v1; missing models use an explicit Hugging Face file install path instead of merged fallback search
10. `models browse` launches the native `llmfit` TUI in the current terminal, then imports all new or changed GGUF files from watched roots into managed host state when the session exits successfully
11. successful `models browse` or `models import-llmfit` imports must never auto-activate a model; activation remains an explicit step
12. default watched roots for llmfit reconciliation are `~/.cache/llmfit` and `~/.cache/huggingface/hub`, with explicit watch-root extension points
13. import collision rules must be stable:
   - same-content duplicates are skipped
   - same normalized model id with different content gets a short-hash suffix instead of silent overwrite
14. `models install --hf-url` is a first-class escape hatch and must accept file-specific Hugging Face URLs, including `show_file_info=<file>.gguf`
15. `llmfit` integration stays JSON-first, but search integration must tolerate non-JSON output when `llmfit search --json` does not honor the requested machine format in practice

### Frontend Integration

1. first-class targets: Codex and OpenCode
2. frontend sync owns:
   - provider endpoint wiring
   - provider credentials wiring
   - baseline skills
   - baseline tools
3. baseline content stays intentionally small

## 6. System Model

### Host Mode

Responsibilities:

1. validate prerequisites
2. detect hardware
3. acquire `llama.cpp`
4. search, recommend, and acquire models
5. run and manage the control-plane service
6. expose local or LAN-accessible inference and admin APIs

### Client Mode

Responsibilities:

1. define and manage named backend profiles
2. validate connectivity to a selected host
3. sync supported frontends against the active backend profile
4. support authenticated inference and remote admin against a LAN host

### Hybrid Mode

Responsibilities:

1. combine host and client roles on one machine
2. allow frontends on the same machine to target the local control plane through the same profile model used for remote hosts

## 7. Public Interfaces

### CLI Shape

Initial command groups:

1. `aistackd host`
2. `aistackd client`
3. `aistackd profiles`
4. `aistackd models`
5. `aistackd sync`
6. `aistackd doctor`

### Profile Model

Profiles are named endpoint definitions such as:

1. `local`
2. `lan-5090`
3. `lab-host`

Each profile must define:

1. base URL
2. API key source
3. profile role hints where useful
4. whether it is the active frontend target

### Runtime API

The control plane must expose:

1. Open Responses inference
2. health inspection
3. active model and installed model listing
4. authenticated admin operations for search, download, activate, and runtime inspection
5. authenticated tool discovery for repo-owned function-tool exposure and execution policy

## 8. Frontend Sync Contract

Frontend sync is part of the product, not a separate optional utility.

For v1, sync must:

1. write provider settings for the active profile
2. write managed baseline skills
3. write managed baseline tools
4. preserve unmanaged user config and unmanaged content
5. support dry-run and write modes
6. be idempotent across repeated runs

Baseline content policy:

1. ship `find-skills`
2. ship a small baseline of generic reusable skills
3. ship baseline tools that help supported frontends use the configured backend
   - initial baseline tools are `runtime-status`, `model-admin`, `responses-smoke`, and `runtime-wait`
   - sync must render these with the active profile defaults and write managed executable copies into frontend-specific tool roots
4. defer canonical agent definitions to a later phase

## 9. External Design Inputs

These systems inform the design, but are not runtime dependencies:

1. Open Responses
2. `superpowers`
3. StrongDM Factory

Adoption policy:

1. use them as references
2. selectively vendor only the specific skills, templates, or validation ideas intentionally adopted into this repo
3. keep this repo as the source of truth for shipped behavior

## 10. Delivery Phases

### Phase 0: Reset And Skeleton

Deliverables:

1. preserve only approved reference material
2. remove legacy runtime/bootstrap implementation
3. create the new repo skeleton around runtime, profiles, sync, and content catalogs
4. land the canonical docs and command surface

Acceptance gates:

1. legacy plan no longer drives implementation
2. new skeleton reflects `host`, `client`, `hybrid`, and `sync`
3. CI runs on the new skeleton

### Phase 1: Contracts And Foundations

Deliverables:

1. CLI contract
2. profile schema
3. runtime config schema
4. frontend sync manifest shape
5. backend and model-source adapter boundaries

Acceptance gates:

1. contracts are testable and versioned
2. no remaining ambiguity around mode boundaries or public commands

### Phase 2: Host Runtime

Deliverables:

1. prerequisite validation
2. bootstrap-managed operator tool install for `llmfit` and `hf`
3. hardware detection
4. `llama.cpp` acquisition
5. model recommendation and acquisition
6. control-plane service lifecycle

Acceptance gates:

1. Ubuntu reference host can serve one model through the control plane
2. source fallback works when prebuilt acquisition is unavailable
3. explicit local GGUF install works without network access
4. successful llmfit browse/import stages all new GGUF artifacts into managed host state without changing the active model
5. a clean host can bootstrap `llmfit`, `hf`, and managed `llama.cpp` without relying on `git`, `curl`, or `wget`

### Phase 3: Client Runtime

Deliverables:

1. named backend profiles
2. remote connectivity validation
3. remote admin against authenticated LAN hosts
4. client-side smoke and local tool-loop examples against the active remote profile

Acceptance gates:

1. client-only machine can target an existing host without local model/runtime setup
2. bad credentials and unreachable hosts fail with actionable errors
3. the main CLI can prove `/v1/responses` works end to end from the frontend machine without relying on synced scripts

### Phase 4: Frontend Sync

Deliverables:

1. Codex adapter
2. OpenCode adapter
3. provider wiring for active profile
4. baseline skill and tool sync
5. first-run frontend readiness checks for the remote-backend/local-frontend workflow

Acceptance gates:

1. fresh client can sync supported frontends and use the configured host immediately
2. repeated sync does not damage unmanaged config
3. the repo can answer “am I ready to use OpenCode against this host?” in one command

### Phase 5: Catalog And Discovery

Deliverables:

1. baseline content catalog
2. `find-skills`
3. project-local skill install workflow
4. ownership and provenance tracking for managed content

Acceptance gates:

1. project-specific skills can be added without polluting the global baseline
2. vendored external content records provenance clearly

## 11. Must-Pass Scenarios

The implementation is not complete until these scenarios pass:

1. same-machine `hybrid` setup on the Ubuntu reference host
2. Linux `host` plus LAN `client`
3. client-only machine connecting to an already-running host
4. frontend sync after switching active profiles
5. `llmfit` download path failure with controlled Hugging Face fallback
6. prebuilt backend unavailable with successful source fallback
7. explicit local GGUF install succeeds and is activated from managed host state
8. missing model in llmfit search still installs from an explicit Hugging Face file URL
9. successful llmfit browse session imports multiple new GGUFs without auto-activation
10. Arch host manual acceptance

## 12. Risks And Controls

### Risk: Distro-specific host setup drift

Control:

1. keep Ubuntu as the only CI/reference host
2. isolate distro-specific logic behind host dependency adapters
3. keep Arch in manual acceptance

### Risk: `llmfit` does not remain sufficient for model download

Control:

1. keep detection/recommendation and download responsibilities separate
2. preserve Hugging Face fallback from the start
3. keep native llmfit TUI browsing separate from managed runtime artifact ownership
4. prefer JSON integration, but tolerate search-output format drift without breaking model discovery

### Risk: Frontend sync becomes too broad

Control:

1. keep v1 baseline small
2. defer canonical agents
3. ship only Codex and OpenCode initially

## 13. References

1. Open Responses specification: `https://www.openresponses.org/specification`
2. StrongDM Factory: `https://factory.strongdm.ai/`
3. `superpowers`: `https://github.com/obra/superpowers`
