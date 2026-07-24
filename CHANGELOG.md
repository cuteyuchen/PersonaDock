# Changelog

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
