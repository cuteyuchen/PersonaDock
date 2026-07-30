# Changelog

## Unreleased — Vue Control Plane migration complete

### Vue 3 desktop control plane

- Replaced the default native JavaScript interface with Vue 3, TypeScript, Vite, shadcn-vue, Reka UI and Tailwind CSS 4.
- Added a high-density desktop shell, Hash Router, Pinia preferences and TanStack Vue Query server-state management.
- The Vue control plane now owns `/`; `/vue` remains an alias and the former interface is available at `/legacy` for one compatibility cycle.
- Node.js is required only for development and release builds; wheel and standalone users continue to receive prebuilt embedded assets.

### Persona, Artifact and Runtime workflows

- Migrated Persona creation, registration, details, Canonical/Monaco editing, Revision history, semantic Diff, validation, scenario tests and compile previews.
- Added optimistic Canonical concurrency protection with `expected_content_hash`; stale editors receive HTTP 409 instead of silently overwriting a newer Revision.
- Migrated Build, PersonaPack, public export, Ed25519 signing and verification, AES-256-GCM private backups, Character Card, Adapter Doctor and Skill installation.
- Migrated Runtime details and Adoption Preview, Hermes/OpenClaw deployment Plan/Apply, one-time confirmation tokens, deployment history and Rollback.

### Governance and AI Studio

- Migrated Memory policy, candidate review, conflict resolution, propagation plans and history.
- Migrated Reviewed Session Summary policy, manual summaries, review and explicit propagation while keeping raw Session/Transcript synchronization disabled.
- Migrated encrypted Provider settings, connection tests, model discovery and Create/Distill/Hybrid/Refine AI Persona generation.
- AI drafts expose Canonical, semantic Diff, risk, validation, tests and compile preview for review, and still require explicit `APPLY`.

### Browser quality gates

- Added Playwright Chromium tests for the root shell and major workspaces.
- Added axe-core serious/critical accessibility checks and an 8 MiB embedded frontend resource budget.
- Release bundle now gates on Vue type checking, Vitest, Vite, Playwright, pytest, installer validation, PyInstaller HTTP resource validation, PersonaPack and checksums.

## Unreleased — Web Control Plane 2

### Complete Web capability coverage

- Unified desktop-style Web workspace with versioned `/api/v1` resources, Capability Registry, persistent Job Center and SSE events.
- Persona creation, registration, Runtime discovery, Adoption, export, Canonical editing, Revision history, semantic Diff, validation, tests and compile previews.
- Build, PersonaPack, public export, signing, verification, encrypted backup, Character Card, Adapter and Skill workflows.
- Native Hermes and OpenClaw deployment Plan/Apply/Verify/Rollback with persistent deployment history and runtime-state revalidation.
- Memory and Reviewed Session Summary policy, collection, review, conflict, plan and apply workspaces.

### AI Persona Studio

- OpenAI, OpenAI-compatible, Anthropic, Gemini and Ollama Provider adapters.
- AES-256-GCM local Secret Vault; API keys and custom sensitive headers are not stored in SQLite or returned to the browser.
- Create, Distill, Hybrid and Refine modes.
- Canonical v3 validation, scenario tests, compile previews and semantic risk Diff before application.
- AI results remain drafts until the user explicitly applies them to a Revision; no automatic deployment or synchronization.
- Raw instructions and evidence are not stored in Job or Generation history.

### Web security and quality

- Constant-time Bearer Token comparison.
- Configurable request-body limit, API `no-store`, Content Security Policy, frame denial, MIME sniffing protection and restrictive browser permissions.
- Automatic CLI/Web top-level command parity validation with zero planned Capability entries.
- Phase-specific integration tests, standalone executable resource validation and retained pytest diagnostics in GitHub Actions.
- Restrained desktop utility styling with no gradients, AI chat bubbles or CDN dependencies.

## 1.0.0 — 2026-07-24

PersonaDock 1.0 turns the project into a local-first control plane for portable, reviewable AI personas.

### Canonical and Registry

- Canonical Persona Schema v3.
- Persona Registry with Runtime Instances, Bindings, Snapshots, Journal, Sync and Session Summary records.
- Transactional Registry migrations through Schema v3.
- Semantic Diff, migration and deterministic scenario tests.

### Native Adapters

- Native Hermes Profile Distribution Adapter.
- Native OpenClaw Agent/Workspace Adapter.
- Local, Docker and OpenClaw SSH transports.
- Plan, Apply, Verify, Snapshot and Rollback workflows.
- Explicit file ownership and private runtime state preservation.

### Governed synchronization

- Review-first cross-runtime Memory synchronization.
- Sensitivity classification, provenance, deduplication and conflict resolution.
- Propagation logs and source echo prevention.
- Reviewed Session Summary handoff with pending tasks and emotional context.
- Raw Session/Transcript synchronization remains disabled.

### Trust and backup

- Deterministic PersonaPack Manifest v2 archives.
- Strict unexpected-member rejection.
- Detached Ed25519 PersonaPack signatures and trusted Key IDs.
- Scrypt + AES-256-GCM encrypted private Persona backups.

### Compatibility

- Stable Adapter API 1.0 and `personadock.adapters` plugin discovery.
- Character Card V1/V2/V3 JSON import.
- Character Card PNG Metadata and CHARX import.
- Character Card V2/V3 JSON and CHARX export.
- OpenPersona compatibility research and loss boundaries.

### Quality

- Golden Contract Tests.
- Python 3.10–3.13 compatibility matrix.
- Real Docker Hermes/OpenClaw Adapter contracts.
- Linux x86_64/ARM64, macOS Intel/Apple Silicon and Windows x86_64 standalone validation.
- Complete migration, rollback, trust and compatibility documentation.

### Security defaults

- Local-only Web binding unless a Bearer Token is configured.
- No credentials, raw Sessions, Transcripts or runtime State in PersonaPack.
- Memory and Session Summary auto-approval disabled by default.
- Raw Session preview disabled by default and double-gated when enabled.
- System messages, tool calls, tool results and reasoning excluded from Session Summary propagation.
