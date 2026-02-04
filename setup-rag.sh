#!/usr/bin/env bash
# =============================================================================
# RAG Setup Script
# Creates Python venv, installs dependencies, downloads embedding model,
# and pulls SearXNG Docker container.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
source "$SCRIPT_DIR/lib/common.sh"

# Set up signal handlers
setup_signal_handlers

# Initialize paths
init_paths "$SCRIPT_DIR"

# RAG-specific paths
RAG_DIR="$SCRIPT_DIR/rag"
RAG_VENV="$RAG_DIR/.venv"
RAG_REQUIREMENTS="$RAG_DIR/requirements.txt"

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

print_banner "RAG Setup"

# Check for Python
print_header "Checking Dependencies"
echo

PYTHON_CMD=""
for cmd in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [[ $major -ge 3 && $minor -ge 10 ]]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    print_error "Python 3.10+ is required but not found"
    echo "Please install Python 3.10 or newer"
    exit 1
fi

echo -e "  $CHECKMARK Python: $($PYTHON_CMD --version)"

# Check for pip
if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
    print_error "pip is not available"
    echo "Please ensure pip is installed for your Python"
    exit 1
fi
echo -e "  $CHECKMARK pip available"

# Check for Docker (optional, for SearXNG)
HAS_DOCKER=false
if command -v docker &>/dev/null; then
    if docker info &>/dev/null; then
        HAS_DOCKER=true
        echo -e "  $CHECKMARK Docker available"
    else
        echo -e "  $WARNMARK Docker installed but not running (SearXNG will be skipped)"
    fi
else
    echo -e "  $WARNMARK Docker not installed (SearXNG web search will not be available)"
fi

# -----------------------------------------------------------------------------
# Create Python Virtual Environment
# -----------------------------------------------------------------------------

print_header "Setting Up Python Environment"
echo

if [[ -d "$RAG_VENV" ]]; then
    print_status "Virtual environment exists, updating..."
else
    print_status "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$RAG_VENV"
fi

# Activate venv
source "$RAG_VENV/bin/activate"

# Upgrade pip
start_spinner "Upgrading pip"
pip install --upgrade pip --quiet 2>/dev/null
stop_spinner true "pip upgraded"

# Install requirements
start_spinner "Installing dependencies (this may take a few minutes)"
pip install -r "$RAG_REQUIREMENTS" --quiet 2>/dev/null
stop_spinner true "Dependencies installed"

# -----------------------------------------------------------------------------
# Download Embedding Model
# -----------------------------------------------------------------------------

print_header "Downloading Embedding Model"
echo

print_status "Model: nomic-ai/nomic-embed-text-v1.5"
echo -e "${DIM}This is a ~270MB download and will be cached for future use${NC}"
echo

start_spinner "Downloading embedding model"

# Pre-download the model by importing embeddings module
"$RAG_VENV/bin/python" -c "
import os
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', device='cpu', trust_remote_code=True)
print(f'Model loaded: {model.get_sentence_embedding_dimension()} dimensions')
" 2>/dev/null

stop_spinner true "Embedding model ready"

# -----------------------------------------------------------------------------
# Set Up SearXNG (Optional)
# -----------------------------------------------------------------------------

if [[ "$HAS_DOCKER" == true ]]; then
    print_header "Setting Up SearXNG"
    echo
    
    # Check if SearXNG is already running
    if docker ps --format '{{.Names}}' | grep -q '^searxng$'; then
        print_status "SearXNG is already running"
    else
        print_status "Pulling SearXNG image..."
        start_spinner "Pulling docker image"
        docker pull searxng/searxng:latest --quiet 2>/dev/null || true
        stop_spinner true "SearXNG image ready"
        
        print_status "Starting SearXNG container..."
        # Export UID/GID for docker-compose to run as current user (prevents permission issues)
        export UID GID=$(id -g)
        if docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d searxng 2>/dev/null; then
            print_success "SearXNG started on port 8888"
        else
            print_warning "Failed to start SearXNG (web search will not be available)"
        fi
    fi
else
    echo
    print_warning "Skipping SearXNG setup (Docker not available)"
    echo -e "${DIM}Web search will not be available. Install Docker to enable it.${NC}"
fi

# -----------------------------------------------------------------------------
# Create Data Directory
# -----------------------------------------------------------------------------

mkdir -p "$RAG_DIR/data/lancedb"

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

echo
print_header "Setup Complete"
echo
echo -e "${GREEN}${BOLD}RAG system is ready!${NC}"
echo
echo -e "  ${BOLD}Python venv:${NC}     $RAG_VENV"
echo -e "  ${BOLD}Embedding model:${NC} nomic-ai/nomic-embed-text-v1.5"
echo -e "  ${BOLD}Vector store:${NC}    $RAG_DIR/data/lancedb"

if [[ "$HAS_DOCKER" == true ]]; then
    echo -e "  ${BOLD}Web search:${NC}      http://127.0.0.1:8888 (SearXNG)"
fi

echo
echo -e "${BOLD}Next steps:${NC}"
echo
echo -e "  1. Start the RAG server:"
echo -e "     ${CYAN}./start-rag.sh${NC}"
echo
echo -e "  2. Index some documents:"
echo -e "     ${CYAN}./rag-index.sh --collection coding ~/my-project/${NC}"
echo
echo -e "  3. Search your documents:"
echo -e "     ${CYAN}./rag-search.sh --collection coding \"how does auth work\"${NC}"
echo
echo -e "  4. Or start everything together:"
echo -e "     ${CYAN}./start-server.sh qwen3${NC}  ${DIM}(RAG auto-starts by default)${NC}"
echo
