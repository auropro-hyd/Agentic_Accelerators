# Accelerator Repo Plan — `Agentic_Accelerators` as the Centralized Package Platform

> **Status:** Researched + drafted 2026-06-11, after Akhilesh approved: *"directories for the
> accelerators… manage them as libraries/packages… internal package manager… use the stable
> version instead of rebuilding foundation components like llm, ocr."*
> Implementation plan: [plans/2026-06-11-accelerators-workspace-core-llm.md](plans/2026-06-11-accelerators-workspace-core-llm.md)
> (§8 steps 1–4). Broader practice strategy docs (STRATEGY / EXECUTION-PLAN) live in the private
> Ocean workspace. Research basis: 6-agent web sweep (June 2026 state) over monorepo tooling,
> reference monorepos (LangChain/LlamaIndex/OTel/Azure SDK), OSS per layer, and registries.

---

## 1. Target repo structure

```
Agentic_Accelerators/
├── pyproject.toml                 # VIRTUAL ROOT: [tool.uv.workspace] members = ["libs/*"]; not published
├── uv.lock                        # ONE lockfile — one consistent dependency set across all accelerators
├── libs/                          # ← the accelerators; each = independently versioned, publishable package
│   ├── core/                      #   auropro-core: config loader, logging/telemetry bootstrap, exceptions, shared models
│   ├── llm/                       #   auropro-llm: gateway port; LiteLLM adapter; guardrails interface
│   ├── doc-intel/                 #   auropro-doc-intel: DocumentIntelligencePort; adapters: azure-di, docling, pdfplumber
│   ├── bundle/                    #   auropro-bundle: knowledge bundle (md+json) + provenance state machine  [from dla]
│   ├── knowledge/                 #   auropro-knowledge: DocumentStore/VectorStore/Chunker/Embedder protocols; pgvector, chroma(dev)
│   ├── hitl/                      #   auropro-hitl: review queue (claim/approve/reject/edit) + audit log; FastAPI router factory  [from dla web + BMR hitl]
│   ├── rules/                     #   auropro-rules: rule-pack engine (YAML/MD packs as data)  [from BMR compliance]
│   ├── segmentation/              #   auropro-segmentation: document profiles, section detection  [from BMR]
│   ├── agent-runtime/             #   auropro-agent-runtime: LangGraph + langgraph-checkpoint-postgres + FastAPI wrapper
│   ├── observability/             #   auropro-observability: OTel GenAI instrumentation, audit-trail spine, Langfuse/MLflow exporters
│   ├── mlops/                     #   auropro-mlops: MLflow registry hooks (classical ML + prompts)
│   ├── evals/                     #   auropro-evals: deepeval harness + shared GEval rubrics; pytest-native
│   └── reports/                   #   auropro-reports: template-driven renderer  [from BMR]
├── apps/                          # deployable/demo apps — NEVER published to the feed
│   └── dla/                       #   the dla CLI + web review UI, progressively consuming libs/*
├── playbooks/                     # per-accelerator how-to (add adapter, compose use case)
├── wiki/                          # existing L0–L7 docs stay; each lib maps to a layer
└── .azuredevops|.github/          # shared CI templates + per-package release pipelines
```

**Per-package discipline (Azure-SDK policy, enforced in CI):** every `libs/<pkg>/` MUST contain
`README.md`, `CHANGELOG.md`, `pyproject.toml` (src layout, hatchling), `tests/`, `samples/`.
The CHANGELOG is what client teams read on upgrade — non-negotiable.

**dla's fate:** `src/dla` moves to `apps/dla` (it's a product/tool), while its reusable organs —
`llm/` (gateway), `bundle/` (provenance), `logging_ctx`+`config` (→ core), `web/` review pattern
(→ hitl) — are extracted into `libs/`. dla then consumes them like any other client. Uday's
M6–M8 roadmap continues unaffected on top.

## 2. Packaging mechanics (uv workspace — the decided model)

- Root `pyproject.toml` declares `[tool.uv.workspace] members = ["libs/*", "apps/*"]`. One
  lockfile, one venv: `uv sync --all-packages`, `uv run --package auropro-llm pytest`.
