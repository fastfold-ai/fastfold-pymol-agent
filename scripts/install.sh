#!/usr/bin/env bash
set -euo pipefail

# One-shot installer for macOS/Linux:
# 1) Build/install PyMOL open-source (local checkout or temporary clone)
# 2) Install fastfold-pymol-agent in the same conda env (local editable or git URL)
# 3) Configure ~/.pymolrc to auto-load the plugin

ENV_NAME="pymol"
PYMOL_SRC_DEFAULT="../pymol-open-source"
FASTFOLD_REPO_DEFAULT="."
PYMOL_REPO_URL_DEFAULT="https://github.com/schrodinger/pymol-open-source.git"
PYMOL_REPO_REF_DEFAULT=""
AGENT_REPO_URL_DEFAULT="https://github.com/fastfold-ai/fastfold-pymol-agent.git"
AGENT_REPO_REF_DEFAULT="main"
SKILLS_SRC_DEFAULT=""
SKILLS_REPO_URL_DEFAULT="https://github.com/fastfold-ai/skills.git"
SKILLS_REPO_BRANCH_DEFAULT="main"
SKILLS_REPO_SUBDIR_DEFAULT="skills"
COPY_SKILLS="yes"
AGENT_ONLY="no"

usage() {
  cat <<'EOF'
Usage:
  bash ./scripts/install.sh [options]

Options:
  --env-name <name>          Conda env name (default: pymol)
  --pymol-src <path>         Local path to pymol-open-source checkout (optional)
  --pymol-repo-url <url>     PyMOL git repo URL fallback (default: schrodinger/pymol-open-source)
  --pymol-repo-ref <ref>     PyMOL git branch/tag/commit fallback (default: repo default branch)
  --agent-repo <path>        Local path to fastfold-pymol-agent repo (optional, editable install)
  --agent-repo-url <url>     Agent git repo fallback (default: fastfold-ai/fastfold-pymol-agent.git)
  --agent-repo-ref <ref>     Agent git branch/tag/commit fallback (default: main)
  --agent-only               Install only fastfold-pymol-agent (assumes PyMOL already installed)
  --skills-src <path>        Local skills folder override (default: fetch from GitHub)
  --skills-repo-url <url>    Skills git repo URL (default: https://github.com/fastfold-ai/skills.git)
  --skills-repo-branch <b>   Skills git branch/tag (default: main)
  --skills-repo-subdir <d>   Skills subdir in repo (default: skills)
  --no-copy-skills           Skip copying skills into ~/.fastfold-pymol-agent/skills
  -h, --help                 Show this help

Example:
  bash ./scripts/install.sh \
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
    --pymol-repo-url)
      PYMOL_REPO_URL_DEFAULT="${2:-}"
      shift 2
      ;;
    --pymol-repo-ref)
      PYMOL_REPO_REF_DEFAULT="${2:-}"
      shift 2
      ;;
    --agent-repo)
      FASTFOLD_REPO_DEFAULT="${2:-}"
      shift 2
      ;;
    --agent-repo-url)
      AGENT_REPO_URL_DEFAULT="${2:-}"
      shift 2
      ;;
    --agent-repo-ref)
      AGENT_REPO_REF_DEFAULT="${2:-}"
      shift 2
      ;;
    --agent-only)
      AGENT_ONLY="yes"
      shift 1
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

OS_NAME="$(uname -s)"
OS_ARCH="$(uname -m)"
case "${OS_NAME}" in
  Darwin|Linux)
    ;;
  *)
    echo "Error: Unsupported OS '${OS_NAME}'. This installer supports macOS and Linux." >&2
    exit 1
    ;;
esac
echo "==> Detected platform: ${OS_NAME} (${OS_ARCH})"
if [[ "${OS_NAME}" == "Darwin" && "${OS_ARCH}" != "arm64" ]]; then
  echo "Warning: macOS Intel is not the primary tested path, but installation will continue." >&2
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda was not found. Install Miniforge or Mambaforge first." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CLEANUP_PATHS=()
cleanup() {
  if [[ "${#CLEANUP_PATHS[@]}" -eq 0 ]]; then
    return
  fi
  for path in "${CLEANUP_PATHS[@]}"; do
    if [[ -n "${path}" && -d "${path}" ]]; then
      rm -rf "${path}"
    fi
  done
}
trap cleanup EXIT

PYMOL_SRC=""
if [[ "${AGENT_ONLY}" != "yes" && -n "${PYMOL_SRC_DEFAULT}" ]]; then
  PYMOL_SRC="$(cd "${REPO_ROOT}" && cd "${PYMOL_SRC_DEFAULT}" 2>/dev/null && pwd || true)"
