# Naming Conventions

Status: Draft
Last updated: 2026-03-07
Applies to: all new implementation work

## Canonical Root

Use `aistackd` as the single naming root for the rebuilt project.

Canonical names:

1. repository name: `aistackd`
2. project name in prose: `aistackd`
3. optional long-form expansion in prose: `AI stack daemon`
4. Python package root: `aistackd`
5. Python import namespace: `aistackd`
6. primary CLI executable: `aistackd`
7. runtime state directory: `.aistackd/`
8. environment variable prefix: `AISTACKD_`

## Naming Rules By Surface

### Repo And Filesystem

1. repository-owned hidden state uses `.aistackd/`
2. docs file names use `kebab-case`
3. skill directory names use `kebab-case`
4. repo-owned config and state file names use `snake_case`

### Python

1. package and module names use `snake_case`
2. classes use `PascalCase`
3. functions, methods, variables, and files use `snake_case`
4. constants use `UPPER_SNAKE_CASE`

### CLI

1. the top-level command is `aistackd`
2. subcommands use short lowercase nouns or verb-noun pairs
3. flags use `kebab-case`
4. machine-readable values prefer `snake_case`

Initial command shape:

1. `aistackd host`
2. `aistackd client`
3. `aistackd profiles`
4. `aistackd models`
5. `aistackd sync`
6. `aistackd doctor`

### Environment Variables

1. all repo-owned environment variables start with `AISTACKD_`
2. words are separated with underscores

Examples:

1. `AISTACKD_HOME`
2. `AISTACKD_PROFILE`
3. `AISTACKD_LOG_LEVEL`
4. `AISTACKD_API_KEY`

### API And Wire Names

1. public JSON fields use `snake_case` unless an external spec requires otherwise
2. Open Responses wire names stay unchanged where the spec defines them
3. repo-owned API extensions also prefer `snake_case`

## Do Not Reuse As Canonical Names

These may appear only in salvage or historical context:

1. `ai-stack`
2. `ai_stack`
3. `.ai_stack`
4. `bootstrap-stack`
5. `sync-opencode-config`

## Scaffold Defaults

Unless a later ADR changes this, use these package names:

1. `aistackd.cli`
2. `aistackd.runtime`
3. `aistackd.control_plane`
4. `aistackd.frontends`
5. `aistackd.skills`
6. `aistackd.models`
7. `aistackd.state`
8. `aistackd.testing`
