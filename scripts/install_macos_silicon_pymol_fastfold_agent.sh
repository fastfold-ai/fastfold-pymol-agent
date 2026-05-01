#!/usr/bin/env bash
set -euo pipefail

# One-shot installer for macOS Apple Silicon:
# 1) Build/install PyMOL open-source from local source checkout
# 2) Install fastfold-pymol-agent in the same conda env
# 3) Configure ~/.pymolrc to auto-load the plugin

ENV_NAME="pymol"
PYMOL_SRC_DEFAULT="../pymol-open-source"
FASTFOLD_REPO_DEFAULT="."
SKILLS_SRC_DEFAULT=""
SKILLS_REPO_URL_DEFAULT="https://github.com/fastfold-ai/skills.git"
SKILLS_REPO_BRANCH_DEFAULT="main"
SKILLS_REPO_SUBDIR_DEFAULT="skills"
COPY_SKILLS="yes"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/install_macos_silicon_pymol_fastfold_agent.sh [options]

Options:
  --env-name <name>          Conda env name (default: pymol)
  --pymol-src <path>         Path to pymol-open-source checkout (default: ../pymol-open-source)
  --agent-repo <path>        Path to fastfold-pymol-agent repo (default: current repo)
  --skills-src <path>        Local skills folder override (default: fetch from GitHub)
  --skills-repo-url <url>    Skills git repo URL (default: https://github.com/fastfold-ai/skills.git)
  --skills-repo-branch <b>   Skills git branch/tag (default: main)
  --skills-repo-subdir <d>   Skills subdir in repo (default: skills)
  --no-copy-skills           Skip copying skills into ~/.fastfold-pymol-agent/skills
  -h, --help                 Show this help

Example:
  ./scripts/install_macos_silicon_pymol_fastfold_agent.sh \
    --pymol-src ../pymol-open-source \
    --agent-repo .
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-name)
      ENV_NAME="${2:-}"
      shift 2
      ;;
    --pymol-src)
      PYMOL_SRC_DEFAULT="${2:-}"
      shift 2
      ;;
    --agent-repo)
      FASTFOLD_REPO_DEFAULT="${2:-}"
      shift 2
      ;;
    --skills-src)
      SKILLS_SRC_DEFAULT="${2:-}"
      shift 2
      ;;
    --skills-repo-url)
      SKILLS_REPO_URL_DEFAULT="${2:-}"
      shift 2
      ;;
    --skills-repo-branch)
      SKILLS_REPO_BRANCH_DEFAULT="${2:-}"
      shift 2
      ;;
    --skills-repo-subdir)
      SKILLS_REPO_SUBDIR_DEFAULT="${2:-}"
      shift 2
      ;;
    --no-copy-skills)
      COPY_SKILLS="no"
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: This installer is for macOS only." >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Warning: This script is optimized for Apple Silicon (arm64)." >&2
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda was not found. Install Miniforge first." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYMOL_SRC="$(cd "${REPO_ROOT}" && cd "${PYMOL_SRC_DEFAULT}" 2>/dev/null && pwd || true)"
AGENT_REPO="$(cd "${FASTFOLD_REPO_DEFAULT}" 2>/dev/null && pwd || true)"
SKILLS_SRC=""
if [[ -n "${SKILLS_SRC_DEFAULT}" ]]; then
  SKILLS_SRC="$(cd "${REPO_ROOT}" && cd "${SKILLS_SRC_DEFAULT}" 2>/dev/null && pwd || true)"
fi

if [[ -z "${PYMOL_SRC}" || ! -f "${PYMOL_SRC}/setup.py" ]]; then
  echo "Error: Could not find PyMOL source at: ${PYMOL_SRC_DEFAULT}" >&2
  echo "Pass --pymol-src <path-to-pymol-open-source>." >&2
  exit 1
fi

if [[ -z "${AGENT_REPO}" || ! -f "${AGENT_REPO}/setup.py" ]]; then
  echo "Error: Could not find fastfold-pymol-agent repo at: ${FASTFOLD_REPO_DEFAULT}" >&2
  echo "Pass --agent-repo <path-to-fastfold-pymol-agent>." >&2
  exit 1
