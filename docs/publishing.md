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

## Release metadata contract

These files must contain the same version:

```text
pyproject.toml
src/persona_dock/__init__.py
frontend/package.json
```

`CHANGELOG.md` must contain a matching release heading, and the Git tag must be `v<version>`.

Run the consistency check locally:

```bash
python scripts/check_release_version.py
python scripts/check_release_version.py --tag v1.1.0
```

## Required pre-release checks

Before creating a tag, the release commit must pass:

- Vue TypeScript checking, Vitest and Vite production build
- Playwright Chromium flows and axe-core serious/critical checks
- embedded frontend 8 MiB resource budget
- complete pytest suite
- Python 3.10–3.13 contract matrix
- real Docker Hermes/OpenClaw Adapter contracts
- Linux x86_64 and ARM64 standalone verification
- macOS Intel and Apple Silicon standalone verification
- Windows x86_64 standalone verification
- Ed25519 sign/verify workflow inside each standalone executable
- AES-GCM private backup create/restore workflow inside each standalone executable
- Character Card V3 export/inspect workflow
- Vue `/`, `/vue`, `/legacy`, JavaScript and CSS verification inside each executable
- release asset checksum assembly

## Local release-candidate check

From a clean checkout:

```bash
git checkout main
git pull --ff-only origin main
python scripts/check_release_version.py

corepack enable
corepack prepare pnpm@10.14.0 --activate
pnpm --dir frontend install --no-frozen-lockfile
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build

python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
python -m pip install pyinstaller
pytest

pyinstaller --clean --noconfirm --onefile \
  --name personadock \
  --collect-data persona_dock \
  src/persona_dock/__main__.py
python scripts/verify_release_binary.py --binary dist/personadock
python scripts/verify_vue_binary.py --binary dist/personadock
python scripts/package_binary.py \
  --binary dist/personadock \
  --output dist/personadock-linux-x86_64.tar.gz
```

Windows PowerShell uses `.venv\Scripts\Activate.ps1` and `dist\personadock.exe`.

## Publish v1.1.0

Only create the tag after the latest `main` commit has a successful `personadock-bundle` status.

```bash
git checkout main
git pull --ff-only origin main
python scripts/check_release_version.py --tag v1.1.0
git status --short
git tag -a v1.1.0 -m "PersonaDock v1.1.0"
git push origin v1.1.0
```

The `Publish PersonaDock release` workflow will:

1. verify that the tag, Python package, frontend package and Changelog versions match
2. type-check, test and build the Vue frontend
3. run Playwright Chromium and pytest
4. upload the validated Vue assets for all platform builders
5. build Linux x64 and ARM64 standalone executables
6. build macOS Intel and Apple Silicon standalone executables
7. build a Windows x64 standalone executable
8. execute each binary's complete release smoke test and Vue HTTP test
9. build and inspect an example PersonaPack
10. generate and verify `SHA256SUMS`
11. extract the `1.1.0` section from `CHANGELOG.md`
12. create or update the GitHub Release and upload all assets

The workflow can also republish an existing immutable tag through `workflow_dispatch` by supplying `v1.1.0`. It never moves or recreates the tag.

## Sign the example PersonaPack

Signing is deliberately separate from the public build workflow because private signing keys must not be stored in the repository.

On a trusted release workstation:

```bash
personadock trust sign ./persona-demo-1.1.0.personapack \
  --key ~/.config/personadock/release-signing.pem
```

Verify before upload:

```bash
personadock trust verify ./persona-demo-1.1.0.personapack \
  --signature ./persona-demo-1.1.0.personapack.sig.json \
  --trusted-key ~/.config/personadock/release-signing.pem.pub \
  --json
```

Upload the detached signature and public key document as additional GitHub Release assets. Never upload the private key.

## Releasing the next version

Update all application version declarations:

```text
pyproject.toml
src/persona_dock/__init__.py
frontend/package.json
```

Move completed entries from `Unreleased` into a dated release section in `CHANGELOG.md`, then run:

```bash
python scripts/check_release_version.py --tag v<version>
```

Update compatibility documents only when public contracts change. Do not reuse or move an existing release tag.

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

To test v1.1.0 explicitly:

```bash
PERSONADOCK_VERSION=v1.1.0 sh install.sh
```

```powershell
$env:PERSONADOCK_VERSION = "v1.1.0"
.\install.ps1
```

## Release verification after publication

After the GitHub Release exists, verify every installation path against the published assets rather than a workflow artifact:

```bash
curl -fsSL https://raw.githubusercontent.com/cuteyuchen/PersonaDock/main/install.sh \
  | sh -s -- --version v1.1.0
personadock --version
personadock doctor --json
personadock serve --no-browser
```

Open the local control plane and verify `/`, `/vue` and `/legacy`. On Windows, install the same fixed tag and run the complete CLI/Web smoke checks.

Do not mark the release complete until `SHA256SUMS`, all five executable archives, installer scripts and the example PersonaPack are downloadable from the GitHub Release.
