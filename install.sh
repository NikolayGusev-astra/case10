#!/usr/bin/env bash
# install.sh — One-command installer for Case 10 Pipeline
#
# Usage:
#   curl -fsSL https://hermes-agent.ru/case10/install.sh | bash
#   # or locally:
#   bash install.sh
#
# This script:
#   1. Checks Python 3.10+
#   2. Creates a virtual environment (optional)
#   3. Installs Python dependencies
#   4. Copies the config template if not present
#   5. Prints next steps

set -euo pipefail

REPO_NAME="case10"
REQUIRED_PYTHON="3.10"

# ----------------------------------------
# Colors
# ----------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ----------------------------------------
# Locate the repository root
# ----------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR" && pwd)"

if [[ ! -f "$REPO_DIR/tools/case10_pipeline.py" ]]; then
    err "Cannot find tools/case10_pipeline.py in $REPO_DIR"
    err "Please run install.sh from the case10 repository root."
    exit 1
fi

info "Installing $REPO_NAME in $REPO_DIR"

# ----------------------------------------
# Python version check
# ----------------------------------------
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        if [[ -n "$ver" ]] && python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python $REQUIRED_PYTHON+ is required. Install it first."
    err "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    err "  macOS:         brew install python@3.11"
    exit 1
fi
ok "Python $("$PYTHON" --version) found"

# ----------------------------------------
# Virtual environment (optional)
# ----------------------------------------
USE_VENV=true
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    info "Already in a virtual environment ($VIRTUAL_ENV), skipping venv creation"
    USE_VENV=false
elif [[ -d "$REPO_DIR/.venv" ]]; then
    info "Virtual environment already exists at $REPO_DIR/.venv"
    USE_VENV=false
else
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$REPO_DIR/.venv"
    ok "Virtual environment created at $REPO_DIR/.venv"
fi

if $USE_VENV && [[ -z "${VIRTUAL_ENV:-}" ]]; then
    source "$REPO_DIR/.venv/bin/activate"
fi

# ----------------------------------------
# Install dependencies
# ----------------------------------------
info "Installing Python dependencies..."

# Compile list of requirements
cat > /tmp/case10_requirements.txt <<REQ
pyyaml>=6.0
requests>=2.28
python-dotenv>=1.0
atlassian-python-api>=3.0
REQ

pip install --quiet --upgrade pip setuptools wheel 2>/dev/null
pip install --quiet -r /tmp/case10_requirements.txt
rm -f /tmp/case10_requirements.txt
ok "Dependencies installed"

# ----------------------------------------
# Configuration files
# ----------------------------------------
if [[ ! -f "$REPO_DIR/.env" ]]; then
    if [[ -f "$REPO_DIR/config/.env.example" ]]; then
        cp "$REPO_DIR/config/.env.example" "$REPO_DIR/.env"
        ok "Created .env from template — edit it to add your API keys"
    fi
else
    ok ".env already exists"
fi

# ----------------------------------------
# Install Hermes Agent skill (optional)
# ----------------------------------------
if command -v hermes &>/dev/null; then
    info "Hermes Agent detected — registering skill..."
    SKILL_DIR="${HOME}/.hermes/skills/${REPO_NAME}"
    mkdir -p "$SKILL_DIR"
    if [[ -f "$REPO_DIR/SKILL.md" ]]; then
        cp "$REPO_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
        ok "Hermes skill registered at $SKILL_DIR"
    fi
else
    warn "Hermes Agent not found — skipping skill registration"
    warn "Install it first: pip install hermes-agent"
fi

# ----------------------------------------
# Summary
# ----------------------------------------
echo ""
echo "============================================"
echo -e "${GREEN}  Case 10 Pipeline установлен!${NC}"
echo "============================================"
echo ""
echo "  Repository : $REPO_DIR"
echo ""
echo "  Next steps:"
echo "    1. Edit  .env        — укажите API-ключи"
echo "    2. Edit  config/org_structure.yaml — ваша оргструктура"
echo "    3. Run   python -m tools.case10_pipeline --input sample.txt"
echo "    4. Tests make test"
echo ""
echo "  Документация: https://hermes-agent.ru/assistant/case10.html"
echo "============================================"

# Auto-activate hint
if $USE_VENV && [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo ""
    echo -e "${YELLOW}  Активируйте venv: source $REPO_DIR/.venv/bin/activate${NC}"
fi