- Cross-package deps are declared **twice, deliberately**:
  `[project].dependencies = ["auropro-core>=0.2,<0.3"]` (what published wheels carry) **plus**
  `[tool.uv.sources] auropro-core = { workspace = true }` (editable during in-repo dev).
  ⚠️ uv strips `tool.uv.sources` from built wheels and does **not** auto-pin sibling versions
  (open issue #9811) — the explicit range next to every workspace source is **the one discipline
  we must enforce**; add a 10-line CI check.
- Known trade-off (eyes open): one lockfile = all accelerators agree on shared dep versions and
  one `requires-python` (`>=3.11,<3.14`). At our curated scale that's a feature (one coherent
  platform). Escape hatch if a package ever needs conflicting deps: drop it from workspace
  membership and link via path/published versions — uv documents this; no big-bang migration.
- Why not the alternatives: LangChain/LlamaIndex run independent-projects-per-package (no
  workspace) — right for 100s of packages with external contributors, overhead for ~13 curated
  ones (LlamaIndex ran Pants at 650 packages and **ripped it out** for plain uv + a 200-line
  script; they now auto-close PRs adding new packages). Pants/Bazel: payoff starts ~30+ engineers.
  Hatch workspaces: shipped Nov 2025, too young. Poetry: needs plugins for what uv does natively.

## 3. Versioning & release

- **Independent semver per package**, version lives in each member's `pyproject.toml`.
- Tags: **dash-style per package** — `dla-v1.2.0`, `llm-v0.3.1` (matches tooling defaults; slash
  tags break semver parsing in PSR).
- Automation: **python-semantic-release ≥ 10.4** (Python-native, CI-agnostic — works in Azure
  Pipelines, unlike release-please which is GitHub-PR-centric). Per-package
  `[tool.semantic_release]` config: `tag_format = "<pkg>-v{version}"`, monorepo commit parser
  with `path_filters = ["."]` and `scope_prefix` — so `feat(llm): …` only bumps `auropro-llm`.
- Conventional commits with package scopes become the team convention (cheap; pays for changelogs).

## 4. Distribution: start registry-less, upgrade on triggers

**Phase A (now): git-tag consumption — zero infra.**
Client projects: `uv add "git+https://github.com/auropro-hyd/Agentic_Accelerators" --tag llm-v0.3.1`
(+ `subdirectory=libs/llm`). uv pins the commit SHA in `uv.lock` → reproducible. Auth via
fine-grained PAT or deploy key. Fine for pure-Python wheels and few consumers.

**Phase B (trigger-based): Azure Artifacts feed** — the clear registry when needed: 2 GiB free
(years of pure-Python wheels), native `TwineAuthenticate@1`/`PipAuthenticate@1` in Azure
Pipelines (Build Service identity auto-granted — no PAT in CI), uv-documented auth
(`UV_INDEX_*` env / artifacts-keyring), `uv publish --index`, **and PyPI upstream proxying** so
one index URL serves private + public packages (kills dependency-confusion risk AND gives us a
vetted mirror — see LiteLLM incident below).

**Upgrade triggers (any one):** ① 3+ client projects consume the same accelerator and need semver
ranges instead of exact tags; ② a consumer must install **without** monorepo source access
(client-owned environment); ③ heavy/compiled deps where prebuilt wheels matter; ④ PAT
rotation/sprawl across client CIs becomes a time sink.

**Ruled out:** GitHub Packages (**still no Python registry support in 2026** — roadmap issue
closed "not planned"); self-hosted devpi/pypiserver (ops burden > benefit at our size); SaaS
(Gemfury/Cloudsmith/JFrog — paying for what Azure gives free).

## 5. OSS adoption table (licenses verified June 2026)

**Policy: default path = MIT/Apache-2.0/BSD only, enforced by a license-allowlist CI gate.**

