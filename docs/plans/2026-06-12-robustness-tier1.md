# Robustness Tier 1 — Implementation Plan

> Follow-up to PR #9's final review and the robustness assessment. Scope: port-conformance
> kits, property-based tests, supply-chain hardening, nightly fresh-resolve, structlog
> root-cause fix (typer constraint removal as acceptance), runnable samples + CI smoke.
> Out of scope (Tier 2/3): audit spine sequencing, CONTRIBUTING/CODEOWNERS, CI matrix,
> griffe API-compat, mutation testing, Azure Artifacts.

## Design decisions (the architect deltas)

| # | Decision | Why (and what naive copying would get wrong) |
|---|---|---|
| D1 | Conformance kit ships as `auropro_llm.testing` subpackage, importable via the `auropro-llm[testing]` extra; pytest imported only inside it | Ports need a *certified plug standard*; pytest must never become a runtime dep of the lib. Separate conformance package would be overkill at this scale |
| D2 | Contract suite = class `GatewayContractTests` with abstract `make_gateway()` hook + minimal capability flags; LiteLLMGateway certified by the suite in our own tests | Self-hosting proof; future adapters (client-specific) subclass + pass, or they're not done |
| D3 | Lazy-stream logger: bespoke minimal logger class resolving `sys.stderr` per write; NOT a `structlog.PrintLogger` subclass (level methods are class-level aliases to the parent `msg` — overrides silently don't take). Same lazy treatment for the stdlib handler. `cache_logger_on_first_use=True` STAYS (caching a stream-agnostic logger is safe — that's the point) | Fixes the root cause that forced `typer<0.24`. Acceptance: constraint removed, dla web tests green on typer ≥0.26 |
| D4 | hypothesis at root dev-group only; property tests target `apply_env_overrides` invariants (no-crash, idempotence, prefix isolation, non-dict-mid-path preservation) | Parser-shaped code is where line coverage lies; properties find the order-dependent cases |
| D5 | OSV scan blocks PR CI on `uv.lock`; `osv-scanner.toml` is the documented escape hatch; nightly job scans the *upgraded* lock | Lock changes are the right choke point to block; nightly gives early warning without blocking unrelated PRs at the moment of CVE disclosure |
| D6 | All GitHub Actions pinned to full commit SHAs with `# vX.Y.Z` comments | Tag pinning is a supply-chain hole (tags are mutable) |
| D7 | Samples run offline, zero keys (llm sample uses the mock_response path); CI smoke-runs them | Samples double as demo artifacts and as living docs; if they break, CI says so |
| D8 | Branch protection on `main` attempted via `gh api`; if no admin rights, exact settings documented for Akhilesh/Uday | Org-level control; surface, don't silently skip |

## Tasks

- **A — libs/core robustness:** lazy-stream logging fix (+ regression test simulating stream swap/close), remove root `typer<0.24` constraint, relock (typer → 0.26.x), dla full unit suite green; hypothesis property tests for yamlconfig; `samples/quickstart.py`; CHANGELOG entries. Coverage stays 100%.
- **B — libs/llm conformance kit:** `auropro_llm/testing/` contract suite + `[testing]` extra; certify LiteLLMGateway via the suite; `samples/quickstart.py` (offline); README section "Certifying an adapter"; CHANGELOG. Coverage 100% incl. the kit.
- **C — CI/supply chain:** SHA-pin actions; OSV scan job (lockfile, blocking) + `osv-scanner.toml`; nightly fresh-resolve workflow (`uv lock --upgrade` uncommitted + full gates + OSV); samples smoke step; branch-protection attempt + documentation.

Verification gate per task; push after all three verified together.
