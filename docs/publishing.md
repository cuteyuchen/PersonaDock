# Publishing PersonaDock standalone releases

PersonaDock is distributed through GitHub Releases as standalone executables. End users install it with `install.sh` or `install.ps1`; no Python environment or package index is required.

## Release assets

Each release contains:

```text
personadock-linux-x86_64.tar.gz
personadock-linux-arm64.tar.gz
personadock-macos-x86_64.tar.gz
personadock-macos-arm64.tar.gz
personadock-windows-x86_64.zip
persona-demo-<version>.personapack
install.sh
install.ps1
SHA256SUMS
LICENSE
```

PersonaPack publisher signatures are optional detached assets. A release may additionally contain:

```text
persona-demo-<version>.personapack.sig.json
publisher-public-key.json
```

Do not upload a signing private key.

## Required pre-release checks

Before creating a tag, the release commit must pass:

- complete pytest suite
- Python 3.10–3.13 contract matrix
- real Docker Hermes/OpenClaw Adapter contracts
- Linux x86_64 and ARM64 standalone verification
- macOS Intel and Apple Silicon standalone verification
- Windows x86_64 standalone verification
- Ed25519 sign/verify workflow inside each standalone executable
- AES-GCM private backup create/restore workflow inside each standalone executable
- Character Card V3 export/inspect workflow
- release asset checksum assembly

## Publish v1.0.0

The Git tag must match both:

```text
pyproject.toml
src/persona_dock/__init__.py
```

Commands:

```bash
git checkout main
git pull origin main
git tag -a v1.0.0 -m "PersonaDock v1.0.0"
git push origin v1.0.0
```

The `Publish PersonaDock release` workflow will:

1. verify that the tag matches the project version
2. run the test suite
3. build Linux x64 and ARM64 standalone executables
4. build macOS Intel and Apple Silicon standalone executables
5. build a Windows x64 standalone executable
6. execute each binary's complete 1.0 smoke test
7. build and inspect an example PersonaPack
8. generate `SHA256SUMS`
9. create or update the GitHub Release
10. upload executables, installer scripts, PersonaPack, checksums and license

## Sign the example PersonaPack

Signing is deliberately separate from the public build workflow because private signing keys must not be stored in the repository.

On a trusted release workstation:

```bash
personadock trust sign ./persona-demo-1.0.0.personapack \
  --key ~/.config/personadock/release-signing.pem
```

Verify before upload:

```bash
personadock trust verify ./persona-demo-1.0.0.personapack \
  --signature ./persona-demo-1.0.0.personapack.sig.json \
  --trusted-key ~/.config/personadock/release-signing.pem.pub \
  --json
```

Upload the detached signature and public key document as additional GitHub Release assets.

## Releasing the next version

Update both application version declarations:

```text
pyproject.toml
src/persona_dock/__init__.py
```

Update:

- `CHANGELOG.md`
- compatibility documents when public contracts change
- Golden Contract only when the change is intentional and compatible

Then create a matching tag such as `v1.0.1` or `v1.1.0`.

Do not reuse or move an existing release tag.

## Installation checks

Linux or macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh | sh
personadock --version
personadock adapter list
personadock doctor --json
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.ps1 | iex
personadock --version
personadock adapter list
personadock doctor --json
```

To test v1.0.0 explicitly:

```bash
PERSONADOCK_VERSION=v1.0.0 sh install.sh
```

```powershell
$env:PERSONADOCK_VERSION = "v1.0.0"
.\install.ps1
```

## Release verification after publication

After the GitHub Release exists, verify every installation path against the published assets rather than a workflow artifact:

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh \
  | sh -s -- --version v1.0.0
personadock --version
```

On Windows, install the same fixed tag and run the complete CLI/Web smoke checks.

Do not mark the release complete until `SHA256SUMS`, all five executable archives, installer scripts and the example PersonaPack are downloadable from the GitHub Release.