| Slot | Adopt (behind our port) | Verdict notes | Avoid — and why |
|---|---|---|---|
| LLM gateway | **LiteLLM SDK** (MIT) | Wrap in `auropro-llm`; clients never import litellm directly. **Pin exact + hashes**: PyPI versions 1.82.7/.8 were compromised Mar 2026 (~40 min, token exfiltration) — mirror through Artifacts upstream when Phase B lands | LiteLLM enterprise only if client demands gateway SSO/RBAC |
| Orchestration | **LangGraph core** (MIT, v1.x stable-API pledge) | Already proven in BMR. Persistence: `langgraph-checkpoint-postgres` (MIT) | **LangGraph Platform / `langgraph-api`** — ELv2 + license key; breaks air-gapped story. Our `agent-runtime` package replaces it |
| Doc parsing/OCR | **Docling** (MIT, LF-governed, 61k★, weekly releases) as standard OSS adapter; **pdfplumber** (MIT) for born-digital; **Azure DI** stays paid default; optional GPU: **PaddleOCR-VL-1.6** (Apache, open SOTA) or **olmOCR-2** (Apache) where China-origin is disallowed; **Mistral OCR 3** via Azure AI Foundry ($1–2/1k pages) as cheap managed tier | One port, many adapters | **Marker/Surya** — GPL code + **revenue-capped OpenRAIL weights ($2M/$5M — our clients exceed it)**; **PyMuPDF** — AGPL; **Unstructured** — AGPL ultralytics leaks via hi_res, vendor pivoting away from OSS; **EasyOCR** — dormant since 2024 |
| Observability | **OTel-first** (GenAI semconv — still "Development" status: isolate attribute names in `auropro-observability`); backend: **Langfuse MIT core** self-hosted (native Azure Blob, Helm/Terraform, offline-capable) | ⚠️ Langfuse **audit logs + retention are EE-gated** — budget a Pro key for regulated clients, or cover audit at our spine | **Arize Phoenix** server — ELv2 + patent notices; risky for a consultancy redeploying at client sites |
| MLOps/registry | **MLflow 3.13+** (Apache, LF; RBAC + Helm now in OSS) | Also the documented **"minimal air-gapped profile"** (Postgres+Blob, OTel ingestion) where Langfuse's 4-service footprint is too heavy | |
| Evals | **deepeval** (Apache, pytest-native, Azure OpenAI judges, fully local) | Drops into dla's existing `eval` pytest marker | **ragas** (dormant since Feb 2026 — pin only for testset-gen), **promptfoo** (Node toolchain; ad-hoc red-team only), openai/evals (sunset) |
| HITL | **Internalize** — extract `auropro-hitl` from our two production UIs (dla web review + BMR HITL) | Client-deliverable approval workflows; no OSS labeler covers this. **Label Studio CE** (Apache) as internal ground-truth labeling tool only | Argilla (feature-frozen, maintainers left), doccano (superseded) |
| Knowledge/RAG | **Own ~4-protocol port** (DocumentStore/Retriever/Chunker/Embedder); **pgvector** default (PostgreSQL license; first-class on Azure PG Flexible Server; zero new infra), chroma embedded for dev/tests, qdrant optional | Don't build the port ON a framework | LangChain/LlamaIndex in core (dep weight, churn). If a framework is ever wanted: Haystack 2.x is the only "boring" one |
| Embeddings | Azure OpenAI via gateway (default); **sentence-transformers** (Apache, HF-maintained) as optional extra; **TEI** server (Apache) when self-host serving is justified | | infinity (perpetual 0.0.x, single maintainer) |
| Guardrails | Pluggable interface in `auropro-llm`; start **guardrails-ai** (Apache) output/PII validators (pre-bundle Hub models for offline); **NeMo Guardrails** (Apache) for conversational flows later | | |

**Net new hard dependencies: deepeval + pgvector.** Everything else: internal package, optional
extra, or standalone tool. ⚠️ **Action item — BMR compliance:** BMR's `marker_docling` on-prem
mode currently embeds **Marker** (GPL + revenue-capped weights). Replace with **Docling(+Tesseract)
or PaddleOCR-VL** during the Foundry doc-intel extraction; until then don't ship that mode to
clients above the revenue cap.

## 6. CI/CD

