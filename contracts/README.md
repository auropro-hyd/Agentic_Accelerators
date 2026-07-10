# contracts/ — the published hand-off surface

This folder is the **only** thing a downstream consumer (another
accelerator, another team, another repository) needs from this platform:
the machine-readable contracts each accelerator publishes.

| File | Producer | Consumed by | What it validates |
|---|---|---|---|
| `bundle-schema.json` | `apps/dla` (L1 · Data Layer Accelerator) | L2 Knowledge Representation Assembler, any bundle reader | Every artifact in a `bundle/` directory |

(`kr-schema.json` — the L2 → L3 contract for `representation/` directories —
joins this table when the kra semantic-model milestone publishes it.)

## Rules for consumers

1. **Pin the version.** Each schema carries a top-level `version` (semver;
   additive changes bump minor). Vendor the file and record the version you
   tested against — do not track this folder's HEAD blindly.
2. **Validate at your gate.** Check inputs against the schema before using
   them; never reach into this repo's `src/` — code layout is not a contract.
3. **Prose docs are non-normative.** Human-readable contract documents
   describe these schemas; when they disagree, the JSON Schema wins.

## Rules for producers (in this repo)

- Each file here is a byte-identical **mirror** of an accelerator's
  published schema at `apps/<name>/config/schemas/`. The source of truth is
  generated from code (pydantic → JSON Schema) and parity-tested; this
  mirror is enforced by `scripts/check_contract_mirror.py` in CI.
- After regenerating a schema (e.g. `make schema`), run `make sync-contracts`.
