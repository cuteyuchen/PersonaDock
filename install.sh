#!/usr/bin/env sh
set -eu

REPOSITORY="cuteyuchen/PersonaDock"
VERSION="${PERSONADOCK_VERSION:-latest}"
INSTALL_DIR="${PERSONADOCK_INSTALL_DIR:-${HOME}/.local/bin}"

usage() {
  cat <<'EOF'
Install the PersonaDock standalone executable.

Usage:
  install.sh [--version v1.1.0] [--install-dir PATH]

Environment variables:
  PERSONADOCK_VERSION      Release tag, or "latest" (default)
  PERSONADOCK_INSTALL_DIR  Destination directory (default: ~/.local/bin)
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      [ "$#" -ge 2 ] || { echo "Missing value for --version" >&2; exit 2; }
      VERSION="$2"
      shift 2
      ;;
    --install-dir)
      [ "$#" -ge 2 ] || { echo "Missing value for --install-dir" >&2; exit 2; }
      INSTALL_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v curl >/dev/null 2>&1 || {
  echo "curl is required to install PersonaDock." >&2
  exit 1
}

os="$(uname -s)"
arch="$(uname -m)"

case "$os" in
  Linux) platform="linux" ;;
  Darwin) platform="macos" ;;
  *)
    echo "Unsupported operating system: $os" >&2
    exit 1
    ;;
esac

case "$arch" in
  x86_64|amd64) architecture="x86_64" ;;
  arm64|aarch64) architecture="arm64" ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    exit 1
    ;;
esac

asset="personadock-${platform}-${architecture}.tar.gz"
if [ "$VERSION" = "latest" ]; then
  base_url="https://github.com/${REPOSITORY}/releases/latest/download"
else
  case "$VERSION" in
    v*) ;;
    *) VERSION="v${VERSION}" ;;
  esac
  base_url="https://github.com/${REPOSITORY}/releases/download/${VERSION}"
fi

temporary="$(mktemp -d 2>/dev/null || mktemp -d -t personadock)"
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

archive="$temporary/$asset"
checksums="$temporary/SHA256SUMS"

echo "Downloading $asset..."
curl -fsSL "$base_url/$asset" -o "$archive"
curl -fsSL "$base_url/SHA256SUMS" -o "$checksums"

expected="$(awk -v name="$asset" '$2 == name || $2 == "*" name {print $1; exit}' "$checksums")"
[ -n "$expected" ] || {
  echo "SHA256SUMS does not contain $asset." >&2
  exit 1
}

if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "$archive" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
else
  echo "sha256sum or shasum is required to verify the download." >&2
  exit 1
fi

[ "$actual" = "$expected" ] || {
  echo "Checksum verification failed for $asset." >&2
  exit 1
}

mkdir -p "$temporary/extracted"
tar -xzf "$archive" -C "$temporary/extracted"
source_binary="$temporary/extracted/personadock"
[ -f "$source_binary" ] || {
  echo "The release archive does not contain personadock." >&2
  exit 1
}

mkdir -p "$INSTALL_DIR"
destination="$INSTALL_DIR/personadock"
cp "$source_binary" "$destination"
chmod 755 "$destination"

if [ "$platform" = "macos" ] && command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "$destination" >/dev/null 2>&1 || true
fi

"$destination" --help >/dev/null

echo "PersonaDock installed at $destination"
case ":${PATH:-}:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    echo "Add $INSTALL_DIR to PATH, for example:"
    echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
    ;;
esac
