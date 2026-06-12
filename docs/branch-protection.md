# Branch Protection Settings for `main`

Automated attempt via `gh api -X PUT` returned 404 (no admin token). Apply these settings manually in the GitHub UI.

## Repository

`auropro-hyd/Agentic_Accelerators` → Settings → Branches → Add rule for `main`

## Settings to Enable

| Setting | Value |
|---|---|
| Require a pull request before merging | ✓ enabled |
| Required approving reviews | 1 |
| Require status checks to pass before merging | ✓ enabled |
| Require branches to be up to date | ✓ enabled (strict) |
| Required status checks | `checks`, `osv-scan` |
| Do not allow bypassing the above settings (enforce admins) | leave unchecked (false) |
| Restrict who can push to matching branches | leave empty (null) |

## Required Status Check Names

These must match the job `id` fields in `.github/workflows/ci.yml` exactly:

- `checks` — main CI job (sync, lint, mypy, tests, license gates, samples smoke)
- `osv-scan` — supply-chain vulnerability scan against `uv.lock`

## Notes

- "Strict" up-to-date means PRs must be rebased/merged with the latest `main` before merging — prevents stale-base races.
- Once both `checks` and `osv-scan` have run at least once on a PR, GitHub will surface them in the required-checks dropdown.
- See `docs/plans/2026-06-12-robustness-tier1.md` (D8) for design rationale.
