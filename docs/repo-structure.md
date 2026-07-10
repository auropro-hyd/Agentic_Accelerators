# Repository Structure Guide — the Accelerator Platform

How this repository is organized, how the accelerators connect, and the
exact layout every accelerator follows. **This is the working guide for
anyone building in (or integrating with) this repo.** The decision record
behind it is internal; this document states the rules.

---

## 1. The model in one diagram

```text
════════════════════════ THE HUB — this repository ════════════════════════

   libs/  (shared code — the ONLY code-reuse channel)
   ┌──────────────┐  ┌──────────────┐
   │ libs/core    │  │ libs/llm     │   apps import libs.
   │ config + log │  │ LLM gateway  │   apps NEVER import other apps.
   └──────┬───────┘  └──────┬───────┘
          └────────┬────────┘
                   ▼
   apps/  (one folder per accelerator = one installable package)
   ┌────────────────────┐                  ┌────────────────────┐
   │ apps/dla   (L1)    │   bundle/  +     │ apps/kra   (L2)    │
   │ Data Layer         │  bundle-schema   │ Knowledge Rep.     │
   │ Accelerator        │ ───────────────► │ Assembler          │
   └────────────────────┘   (files, not    └─────────┬──────────┘
                             imports)                │
   contracts/  (mirrored published schemas —         │ representation/
   the ONLY thing outside teams must consume)        │ + kr-schema
                                                     │ + MCP tools
═════════════════════════════════════════════════════╪═════════════════════
                                                     ▼
════════════════ THE SPOKES — other teams, own repositories ═══════════════

   L3 Agentic Layer · L4 UX · L5 Testing/Eval · …
   Build against the published contracts (contracts/*.json + MCP tools).
   No code dependency on this repo. Join the hub later — or never:

        spoke repo ── git subtree add --prefix apps/<name> ──► apps/<name>
        (full history preserved; becomes a workspace member in one PR)
```

**The rule that makes this work:** accelerators hand off through
**published, versioned contracts** (a directory of artifacts + a generated
JSON Schema + MCP tools), never through code imports. Where code lives is
therefore a team-workflow choice; the contracts protect the integration
either way.

## 2. Top-level layout (the hub)

```text
AgenticApplication_Accelerator/
├── pyproject.toml            # uv workspace root: members = ["libs/*", "apps/*"]
├── uv.lock                   # single lockfile for the whole workspace (CI uses --locked)
├── Makefile                  # per-app targets (test-dla, test-kra, e2e-*, ci) — OS-agnostic
├── .github/workflows/        # CI: path-filtered jobs per app + libs
│
├── libs/                     # SHARED CODE — independently versioned, publishable packages
│   ├── core/                 #   auropro-core: YAML→pydantic config, structured logging
│   └── llm/                  #   auropro-llm: provider-agnostic LLM/embedding gateway
│
├── apps/                     # ACCELERATORS — one folder each, layout per §3
│   ├── dla/                  #   L1 · Data Layer Accelerator (shipped)
│   └── kra/                  #   L2 · Knowledge Representation Assembler
│
├── contracts/                # PUBLISHED HAND-OFF SURFACE (mirrors, CI-enforced identical
│   ├── README.md             #   to each app's config/schemas/) — what spoke teams pin
│   ├── bundle-schema.json    #   L1 → L2 contract
│   └── kr-schema.json        #   L2 → L3 contract (from kra M2)
│
├── docs/                     # public docs: operator guides, contract docs, this file,
│   └── accelerators/         #   the L0–L7 landscape docs
├── scripts/                  # repo-level guard scripts (licenses, workspace pins) + tests
├── wiki/                     # architecture notes
│
├── specs/                    # spec-kit planning, one dir per accelerator   (gitignored)
├── Local_Dev/                # internal working material                    (gitignored)
└── bundle*/ representation*/ # per-engagement DATA outputs — never committed
```

## 3. Anatomy of an accelerator (`apps/<name>/`) — the standard shape

Every accelerator, in this repo or a spoke repo, uses this layout. `dla` is
the reference implementation; `kra` follows it; new accelerators copy it.

