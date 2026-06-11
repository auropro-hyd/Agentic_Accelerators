# Releasing accelerator packages

Releases are per-package, automated from conventional commits.

1. Commit with package scopes: `feat(core): …`, `fix(llm): …`. Only commits touching
   files under a package's directory count toward its release (PSR path_filters).
2. To cut a release: `cd libs/<pkg> && uv run semantic-release version` —
   bumps `pyproject.toml:project.version` from commit types (feat→minor, fix→patch,
   `BREAKING CHANGE:`→major), tags `<pkg>-vX.Y.Z`, updates the changelog.
3. Push the tag: `git push origin <pkg>-vX.Y.Z`.
4. Consumers pin: `uv add "git+https://github.com/auropro-hyd/Agentic_Accelerators" --tag core-v0.1.0`
   with `subdirectory = "libs/core"` (see docs/ACCELERATOR-REPO-PLAN.md §4; Azure Artifacts feed
   comes later, on the documented triggers).

Until the first tagged release, versions stay 0.1.0 and consumers use the branch/SHA.