fi

echo "==> Using conda env: ${ENV_NAME}"
echo "==> PyMOL source:    ${PYMOL_SRC}"
echo "==> Agent repo:      ${AGENT_REPO}"

eval "$(conda shell.bash hook)"

if conda env list | awk '{print $1}' | grep -Fx "${ENV_NAME}" >/dev/null 2>&1; then
  echo "==> Conda env '${ENV_NAME}' already exists"
else
  echo "==> Creating conda env '${ENV_NAME}'"
  conda create -n "${ENV_NAME}" python=3.11 cmake pip python-build -y
fi

conda activate "${ENV_NAME}"

echo "==> Installing PyMOL build dependencies"
conda install -y -c conda-forge glew glm libpng freetype libxml2 libnetcdf pyqt

echo "==> Installing PyMOL from source"
python -m pip install --upgrade pip setuptools wheel
python -m pip install "${PYMOL_SRC}"

echo "==> Installing fastfold-pymol-agent (editable)"
python -m pip install -e "${AGENT_REPO}"

if [[ "${COPY_SKILLS}" == "yes" ]]; then
  RESOLVED_SKILLS_SRC=""
  if [[ -n "${SKILLS_SRC}" && -d "${SKILLS_SRC}" ]]; then
    RESOLVED_SKILLS_SRC="${SKILLS_SRC}"
  else
    if ! command -v git >/dev/null 2>&1; then
      echo "Error: git is required to fetch skills from ${SKILLS_REPO_URL_DEFAULT}" >&2
      exit 1
    fi
    TMP_SKILLS_DIR="$(mktemp -d)"
    trap 'rm -rf "${TMP_SKILLS_DIR}"' EXIT
    echo "==> Fetching skills from ${SKILLS_REPO_URL_DEFAULT} (${SKILLS_REPO_BRANCH_DEFAULT})"
    git clone --depth 1 --branch "${SKILLS_REPO_BRANCH_DEFAULT}" "${SKILLS_REPO_URL_DEFAULT}" "${TMP_SKILLS_DIR}/repo"
    RESOLVED_SKILLS_SRC="${TMP_SKILLS_DIR}/repo/${SKILLS_REPO_SUBDIR_DEFAULT}"
    if [[ ! -d "${RESOLVED_SKILLS_SRC}" ]]; then
      echo "Error: skills subdir '${SKILLS_REPO_SUBDIR_DEFAULT}' not found in fetched repo." >&2
      exit 1
    fi
  fi

  if [[ -d "${RESOLVED_SKILLS_SRC}" ]]; then
    echo "==> Copying skills from ${RESOLVED_SKILLS_SRC}"
    mkdir -p "${HOME}/.fastfold-pymol-agent/skills"
    cp -R "${RESOLVED_SKILLS_SRC}/." "${HOME}/.fastfold-pymol-agent/skills/"
  else
    echo "==> Skills source not found; skipping copy"
  fi
fi

PYMOLRC="${HOME}/.pymolrc"
TMP_PYMOLRC="$(mktemp)"
touch "${PYMOLRC}"

# Remove legacy loader lines; keep everything else.
awk '
  $0 == "import promptmol" {next}
  $0 == "promptmol.__init_plugin__()" {next}
  $0 == "import fastfold_pymol_agent" {next}
  $0 == "fastfold_pymol_agent.__init_plugin__()" {next}
  {print}
' "${PYMOLRC}" > "${TMP_PYMOLRC}"

cat >> "${TMP_PYMOLRC}" <<'EOF'

# Fastfold PyMOL Agent
import fastfold_pymol_agent
fastfold_pymol_agent.__init_plugin__()
EOF

mv "${TMP_PYMOLRC}" "${PYMOLRC}"

echo ""
echo "Install complete."
echo "Next:"
echo "  conda activate ${ENV_NAME}"
echo "  pymol"
echo "Then in PyMOL:"
echo "  fastfold doctor"
echo "  fastfold ui"