```text
apps/<name>/
├── pyproject.toml            # its OWN package: name, deps, entry point
│                             #   [project.scripts] <name> = "<name>.cli.main:app"
│                             #   deps on libs via [tool.uv.sources] workspace = true
│                             #   own ruff/mypy/pytest config (warnings-as-errors)
├── README.md                 # what it is, quickstart, command reference
│
├── config/
│   ├── defaults.yaml         # every threshold/knob — behavior lives in config, not code
│   ├── examples/             # ready-to-run engagement configs
│   └── schemas/              # THE PUBLISHED CONTRACT — JSON Schema generated from the
│       └── <name>-schema.json#   code's pydantic models (parity-tested in CI, mirrored
│                             #   to /contracts). Downstream consumes THIS, never src/.
│
├── src/<name>/               # ★ ALL MAIN CODE — the only importable surface
│   ├── __init__.py           #   __version__
│   ├── cli/                  #   entry point: cli/main.py (Typer app + exit-code table
│   │                         #   0–7, shared convention) + one module per subcommand
│   ├── config/               #   engagement-config pydantic models + loader
│   │                         #   (env prefix <NAME>__, secrets via env-var NAMES only)
│   ├── <stage>/…             #   one package per pipeline stage / domain concern —
│   │                         #   e.g. dla: connectors/ discovery/ profiling/ describe/
│   │                         #        recommender/ bundle/ ui/
│   │                         #   e.g. kra: bundle/ grade/ plan/ model/ graph/ vector/
│   │                         #        query_pack/ review/ serve/ commit/ pipeline/
│   └── output/ (or bundle/)  #   artifact writers: atomic, canonical, deterministic —
│                             #   owns the on-disk layout of what this accelerator emits
│
└── tests/                    # co-located with the code they test
    ├── unit/                 #   fast, no external services — the per-PR CI gate
    ├── integration/          #   cross-module / real-pipeline (may need workspace peers)
    ├── e2e/                  #   opt-in via <NAME>_E2E_FIXTURE (Docker fixtures)
    ├── eval/                 #   eval harness for anything inferred/generated
    │                         #   (constitution: "measure it or don't ship it")
    └── fixtures/             #   committed synthetic fixtures + regeneration README
                              #   (real generated bundles are never committed)
```

**Where is "the main code"?** Always `src/<name>/`. The CLI entry point is
always `src/<name>/cli/main.py`. The published contract is always
`config/schemas/`. Tests always sit in `tests/` beside `src/`. No
exceptions — this uniformity is what lets a spoke repo merge in via
`git subtree` with zero restructuring.

## 4. Hard rules (enforced, not aspirational)

1. **No app imports another app.** Integration is files + schemas + MCP.
   (dla → kra: kra validates `bundle/` against `bundle-schema.json`; it
   never `import dla`.)
2. **Shared code lives in `libs/`** and is extracted only when a second
   app actually needs it — never speculatively.
3. **Contracts are generated from code** (pydantic → JSON Schema), parity-
   tested in CI, versioned semver, mirrored to `/contracts`. Prose docs
   about a contract are non-normative.
4. **Consumers pin the contract version** they tested and validate inputs
   at their own gate.
5. **Engagement data (`bundle/`, `representation/`) is never committed.**
   Code and contracts in git; data on disk per engagement.
6. **Secrets only via env vars** — configs store the env-var *name*.
   No AI-tool or person names in commits/PRs/code.
7. **One branch model:** `feat/<accel>-<topic>` → PR → stakeholder merges
   via the GitHub UI. `main` = only released, demoed work.

## 5. For spoke teams (building an accelerator in your own repo)

- Adopt the §3 shape (`src/<name>/`, own `pyproject.toml`, `tests/`) and
  the §4 rules from day one.
- Consume `contracts/*.json` (vendor the file and pin the version) and,
  for L2 consumers, the kra MCP tools — nothing else from this repo.
- Need `auropro-core`/`auropro-llm`? Vendor a copy short-term, or install
  from a git tag; don't fork-and-drift.
- Joining the hub later is one PR:
  `git subtree add --prefix apps/<name> <your-repo> main` → `uv lock` →
  add Makefile/CI stanzas. Your history comes with you. Staying a spoke
  permanently is equally valid — the contracts are the interface either way.

## 6. Adding a new accelerator to the hub — checklist

1. `apps/<name>/` scaffold per §3 (workspace picks it up via `apps/*`).
2. `uv lock` (CI runs `--locked`).
3. Makefile: add `test-<name>` to the `test` chain; add `apps/<name>/src`
   to the exported `PYTHONPATH`.
4. CI: add the app's unit-test step (path-filtered); e2e lanes when they exist.
5. Spec-kit planning in `specs/<NNN>-<name>/` (spec → plan → data-model →
   contracts → tasks → analysis) before code.
6. Publish its contract in `config/schemas/` + mirror to `/contracts` once
   downstream consumers exist.
