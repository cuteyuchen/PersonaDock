# Release history

## v1.1.0

PersonaDock 1.1 completes the Vue 3 desktop control plane while preserving the 1.0 data, Adapter and PersonaPack compatibility contracts.

- Vue 3, TypeScript, Vite, shadcn-vue and Monaco replace the default native JavaScript interface.
- Persona lifecycle, Canonical editing, Revision, semantic Diff, validation, tests and compilation are available in one desktop workspace.
- Build, PersonaPack, Ed25519 trust, AES-256-GCM backup, Character Card, Adapter and Skill workflows are available in Vue.
- Runtime adoption, Hermes/OpenClaw deployment Plan/Apply/Rollback and deployment history are available in Vue.
- Memory and Reviewed Session Summary governance include policy, review, conflict handling, propagation planning and explicit application.
- AI Studio supports OpenAI, OpenAI-compatible, Anthropic, Gemini and Ollama providers with an encrypted local Secret Vault.
- Create, Distill, Hybrid and Refine generation remain review-first and require explicit application.
- Playwright, axe-core, frontend size budgets and embedded Vue HTTP checks are release gates.
- `/` is the Vue control plane, `/vue` is an alias and `/legacy` retains the previous interface for one compatibility cycle.

## v1.0.0

PersonaDock 1.0 is the first stable local-first Persona control plane release.

- Canonical Persona Schema v3 and PersonaPack Manifest v2.
- Persona Registry, Runtime Discovery, Binding, Snapshot and Journal.
- Native Hermes Profile Distribution deployment and rollback.
- Native OpenClaw Agent/Workspace deployment for local, Docker and SSH targets.
- Review-first cross-runtime Memory synchronization.
- Reviewed Session Summary handoff; raw Session synchronization remains disabled.
- Stable Adapter API 1.0 with external plugin discovery.
- Deterministic PersonaPack archives, strict integrity validation and detached Ed25519 signatures.
- Scrypt + AES-256-GCM encrypted private Persona backups.
- Character Card V1/V2/V3 JSON, PNG Metadata and CHARX compatibility.
- Python 3.10–3.13 contracts, real Docker tests and five-platform standalone verification.

## Pre-1.0 refactor milestones

The control-plane architecture was developed through independently reviewed phases:

- Phase 0: safe deployment core and local Web foundation.
- Phase 1: Persona Registry and runtime discovery.
- Phase 2: adopt, snapshot and export existing personas.
- Phase 3: Canonical Persona v3.
- Phase 4: native Hermes Adapter.
- Phase 5: native OpenClaw Adapter.
- Phase 6: governed cross-runtime Memory synchronization.
- Phase 7: reviewed Session Summaries.
- Phase 8: compatibility, trust, backup, Character Card and 1.0 stabilization.

Earlier experimental release notes described prototypes that were replaced during this refactor. They are not compatibility promises for PersonaDock 1.0.
