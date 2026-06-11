#!/usr/bin/env bash
# Initialize / refresh the dla development environment.
#
# Why this script exists (macOS gotcha): files written into `.venv/...`
# inherit the macOS UF_HIDDEN file flag because the parent `.venv`
# directory is itself dot-hidden. Python 3.11.14+ / 3.12.12+ skip ANY
# .pth file whose UF_HIDDEN flag is set, so `_editable_impl_dla.pth`
# (and every other .pth file in site-packages) gets silently ignored
# and `import dla` fails. We fix this by:
#   1. Calling `uv sync --all-packages` at the workspace root to populate
#      the shared venv,
#   2. Writing our own visible-name `dla.pth` so behavior doesn't depend
#      on uv's internal naming convention, and
#   3. Stripping UF_HIDDEN from every .pth file in site-packages.
#
# Run this any time after `rm -rf .venv` or `uv sync --reinstall`.
# Run from anywhere — the script cds to the workspace root automatically.

set -euo pipefail

# apps/dla/scripts/ -> apps/dla/ -> apps/ -> workspace root
WORKSPACE_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${WORKSPACE_ROOT}"

uv sync --all-packages "$@"

PY_VERSION="$(./.venv/bin/python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
SP=".venv/lib/${PY_VERSION}/site-packages"

if [[ ! -d "${SP}" ]]; then
    echo "error: ${SP} does not exist; uv sync may have failed." >&2
    exit 1
fi

DLA_SRC="${WORKSPACE_ROOT}/apps/dla/src"
echo "${DLA_SRC}" > "${SP}/dla.pth"

# Strip UF_HIDDEN from every .pth file (macOS only; on Linux this is a no-op
# because chflags doesn't exist there, so we tolerate failure).
if command -v chflags > /dev/null 2>&1; then
    for f in "${SP}"/*.pth; do
        chflags nohidden "${f}" 2>/dev/null || true
    done
fi

echo "Installed dla.pth -> ${DLA_SRC} in ${SP}"
echo "Stripped UF_HIDDEN from .pth files (macOS)"

if ! ./.venv/bin/python -c "import dla; print(f'OK: dla.__file__ = {dla.__file__}')"; then
    echo "error: dla import still fails after pth fix." >&2
    exit 1
fi
