#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# OpenHands Frontend Launcher
# Starts the OpenHands AI coding assistant with llama.cpp backend
# =============================================================================

# -----------------------------------------------------------------------------
# Early --help Check
# -----------------------------------------------------------------------------

for arg in "$@"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
        echo "Usage: ./start-openhands.sh [OPTIONS]"
        echo
        echo "Start the OpenHands AI coding assistant."
        echo "Connects to your llama.cpp server (local or remote)."
        echo
        echo "Options:"
        echo "  --workspace PATH   Set the workspace directory (default: current dir)"
        echo "  --llm-url URL      Override the LLM server URL"
        echo "  --model MODEL      Model name to use (default: auto-detect)"
        echo "  --stop             Stop running OpenHands container"
        echo "  --status           Show OpenHands container status"
        echo "  --logs             Show OpenHands logs"
        echo "  --help, -h         Show this help message"
        echo
        echo "Environment Variables (.env):"
        echo "  REMOTE_LLM_URL         Remote LLM server URL"
        echo "  OPENHANDS_WORKSPACE    Default workspace directory"
        echo "  OPENHANDS_VERSION      Docker image version (default: 1.3.0)"
        echo
        echo "Examples:"
        echo "  ./start-openhands.sh                           # Start with defaults"
        echo "  ./start-openhands.sh --workspace ~/projects    # Custom workspace"
        echo "  ./start-openhands.sh --llm-url http://gpu:8080 # Remote LLM"
        echo "  ./start-openhands.sh --stop                    # Stop container"
        exit 0
    fi
done

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Source Common Library
# -----------------------------------------------------------------------------

if [[ ! -f "$SCRIPT_DIR/lib/common.sh" ]]; then
    echo "ERROR: lib/common.sh not found"
    echo "Please ensure the repository is complete."
    exit 1
fi

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

# Initialize paths
init_paths "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Load Configuration
# -----------------------------------------------------------------------------

if [[ -f "$LOCAL_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$LOCAL_ENV"
fi

# Defaults
OPENHANDS_VERSION="${OPENHANDS_VERSION:-1.3.0}"
OPENHANDS_WORKSPACE="${OPENHANDS_WORKSPACE:-$(pwd)}"
OPENHANDS_PORT="${OPENHANDS_PORT:-3000}"
CONTAINER_NAME="openhands-app"

# LLM URL: prefer REMOTE_LLM_URL, fallback to local
if [[ -n "${REMOTE_LLM_URL:-}" ]]; then
    LLM_BASE_URL="$REMOTE_LLM_URL"
else
    LLM_BASE_URL="http://host.docker.internal:${LLAMA_PORT:-8080}"
fi

# -----------------------------------------------------------------------------
# Parse Command Line Arguments
# -----------------------------------------------------------------------------

ACTION="start"
WORKSPACE_OVERRIDE=""
LLM_URL_OVERRIDE=""
MODEL_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --workspace)
            WORKSPACE_OVERRIDE="$2"
            shift 2
            ;;
        --llm-url)
            LLM_URL_OVERRIDE="$2"
            shift 2
            ;;
        --model)
            MODEL_OVERRIDE="$2"
            shift 2
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --logs)
            ACTION="logs"
            shift
            ;;
        *)
            print_warning "Unknown option: $1"
            shift
            ;;
    esac
done

# Apply overrides
[[ -n "$WORKSPACE_OVERRIDE" ]] && OPENHANDS_WORKSPACE="$WORKSPACE_OVERRIDE"
[[ -n "$LLM_URL_OVERRIDE" ]] && LLM_BASE_URL="$LLM_URL_OVERRIDE"

# Resolve workspace to absolute path
OPENHANDS_WORKSPACE="$(cd "$OPENHANDS_WORKSPACE" 2>/dev/null && pwd)" || {
    print_error "Workspace directory does not exist: $OPENHANDS_WORKSPACE"
    exit 1
}

# -----------------------------------------------------------------------------
# Check Docker
# -----------------------------------------------------------------------------