- **Selective builds:** Azure Pipelines path-filtered triggers per package (`paths.include:
  ['libs/llm/*']`), extending **one shared template** (the `azure-sdk-for-python`
  `ci.yml` + archetype pattern). Rule: each dependent package's filter must ALSO include its
  in-repo dependencies' paths (uv has no affected-graph awareness).
- **Release pipeline:** tag-triggered → `uv build --package` → (Phase B) `uv publish --index` to
  the Artifacts feed.
- **Gates:** license allowlist (block AGPL/ELv2/OpenRAIL entering the tree), the
  workspace-source-needs-version-range check, per-package min coverage (LlamaIndex enforces 50% —
  adopt), conventional-commit lint.

## 7. Governance

- **Curated package set** — adding a new `libs/` package requires Akhilesh/Uday/Anmol agreement
  (LlamaIndex lesson: they now auto-close package-adding PRs).
- **CODEOWNERS** per directory: Uday → `apps/dla` + `libs/bundle`; Anmol → doc-intel family
  (`doc-intel`, `rules`, `segmentation`, `hitl`, `reports`); shared → `core`, `llm`.
- Experimental/client-specific code never lands in `libs/` — prototypes live in client repos or
  `apps/`, get promoted only on traction (matches the prototype→product funnel).
- Demo/deployable apps are **never published** to the feed (Microsoft's accelerator repos are
  fork-templates, not libraries — our library model is the differentiator; keep the boundary).

## 8. Migration steps (ordered, each lands green)

> ✅ Steps 1–4 implemented on `feat/workspace-restructure` → [PR #9](https://github.com/auropro-hyd/Agentic_Accelerators/pull/9)
> (2026-06-11; 134 baseline tests redistributed 124 dla + 10 llm; +11 core, +6 scripts; CI live).
> Deferred from step 3: guardrails interface stub (YAGNI until first consumer); structlog stream-caching fix tracked in PR #9 review.

1. **Restructure shell:** root becomes virtual workspace; `git mv` dla into `apps/dla/` (or
   `libs/dla` if Uday prefers it consumable); CI stays green. *(Coordinate with Uday — his repo,
   his M6–M8 roadmap must not be disrupted.)*
2. **`libs/core` v0.1:** extract dla's `config` + `logging_ctx` (BMR's equivalents converge here later).
3. **`libs/llm` v0.1:** extract dla's `llm/` gateway; add guardrails interface stub; dla consumes it.
4. **Release automation:** PSR per package, dash tags, license-gate CI, conventional commits.
5. **`libs/doc-intel`, `libs/rules`, `libs/segmentation`, `libs/hitl`, …:** the Foundry Phase-1
   extractions from BMR (per EXECUTION-PLAN (Ocean workspace) §3) now land as `libs/`
   packages here — EXECUTION-PLAN phases unchanged, destination updated.
6. **Consumption doc:** `playbooks/consuming-accelerators.md` — git-tag pin pattern + the
   Artifacts upgrade trigger checklist.
7. **First real consumer:** insurance build (Foundry Phase 2a) consumes `libs/*` natively;
   BMR re-platform (Phase 2b) follows golden-master gates.

## 9. Decisions to ratify with Akhilesh/Uday (Friday)

1. Workspace model (one lockfile) vs. LangChain-style independent projects — **recommended: workspace** (rationale §2).
2. dla placement: `apps/dla` vs. `libs/dla` — affects whether dla itself is feed-consumable.
3. Registry timing: start git-tag, Artifacts on triggers (§4) — or stand the feed up now (cost ≈ 0, just earlier setup).
4. License policy ratification (§5) **including the Marker-in-BMR replacement** — client-facing risk.
5. CODEOWNERS split (§7).

## 10. Change log

| Date | Change |
|---|---|
| 2026-06-11 | Created from 6-dimension research workflow + local seam analysis of dla/BMR. |
| 2026-06-11 | §8 steps 1–4 implemented (PR #9): uv workspace, auropro-core + auropro-llm extracted, PSR release automation, CI with pin guard + license gate. typer<0.24 constrained (latent dla CliRunner/structlog bug — flagged to Uday). |