fi
AGENT_REPO=""
if [[ -n "${FASTFOLD_REPO_DEFAULT}" ]]; then
  AGENT_REPO="$(cd "${FASTFOLD_REPO_DEFAULT}" 2>/dev/null && pwd || true)"
fi
SKILLS_SRC=""
if [[ -n "${SKILLS_SRC_DEFAULT}" ]]; then
  SKILLS_SRC="$(cd "${REPO_ROOT}" && cd "${SKILLS_SRC_DEFAULT}" 2>/dev/null && pwd || true)"
fi

if [[ "${AGENT_ONLY}" != "yes" ]]; then
  if [[ -z "${PYMOL_SRC}" || ! -f "${PYMOL_SRC}/setup.py" ]]; then
    if ! command -v git >/dev/null 2>&1; then
      echo "Error: git is required to fetch PyMOL source." >&2
      echo "Either install git or pass --pymol-src <path-to-pymol-open-source>." >&2
      exit 1
    fi
    TMP_PYMOL_DIR="$(mktemp -d)"
    CLEANUP_PATHS+=("${TMP_PYMOL_DIR}")
    echo "==> Fetching PyMOL source from ${PYMOL_REPO_URL_DEFAULT}"
    if [[ -n "${PYMOL_REPO_REF_DEFAULT}" ]]; then
      git clone --depth 1 --branch "${PYMOL_REPO_REF_DEFAULT}" "${PYMOL_REPO_URL_DEFAULT}" "${TMP_PYMOL_DIR}/repo"
    else
      git clone --depth 1 "${PYMOL_REPO_URL_DEFAULT}" "${TMP_PYMOL_DIR}/repo"
    fi
    PYMOL_SRC="${TMP_PYMOL_DIR}/repo"
  fi

  if [[ -z "${PYMOL_SRC}" || ! -f "${PYMOL_SRC}/setup.py" ]]; then
    echo "Error: Unable to resolve a valid PyMOL source checkout." >&2
    exit 1
  fi
fi

AGENT_INSTALL_MODE="local"
if [[ -z "${AGENT_REPO}" || ! -f "${AGENT_REPO}/setup.py" ]]; then
  AGENT_INSTALL_MODE="git"
fi

echo "==> Using conda env: ${ENV_NAME}"
if [[ "${AGENT_ONLY}" == "yes" ]]; then
  echo "==> Mode:            agent-only (skip PyMOL build/install)"
else
  echo "==> PyMOL source:    ${PYMOL_SRC}"
fi
if [[ "${AGENT_INSTALL_MODE}" == "local" ]]; then
  echo "==> Agent source:    ${AGENT_REPO} (editable)"
else
  echo "==> Agent source:    ${AGENT_REPO_URL_DEFAULT}@${AGENT_REPO_REF_DEFAULT}"
fi

eval "$(conda shell.bash hook)"

if conda env list | awk '{print $1}' | grep -Fx "${ENV_NAME}" >/dev/null 2>&1; then
  echo "==> Conda env '${ENV_NAME}' already exists"
else
  echo "==> Creating conda env '${ENV_NAME}'"
  conda create -n "${ENV_NAME}" python=3.11 cmake pip python-build -y
fi

conda activate "${ENV_NAME}"

python -m pip install --upgrade pip setuptools wheel

if [[ "${AGENT_ONLY}" != "yes" ]]; then
  echo "==> Installing PyMOL build dependencies"
  conda install -y -c conda-forge glew glm libpng freetype libxml2 libnetcdf pyqt

  echo "==> Installing PyMOL from source"
  python -m pip install "${PYMOL_SRC}"
fi

if [[ "${AGENT_INSTALL_MODE}" == "local" ]]; then
  echo "==> Installing fastfold-pymol-agent (editable)"
  python -m pip install -e "${AGENT_REPO}"
else
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required to install fastfold-pymol-agent from GitHub." >&2
    echo "Either install git or pass --agent-repo <local-path>." >&2
    exit 1
  fi
  echo "==> Installing fastfold-pymol-agent from git"
  python -m pip install "git+${AGENT_REPO_URL_DEFAULT}@${AGENT_REPO_REF_DEFAULT}"
fi

if [[ "${AGENT_ONLY}" == "yes" ]]; then
  if ! python -c "import pymol" >/dev/null 2>&1; then
    echo "Error: PyMOL is not importable in conda env '${ENV_NAME}'." >&2
    echo "Use full installer mode (without --agent-only) or install PyMOL first." >&2
    exit 1
  fi
fi

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
    CLEANUP_PATHS+=("${TMP_SKILLS_DIR}")
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