check_docker() {
    if ! command -v docker &>/dev/null; then
        print_error "Docker is not installed"
        echo
        echo "Install Docker:"
        echo "  https://docs.docker.com/engine/install/"
        echo
        exit 1
    fi
    
    if ! docker info &>/dev/null 2>&1; then
        print_error "Docker daemon is not running"
        echo
        echo "Start Docker with:"
        echo "  sudo systemctl start docker"
        echo
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Status Action
# -----------------------------------------------------------------------------

if [[ "$ACTION" == "status" ]]; then
    print_header "OpenHands Status"
    echo
    
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "  $CHECKMARK Container: ${GREEN}running${NC}"
        echo -e "  $CHECKMARK URL: http://localhost:${OPENHANDS_PORT}"
        echo
        echo "Container info:"
        docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        echo -e "  $CROSSMARK Container: ${RED}not running${NC}"
    fi
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Stop Action
# -----------------------------------------------------------------------------

if [[ "$ACTION" == "stop" ]]; then
    print_header "Stopping OpenHands"
    echo
    
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
        docker stop "$CONTAINER_NAME" >/dev/null
        print_success "OpenHands stopped"
    else
        print_status "OpenHands is not running"
    fi
    exit 0
fi

# -----------------------------------------------------------------------------
# Logs Action
# -----------------------------------------------------------------------------

if [[ "$ACTION" == "logs" ]]; then
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
        docker logs -f "$CONTAINER_NAME"
    else
        print_error "OpenHands container not found"
        exit 1
    fi
    exit 0
fi

# -----------------------------------------------------------------------------
# Start Action
# -----------------------------------------------------------------------------

check_docker

print_banner "OpenHands"

# Check if already running
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    print_warning "OpenHands is already running"
    echo
    echo "  URL: http://localhost:${OPENHANDS_PORT}"
    echo
    echo "Options:"
    echo "  ./start-openhands.sh --stop   Stop the container"
    echo "  ./start-openhands.sh --logs   View logs"
    exit 0
fi

# Remove old stopped container if exists
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# Check if LLM server is reachable (if local)
if [[ "$LLM_BASE_URL" == *"host.docker.internal"* ]]; then
    LOCAL_URL="${LLM_BASE_URL/host.docker.internal/127.0.0.1}"
    if ! curl -sf "${LOCAL_URL}/health" &>/dev/null; then
        print_warning "LLM server not responding at ${LOCAL_URL}"
        echo
        echo "Start the LLM server first:"
        echo "  ./start-server.sh <model-id>"
        echo
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

print_status "Starting OpenHands..."
echo
echo -e "  ${BOLD}Version:${NC}    $OPENHANDS_VERSION"
echo -e "  ${BOLD}Workspace:${NC}  $OPENHANDS_WORKSPACE"
echo -e "  ${BOLD}LLM URL:${NC}    $LLM_BASE_URL"
echo -e "  ${BOLD}Web UI:${NC}     http://localhost:${OPENHANDS_PORT}"
echo

# Determine model name
if [[ -n "$MODEL_OVERRIDE" ]]; then
    MODEL_NAME="$MODEL_OVERRIDE"
else
    # Try to auto-detect from downloaded models
    MODEL_NAME=""
    if [[ -f "$MODELS_CONF" ]]; then
        load_models_conf
        for model in "${MODEL_ORDER[@]}"; do
            IFS='|' read -r category _ gguf_file _ _ <<< "${MODEL_INFO[$model]}"
            if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
                MODEL_NAME="$model"
                break
            fi
        done
    fi
    
    if [[ -z "$MODEL_NAME" ]]; then
        MODEL_NAME="llama.cpp"
    fi
fi

# Pull image if not exists
if ! docker image inspect "docker.all-hands.dev/all-hands-ai/openhands:${OPENHANDS_VERSION}" &>/dev/null 2>&1; then
    print_status "Pulling OpenHands image (this may take a few minutes)..."
    docker pull "docker.all-hands.dev/all-hands-ai/openhands:${OPENHANDS_VERSION}"
fi

# Start container
docker run -d \
    --name "$CONTAINER_NAME" \
    -p "${OPENHANDS_PORT}:3000" \
    --add-host host.docker.internal:host-gateway \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${OPENHANDS_WORKSPACE}:/opt/workspace_base" \
    -e SANDBOX_RUNTIME_CONTAINER_IMAGE="docker.all-hands.dev/all-hands-ai/runtime:${OPENHANDS_VERSION}" \
    -e LLM_BASE_URL="${LLM_BASE_URL}/v1" \
    -e LLM_MODEL="openai/${MODEL_NAME}" \
    -e LLM_API_KEY="not-needed" \
    "docker.all-hands.dev/all-hands-ai/openhands:${OPENHANDS_VERSION}" >/dev/null

print_success "OpenHands started!"
echo
echo -e "${BOLD}Access OpenHands:${NC}"
echo "  http://localhost:${OPENHANDS_PORT}"
echo
echo -e "${BOLD}Commands:${NC}"
echo "  ./start-openhands.sh --logs    View logs"
echo "  ./start-openhands.sh --stop    Stop OpenHands"
echo "  ./start-openhands.sh --status  Check status"
echo
