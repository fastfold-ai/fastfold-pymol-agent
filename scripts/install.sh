#!/usr/bin/env sh

# Re-exec with bash so this supports:
#   curl -LsSf .../install.sh | sh
if [ -z "${BASH_VERSION:-}" ]; then
  if ! command -v bash >/dev/null 2>&1; then
    echo "Error: bash is required to run this installer." >&2
    exit 1
  fi

  case "${0:-}" in
    sh|dash|-sh|-dash|*/sh|*/dash)
      _ff_tmp_script="$(mktemp)"
      cat > "${_ff_tmp_script}"
      exec bash "${_ff_tmp_script}" "$@"
      ;;
    *)
      exec bash "$0" "$@"
      ;;
  esac
fi

set -euo pipefail

# Guided installer (interactive, no CLI options).
if [[ $# -gt 0 ]]; then
  echo "This installer is interactive and does not accept CLI options." >&2
  echo "Run it like: curl -LsSf http://fastfold.ai/pymol-agent/install.sh | sh" >&2
  exit 1
fi

PYMOL_REPO_URL="https://github.com/schrodinger/pymol-open-source.git"
AGENT_REPO_URL="https://github.com/fastfold-ai/fastfold-pymol-agent.git"
AGENT_REPO_REF="main"
SKILLS_REPO_URL="https://github.com/fastfold-ai/skills.git"
SKILLS_REPO_BRANCH="main"
SKILLS_REPO_SUBDIR="skills"

ensure_tty_input() {
  if [[ ! -t 0 ]]; then
    if [[ -r /dev/tty ]]; then
      exec < /dev/tty
    else
      echo "Error: interactive installer requires a TTY." >&2
      exit 1
    fi
  fi
}

prompt_default() {
  local label="$1"
  local default="$2"
  local value=""
  read -r -p "${label} [${default}]: " value || true
  if [[ -z "${value// }" ]]; then
    printf "%s" "${default}"
  else
    printf "%s" "${value}"
  fi
}

prompt_yes_no() {
  local prompt="$1"
  local default="$2" # y|n
  local hint=""
  local answer=""
  if [[ "${default}" == "y" ]]; then
    hint="[Y/n]"
  else
    hint="[y/N]"
  fi
  while true; do
    read -r -p "${prompt} ${hint} " answer || true
    answer="${answer:-$default}"
    case "${answer,,}" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

require_git() {
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required for this step." >&2
    exit 1
  fi
}

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

ensure_tty_input

echo ""
echo "Fastfold PyMOL Agent Installer"
echo "Choose install mode:"
echo "  1) Full install (default): PyMOL open-source + Fastfold PyMOL Agent"
echo "  2) Agent-only: Fastfold PyMOL Agent only (PyMOL must already be installed)"
echo ""

INSTALL_MODE="full"
while true; do
  read -r -p "Install mode [1/2] (default 1): " MODE_CHOICE || true
  MODE_CHOICE="${MODE_CHOICE:-1}"
  case "${MODE_CHOICE}" in
    1) INSTALL_MODE="full"; break ;;
    2) INSTALL_MODE="agent-only"; break ;;
    *) echo "Please choose 1 or 2." ;;
  esac
done

ENV_NAME="$(prompt_default "Conda environment name" "pymol")"

INSTALL_SKILLS="yes"
if prompt_yes_no "Install official Fastfold skills pack?" "y"; then
  INSTALL_SKILLS="yes"
else
  INSTALL_SKILLS="no"
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

LOCAL_AGENT_REPO=""
if [[ -f "${REPO_ROOT}/setup.py" ]]; then
  LOCAL_AGENT_REPO="${REPO_ROOT}"
fi

