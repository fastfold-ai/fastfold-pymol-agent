#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/dist"
PKG_DIR_NAME="fastfold_pymol_agent"

VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
  VERSION="$(python - <<'PY'
import pathlib
import re

setup_py = pathlib.Path("setup.py").read_text(encoding="utf-8")
match = re.search(r'version\s*=\s*"([^"]+)"', setup_py)
if not match:
    raise SystemExit("Could not detect version from setup.py")
print(match.group(1))
PY
)"
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGING_DIR}"' EXIT

mkdir -p "${OUT_DIR}" "${STAGING_DIR}/${PKG_DIR_NAME}"

python - "${ROOT_DIR}" "${STAGING_DIR}/${PKG_DIR_NAME}" <<'PY'
import pathlib
import shutil
import sys

root = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])

runtime_files = [
    "__init__.py",
    "agent_sdk.py",
    "config.py",
    "gui.py",
    "llm.py",
    "prompts.py",
    "session.py",
    "skills.py",
    "state.py",
    "utils.py",
]

for rel in runtime_files:
    src = root / rel
    if not src.is_file():
        raise SystemExit(f"Missing runtime file: {src}")
    shutil.copy2(src, dest / rel)

assets_src = root / "assets"
if assets_src.is_dir():
    shutil.copytree(assets_src, dest / "assets")
PY

ZIP_NAME="fastfold-pymol-agent-${VERSION}-plugin.zip"
ZIP_PATH="${OUT_DIR}/${ZIP_NAME}"

python - "${STAGING_DIR}" "${PKG_DIR_NAME}" "${ZIP_PATH}" <<'PY'
import pathlib
import zipfile
import sys

staging = pathlib.Path(sys.argv[1])
pkg = pathlib.Path(sys.argv[2])
zip_path = pathlib.Path(sys.argv[3])
root = staging / pkg

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            zf.write(path, path.relative_to(staging))

print(zip_path)
PY

echo "Built plugin zip:"
echo "  ${ZIP_PATH}"