PYMOL_SRC=""
if [[ "${INSTALL_MODE}" == "full" ]]; then
  LOCAL_PYMOL_SRC="$(cd "${REPO_ROOT}" && cd "../pymol-open-source" 2>/dev/null && pwd || true)"
  if [[ -n "${LOCAL_PYMOL_SRC}" && -f "${LOCAL_PYMOL_SRC}/setup.py" ]]; then
    PYMOL_SRC="${LOCAL_PYMOL_SRC}"
  else
    require_git
    TMP_PYMOL_DIR="$(mktemp -d)"
    CLEANUP_PATHS+=("${TMP_PYMOL_DIR}")
    echo "==> Fetching PyMOL source from ${PYMOL_REPO_URL}"
    git clone --depth 1 "${PYMOL_REPO_URL}" "${TMP_PYMOL_DIR}/repo"
    PYMOL_SRC="${TMP_PYMOL_DIR}/repo"
  fi

  if [[ -z "${PYMOL_SRC}" || ! -f "${PYMOL_SRC}/setup.py" ]]; then
    echo "Error: Unable to resolve a valid PyMOL source checkout." >&2
    exit 1
  fi
fi

AGENT_INSTALL_MODE="local"
if [[ -z "${LOCAL_AGENT_REPO}" || ! -f "${LOCAL_AGENT_REPO}/setup.py" ]]; then
  AGENT_INSTALL_MODE="git"
fi

echo "==> Using conda env: ${ENV_NAME}"
if [[ "${INSTALL_MODE}" == "agent-only" ]]; then
  echo "==> Mode:            agent-only"
else
  echo "==> PyMOL source:    ${PYMOL_SRC}"
fi
if [[ "${AGENT_INSTALL_MODE}" == "local" ]]; then
  echo "==> Agent source:    ${LOCAL_AGENT_REPO} (editable)"
else
  echo "==> Agent source:    ${AGENT_REPO_URL}@${AGENT_REPO_REF}"
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

if [[ "${INSTALL_MODE}" == "full" ]]; then
  echo "==> Installing PyMOL build dependencies"
  conda install -y -c conda-forge glew glm libpng freetype libxml2 libnetcdf pyqt

  echo "==> Installing PyMOL from source"
  python -m pip install "${PYMOL_SRC}"
fi

if [[ "${AGENT_INSTALL_MODE}" == "local" ]]; then
  echo "==> Installing fastfold-pymol-agent (editable)"
  python -m pip install -e "${LOCAL_AGENT_REPO}"
else
  require_git
  echo "==> Installing fastfold-pymol-agent from git"
  python -m pip install "git+${AGENT_REPO_URL}@${AGENT_REPO_REF}"
fi

if [[ "${INSTALL_MODE}" == "agent-only" ]]; then
  if ! python -c "import pymol" >/dev/null 2>&1; then
    echo "Error: PyMOL is not importable in conda env '${ENV_NAME}'." >&2
    echo "Re-run installer and choose full install, or install PyMOL in this env first." >&2
    exit 1
  fi
fi

if [[ "${INSTALL_SKILLS}" == "yes" ]]; then
  RESOLVED_SKILLS_SRC=""
  LOCAL_SKILLS_SRC="$(cd "${REPO_ROOT}" && cd "../fastfold-skills/skills" 2>/dev/null && pwd || true)"
  if [[ -n "${LOCAL_SKILLS_SRC}" && -d "${LOCAL_SKILLS_SRC}" ]]; then
    RESOLVED_SKILLS_SRC="${LOCAL_SKILLS_SRC}"
  else
    require_git
    TMP_SKILLS_DIR="$(mktemp -d)"
    CLEANUP_PATHS+=("${TMP_SKILLS_DIR}")
    echo "==> Fetching skills from ${SKILLS_REPO_URL} (${SKILLS_REPO_BRANCH})"
    git clone --depth 1 --branch "${SKILLS_REPO_BRANCH}" "${SKILLS_REPO_URL}" "${TMP_SKILLS_DIR}/repo"
    RESOLVED_SKILLS_SRC="${TMP_SKILLS_DIR}/repo/${SKILLS_REPO_SUBDIR}"
    if [[ ! -d "${RESOLVED_SKILLS_SRC}" ]]; then
      echo "Error: skills subdir '${SKILLS_REPO_SUBDIR}' not found in fetched repo." >&2
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
