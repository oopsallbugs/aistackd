#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Ollama ROCm Setup Script
# Linux-only setup for AMD GPUs with automatic system detection
# =============================================================================

# -----------------------------------------------------------------------------
# OS Check - ROCm only supports Linux
# -----------------------------------------------------------------------------

if [[ "$(uname -s)" != "Linux" ]]; then
    echo ""
    echo "ERROR: This setup only works on Linux."
    echo ""
    echo "ROCm (AMD's GPU compute platform) is Linux-only."
    echo ""
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "For macOS, use the macOS setup script instead:"
        echo "  ./setup-macos.sh"
        echo ""
        echo "Or install Ollama manually:"
        echo "  brew install ollama"
    elif [[ "$(uname -s)" =~ MINGW|MSYS|CYGWIN ]] || [[ -n "${OS:-}" && "${OS}" == "Windows_NT" ]]; then
        echo "Windows detected."
        echo ""
        echo "It would be a mass pro gamer move for you to install Linux right now."
        echo ""
        echo "Your options:"
        echo "  1. WSL2 with Ubuntu (cringe)"
        echo "  2. Dual boot Linux (acceptable)"
        echo "  3. Full Linux install (legendary)"
        echo ""
        echo "Get started:"
        echo "  Stock standard: https://ubuntu.com/download"
        echo "  If you are an insane person: https://omarchy.org/"
        echo "  Giga chads: https://archlinux.org/download/"
        echo ""
        echo "Then run this setup script again inside your new premium Linux environment."
    else
        echo "For other operating systems, good luck :)"
    fi
    echo ""
    exit 1
fi

# Change to script directory (works regardless of where user runs it from)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Colors and Output Helpers
# -----------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'
CHECKMARK="${GREEN}✓${NC}"
CROSSMARK="${RED}✗${NC}"
WARNMARK="${YELLOW}!${NC}"

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

ENV_FILE="$SCRIPT_DIR/.env"
MODELS_CONF="$SCRIPT_DIR/models.conf"
METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
OPENCODE_CONFIG="$HOME/.config/opencode/opencode.json"

# Parse command line arguments
SKIP_MODELS=false
FORCE_ENV=false
NON_INTERACTIVE=false
FIX_PERMISSIONS=false
IGNORE_WARNINGS=false
RUN_UPDATE=false
RUN_STATUS=false
SELECTED_MODELS=()
for arg in "$@"; do
    case $arg in
        --skip-models) SKIP_MODELS=true ;;
        --force-env) FORCE_ENV=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --fix-permissions) FIX_PERMISSIONS=true ;;
        --ignore-warnings) IGNORE_WARNINGS=true ;;
        --update) RUN_UPDATE=true ;;
        --status) RUN_STATUS=true ;;
        --help|-h)
            echo "Usage: ./setup.sh [OPTIONS]"
            echo ""
            echo "Commands:"
            echo "  --status            Show current Ollama status and configuration"
            echo "  --update            Update Ollama to latest version"
            echo ""
            echo "Setup Options:"
            echo "  --skip-models       Skip model selection and downloading"
            echo "  --force-env         Regenerate .env file even if it exists"
            echo "  --non-interactive   Use default selections (no prompts)"
            echo "  --fix-permissions   Attempt to fix user group permissions (requires sudo)"
            echo "  --ignore-warnings   Continue setup even with non-critical warnings"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "Files:"
            echo "  models.conf         Edit this file to customize available models"
            echo "  .env                Generated config (system-specific)"
            echo "  .env.example        Template for manual configuration"
            echo ""
            echo "Examples:"
            echo "  ./setup.sh                      # Interactive setup"
            echo "  ./setup.sh --status             # Check current status"
            echo "  ./setup.sh --update             # Update Ollama image"
            echo "  ./setup.sh --fix-permissions    # Fix group permissions first"
            echo "  ./setup.sh --skip-models        # Setup without downloading models"
            echo "  ./setup.sh --non-interactive    # Automated setup with defaults"
            exit 0
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Error Handling
# -----------------------------------------------------------------------------

# Trap errors and provide helpful messages
trap 'handle_error $? $LINENO' ERR

handle_error() {
    local exit_code=$1
    local line_number=$2
    echo ""
    print_error "An error occurred on line $line_number (exit code: $exit_code)"
    echo ""
    echo "Common solutions:"
    echo "  - Check Docker is running: sudo systemctl status docker"
    echo "  - Check permissions: groups (should show video and render)"
    echo "  - Check logs: docker compose logs"
    echo "  - Re-run with: ./setup.sh --ignore-warnings"
    echo ""
    exit "$exit_code"
}

# Helper function to prompt user on warnings
prompt_continue() {
    local message=$1
    if [ "$NON_INTERACTIVE" = true ] || [ "$IGNORE_WARNINGS" = true ]; then
        print_warning "$message - continuing anyway (--ignore-warnings or --non-interactive)"
        return 0
    fi
    echo ""
    print_warning "$message"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "Setup cancelled by user"
        exit 1
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Model Selection Functions
# -----------------------------------------------------------------------------

declare -A MODEL_SELECTED
declare -a MODEL_ORDER
declare -A MODEL_INFO
declare -A CATEGORY_SEEN

# Model metadata for OpenCode config
declare -A MODEL_DISPLAY_NAME
declare -A MODEL_CONTEXT_LIMIT
declare -A MODEL_OUTPUT_LIMIT
DEFAULT_CONTEXT=32768
DEFAULT_OUTPUT=8192

load_metadata_conf() {
    # Load model metadata for OpenCode config generation
    if [[ ! -f "$METADATA_CONF" ]]; then
        print_warning "models-metadata.conf not found, using defaults for OpenCode config"
        return
    fi
    
    while IFS='|' read -r model display_name context_limit output_limit || [[ -n "$model" ]]; do
        # Skip comments and empty lines
        [[ "$model" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$model" ]] && continue
        
        # Trim whitespace
        model="${model#"${model%%[![:space:]]*}"}"
        model="${model%"${model##*[![:space:]]}"}"
        display_name="${display_name#"${display_name%%[![:space:]]*}"}"
        display_name="${display_name%"${display_name##*[![:space:]]}"}"
        context_limit="${context_limit#"${context_limit%%[![:space:]]*}"}"
        context_limit="${context_limit%"${context_limit##*[![:space:]]}"}"
        output_limit="${output_limit#"${output_limit%%[![:space:]]*}"}"
        output_limit="${output_limit%"${output_limit##*[![:space:]]}"}"
        
        MODEL_DISPLAY_NAME["$model"]="$display_name"
        MODEL_CONTEXT_LIMIT["$model"]="$context_limit"
        MODEL_OUTPUT_LIMIT["$model"]="$output_limit"
    done < "$METADATA_CONF"
}

generate_display_name() {
    # Generate a display name for models not in metadata
    local model="$1"
    local base_name size_tag
    
    base_name="${model%%:*}"
    size_tag="${model##*:}"
    base_name="${base_name^}"  # Capitalize first letter
    size_tag="${size_tag^^}"   # Uppercase size tag
    
    echo "$base_name $size_tag"
}

generate_opencode_config() {
    # Generate OpenCode config JSON for the given models
    local models=("$@")
    local config=""
    local first=true
    
    # JSON header
    config='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {
        "baseURL": "http://localhost:11434/v1"
      },
      "models": {'
    
    # Add each model
    for model in "${models[@]}"; do
        [[ -z "$model" ]] && continue
        
        local display_name context_limit output_limit
        
        # Look up metadata or use defaults
        if [[ -n "${MODEL_DISPLAY_NAME[$model]:-}" ]]; then
            display_name="${MODEL_DISPLAY_NAME[$model]}"
            context_limit="${MODEL_CONTEXT_LIMIT[$model]}"
            output_limit="${MODEL_OUTPUT_LIMIT[$model]}"
        else
            display_name=$(generate_display_name "$model")
            context_limit=$DEFAULT_CONTEXT
            output_limit=$DEFAULT_OUTPUT
        fi
        
        # Add comma separator after first entry
        if [[ "$first" == "true" ]]; then
            first=false
        else
            config+=","
        fi
        
        config+="
        \"$model\": {
          \"name\": \"$display_name\",
          \"limit\": { \"context\": $context_limit, \"output\": $output_limit }
        }"
    done
    
    # JSON footer
    config+='
      }
    }
  }
}'
    
    echo "$config"
}

load_models_conf() {
    # Load models from models.conf file
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found at: $MODELS_CONF"
        exit 1
    fi
    
    local index=0
    while IFS='|' read -r category model size description || [[ -n "$category" ]]; do
        # Skip comments and empty lines
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim whitespace (use parameter expansion to avoid xargs issues with quotes)
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model="${model#"${model%%[![:space:]]*}"}"
        model="${model%"${model##*[![:space:]]}"}"
        size="${size#"${size%%[![:space:]]*}"}"
        size="${size%"${size##*[![:space:]]}"}"
        description="${description#"${description%%[![:space:]]*}"}"
        description="${description%"${description##*[![:space:]]}"}"
        
        # Store model info
        MODEL_ORDER+=("$model")
        MODEL_INFO["$model"]="$category|$size|$description"
        
        # Default selection: first model in each category is auto-selected
        # This works for any category name (autocomplete, general, reasoning, coding, or custom)
        if [[ -z "${CATEGORY_SEEN[$category]:-}" ]]; then
            # First model in this category - select it by default
            MODEL_SELECTED["$model"]=1
            CATEGORY_SEEN["$category"]=1
        else
            # Not the first model in this category - don't select by default
            MODEL_SELECTED["$model"]=0
        fi
        
        index=$((index + 1))
    done < "$MODELS_CONF"
}

calculate_total_size() {
    local total=0
    local num
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            IFS='|' read -r _ size _ <<< "${MODEL_INFO[$model]}"
            # Extract numeric value from size (e.g., "20GB" -> 20)
            num=$(echo "$size" | grep -oE '[0-9]+\.?[0-9]*')
            total=$(echo "$total + $num" | bc)
        fi
    done
    echo "$total"
}

count_selected() {
    local count=0
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            ((count++))
        fi
    done
    echo "$count"
}

interactive_model_selection() {
    # Build options array and list of preselected labels
    local options=()
    local preselected_labels=()
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category size description <<< "${MODEL_INFO[$model]}"
        
        # Format: "model_name (~size) - description"
        local label="$model (~$size) - $description"
        options+=("$label")
        
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            preselected_labels+=("$label")
        fi
    done
    
    echo ""
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo -e "${CYAN}${BOLD}  Select Models to Install${NC}"
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo ""
    echo -e "${DIM}Space to toggle, Enter to confirm, Ctrl+C to cancel${NC}"
    echo -e "${DIM}Edit models.conf to add more models to this list${NC}"
    echo ""
    
    # Build comma-separated string of preselected labels (descriptions must not contain commas!)
    local selected_csv=""
    if [ ${#preselected_labels[@]} -gt 0 ]; then
        selected_csv=$(IFS=,; echo "${preselected_labels[*]}")
    fi
    
    # Run gum choose with multi-select
    local selections
    if [ -n "$selected_csv" ]; then
        selections=$(gum choose --no-limit \
            --cursor-prefix="○ " \
            --selected-prefix="✓ " \
            --unselected-prefix="○ " \
            --cursor.foreground="212" \
            --selected.foreground="212" \
            --height=20 \
            --selected="$selected_csv" \
            "${options[@]}") || {
            # User cancelled with Ctrl+C
            echo ""
            print_status "Model selection cancelled"
            exit 0
        }
    else
        selections=$(gum choose --no-limit \
            --cursor-prefix="○ " \
            --selected-prefix="✓ " \
            --unselected-prefix="○ " \
            --cursor.foreground="212" \
            --selected.foreground="212" \
            --height=20 \
            "${options[@]}") || {
            # User cancelled with Ctrl+C
            echo ""
            print_status "Model selection cancelled"
            exit 0
        }
    fi
    
    # Reset all selections
    for model in "${MODEL_ORDER[@]}"; do
        MODEL_SELECTED["$model"]=0
    done
    
    # Parse selections and update MODEL_SELECTED
    while IFS= read -r line; do
        # Extract the model name (everything before the first space and parenthesis)
        local selected_model="${line%% (~*}"
        if [ -n "$selected_model" ]; then
            # Find matching model in MODEL_ORDER
            for model in "${MODEL_ORDER[@]}"; do
                if [[ "$model" == "$selected_model" ]]; then
                    MODEL_SELECTED["$model"]=1
                    break
                fi
            done
        fi
    done <<< "$selections"
    
    # Show summary
    local total_size
    local selected_count
    total_size=$(calculate_total_size)
    selected_count=$(count_selected)
    
    echo ""
    echo -e "${BOLD}Selected:${NC} $selected_count models (~${total_size}GB total)"
}

get_selected_models() {
    local selected=()
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            selected+=("$model")
        fi
    done
    echo "${selected[@]}"
}

# -----------------------------------------------------------------------------
# GPU Detection Functions
# -----------------------------------------------------------------------------

detect_amd_gpu() {
    local gpu_info
    gpu_info=$(lspci 2>/dev/null | grep -i 'vga.*amd\|display.*amd' | head -1) || true
    
    if [[ -z "$gpu_info" ]]; then
        echo "unknown|Unknown AMD GPU|11.0.0"
        return
    fi
    
    if [[ "$gpu_info" =~ "Navi 31" ]]; then
        echo "navi31|RX 7900 XTX/XT/GRE|11.0.0"
    elif [[ "$gpu_info" =~ "Navi 32" ]]; then
        echo "navi32|RX 7800/7700 XT|11.0.0"
    elif [[ "$gpu_info" =~ "Navi 33" ]]; then
        echo "navi33|RX 7600|11.0.0"
    elif [[ "$gpu_info" =~ "Navi 21" ]]; then
        echo "navi21|RX 6900/6800 XT|10.3.0"
    elif [[ "$gpu_info" =~ "Navi 22" ]]; then
        echo "navi22|RX 6700 XT|10.3.0"
    elif [[ "$gpu_info" =~ "Navi 23" ]]; then
        echo "navi23|RX 6600 XT/6600|10.3.0"
    elif [[ "$gpu_info" =~ "Navi 10" ]]; then
        echo "navi10|RX 5700 XT/5700|10.1.0"
    elif [[ "$gpu_info" =~ "Navi 14" ]]; then
        echo "navi14|RX 5500|10.1.0"
    elif [[ "$gpu_info" =~ "Vega 20" ]]; then
        echo "vega20|Radeon VII|9.0.6"
    elif [[ "$gpu_info" =~ "Vega 10" ]]; then
        echo "vega10|RX Vega 64/56|9.0.0"
    else
        echo "unknown|Unknown AMD GPU|11.0.0"
    fi
}

# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------

echo ""
echo -e "${CYAN}${BOLD}============================================${NC}"
echo -e "${CYAN}${BOLD}  Ollama ROCm Setup for AMD GPUs${NC}"
echo -e "${CYAN}${BOLD}  With Multi-Model Support & OpenCode${NC}"
echo -e "${CYAN}${BOLD}============================================${NC}"
echo ""

# -----------------------------------------------------------------------------
# Status Mode
# -----------------------------------------------------------------------------

if [ "$RUN_STATUS" = true ]; then
    print_header "Ollama Status"
    echo ""
    
    # Container status
    echo -e "  ${BOLD}Container:${NC}"
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
        CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' ollama 2>/dev/null || echo "unknown")
        CONTAINER_UPTIME=$(docker inspect --format='{{.State.StartedAt}}' ollama 2>/dev/null | cut -d'T' -f1 || echo "unknown")
        echo -e "    $CHECKMARK Status: ${GREEN}$CONTAINER_STATUS${NC}"
        echo -e "    $CHECKMARK Started: $CONTAINER_UPTIME"
    elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
        echo -e "    $CROSSMARK Status: ${RED}stopped${NC}"
        echo -e "    ${DIM}Start with: docker compose up -d${NC}"
    else
        echo -e "    $CROSSMARK Status: ${RED}not installed${NC}"
        echo -e "    ${DIM}Run ./setup.sh to install${NC}"
    fi
    
    # API status
    echo ""
    echo -e "  ${BOLD}API:${NC}"
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo -e "    $CHECKMARK Endpoint: ${GREEN}http://localhost:11434${NC}"
        OLLAMA_VERSION=$(docker exec ollama ollama --version 2>/dev/null || echo "unknown")
        echo -e "    $CHECKMARK Version: $OLLAMA_VERSION"
    else
        echo -e "    $CROSSMARK Endpoint: ${RED}not responding${NC}"
    fi
    
    # GPU status
    echo ""
    echo -e "  ${BOLD}GPU:${NC}"
    if docker exec ollama ls /dev/kfd &>/dev/null 2>&1; then
        IFS='|' read -r GPU_CHIP GPU_NAME HSA_VERSION <<< "$(detect_amd_gpu)"
        echo -e "    $CHECKMARK Detected: ${GREEN}$GPU_NAME${NC}"
        echo -e "    $CHECKMARK HSA Version: $HSA_VERSION"
        echo -e "    $CHECKMARK /dev/kfd: accessible"
    else
        echo -e "    $WARNMARK GPU access: ${YELLOW}unknown or not available${NC}"
    fi
    
    # Models
    echo ""
    echo -e "  ${BOLD}Models:${NC}"
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        MODEL_LIST=$(docker exec ollama ollama list 2>/dev/null | tail -n +2)
        if [ -n "$MODEL_LIST" ]; then
            MODEL_COUNT=$(echo "$MODEL_LIST" | wc -l)
            echo -e "    $CHECKMARK Installed: $MODEL_COUNT model(s)"
            echo "$MODEL_LIST" | while read -r line; do
                MODEL_NAME=$(echo "$line" | awk '{print $1}')
                MODEL_SIZE=$(echo "$line" | awk '{print $3}')
                echo -e "      - $MODEL_NAME (${MODEL_SIZE})"
            done
        else
            echo -e "    $WARNMARK No models installed"
        fi
        
        # Loaded models
        LOADED=$(docker exec ollama ollama ps 2>/dev/null | tail -n +2)
        if [ -n "$LOADED" ]; then
            echo ""
            echo -e "  ${BOLD}Currently Loaded (in VRAM):${NC}"
            echo "$LOADED" | while read -r line; do
                echo -e "    $CHECKMARK $line"
            done
        fi
    else
        echo -e "    ${DIM}(API not available)${NC}"
    fi
    
    # Storage
    echo ""
    echo -e "  ${BOLD}Storage:${NC}"
    OLLAMA_DIR="${OLLAMA_DATA_DIR:-$HOME/.ollama}"
    if [ -d "$OLLAMA_DIR" ]; then
        DIR_SIZE=$(du -sh "$OLLAMA_DIR" 2>/dev/null | cut -f1 || echo "unknown")
        echo -e "    $CHECKMARK Location: $OLLAMA_DIR"
        echo -e "    $CHECKMARK Size: $DIR_SIZE"
    else
        echo -e "    $CROSSMARK Directory not found: $OLLAMA_DIR"
    fi
    
    # Docker image
    echo ""
    echo -e "  ${BOLD}Docker Image:${NC}"
    IMAGE_INFO=$(docker images ollama/ollama:rocm --format "{{.Size}} (created {{.CreatedSince}})" 2>/dev/null)
    if [ -n "$IMAGE_INFO" ]; then
        echo -e "    $CHECKMARK ollama/ollama:rocm - $IMAGE_INFO"
    else
        echo -e "    $CROSSMARK Image not found"
    fi
    
    echo ""
    exit 0
fi

# -----------------------------------------------------------------------------
# Update Mode
# -----------------------------------------------------------------------------

if [ "$RUN_UPDATE" = true ]; then
    print_header "Updating Ollama"
    echo ""
    
    # Check if container exists
    if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
        print_error "Ollama container not found. Run ./setup.sh first."
        exit 1
    fi
    
    # Get current image ID
    CURRENT_IMAGE=$(docker inspect --format='{{.Image}}' ollama 2>/dev/null || echo "")
    
    print_status "Pulling latest Ollama ROCm image..."
    if ! docker compose pull 2>&1; then
        print_error "Failed to pull latest image"
        exit 1
    fi
    
    # Check if image changed
    NEW_IMAGE=$(docker inspect --format='{{.Id}}' ollama/ollama:rocm 2>/dev/null || echo "")
    
    if [ "$CURRENT_IMAGE" = "$NEW_IMAGE" ]; then
        print_success "Already running the latest version"
    else
        print_status "New version available, restarting container..."
        
        # Stop, remove, and recreate
        docker compose down
        docker compose up -d
        
        # Wait for startup
        print_status "Waiting for Ollama to start..."
        ATTEMPT=0
        while ! curl -sf http://localhost:11434/api/tags &>/dev/null; do
            ATTEMPT=$((ATTEMPT + 1))
            if [ $ATTEMPT -ge 30 ]; then
                print_error "Ollama failed to start after update"
                exit 1
            fi
            sleep 1
            echo -n "."
        done
        echo ""
        
        print_success "Ollama updated successfully"
        
        # Show new version
        OLLAMA_VERSION=$(docker exec ollama ollama --version 2>/dev/null || echo "unknown")
        print_status "Version: $OLLAMA_VERSION"
    fi
    
    # Optionally clean up old images
    OLD_IMAGES=$(docker images --filter "dangling=true" -q 2>/dev/null)
    if [ -n "$OLD_IMAGES" ]; then
        echo ""
        print_status "Cleaning up old images..."
        docker image prune -f &>/dev/null || true
        print_success "Cleanup complete"
    fi
    
    echo ""
    exit 0
fi

# -----------------------------------------------------------------------------
# Fix Permissions Mode
# -----------------------------------------------------------------------------

if [ "$FIX_PERMISSIONS" = true ]; then
    print_header "Fixing User Permissions"
    
    echo ""
    print_status "This will add your user to the required groups for GPU access."
    print_warning "You will need to enter your sudo password."
    print_warning "After this completes, you MUST log out and log back in!"
    echo ""
    
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Proceed? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Cancelled."
            exit 0
        fi
    fi
    
    # Add user to required groups
    CURRENT_USER=$(whoami)
    
    print_status "Adding $CURRENT_USER to video group..."
    if sudo usermod -aG video "$CURRENT_USER"; then
        print_success "Added to video group"
    else
        print_error "Failed to add to video group"
    fi
    
    print_status "Adding $CURRENT_USER to render group..."
    if sudo usermod -aG render "$CURRENT_USER"; then
        print_success "Added to render group"
    else
        print_error "Failed to add to render group"
    fi
    
    # Check if user is in docker group
    if ! groups | grep -q '\bdocker\b'; then
        print_status "Adding $CURRENT_USER to docker group..."
        if sudo usermod -aG docker "$CURRENT_USER"; then
            print_success "Added to docker group"
        else
            print_error "Failed to add to docker group"
        fi
    fi
    
    echo ""
    print_success "Permissions updated!"
    echo ""
    echo -e "${YELLOW}${BOLD}IMPORTANT: You must log out and log back in for changes to take effect!${NC}"
    echo ""
    echo "After logging back in, run this script again:"
    echo "  ./setup.sh"
    echo ""
    exit 0
fi

# -----------------------------------------------------------------------------
# Dependency Check
# -----------------------------------------------------------------------------

print_header "Checking Dependencies"

MISSING_REQUIRED=()
MISSING_RECOMMENDED=()
PERMISSION_WARNINGS=()

# Docker installed
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | cut -d' ' -f3 | tr -d ',')
    echo -e "  $CHECKMARK Docker               installed ($DOCKER_VERSION)"
    DOCKER_INSTALLED=true
else
    echo -e "  $CROSSMARK Docker               not installed"
    MISSING_REQUIRED+=("docker")
    DOCKER_INSTALLED=false
fi

# Docker daemon running
if [ "$DOCKER_INSTALLED" = true ]; then
    if docker info &> /dev/null; then
        echo -e "  $CHECKMARK Docker daemon        running"
    else
        echo -e "  $CROSSMARK Docker daemon        not running (or no permission)"
        MISSING_REQUIRED+=("docker-daemon")
    fi
else
    echo -e "  $CROSSMARK Docker daemon        (requires Docker)"
fi

# Docker Compose
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "unknown")
    echo -e "  $CHECKMARK Docker Compose       installed ($COMPOSE_VERSION)"
else
    echo -e "  $CROSSMARK Docker Compose       not installed"
    MISSING_REQUIRED+=("docker-compose")
fi

# AMD GPU device
if [ -e /dev/kfd ]; then
    echo -e "  $CHECKMARK AMD GPU (/dev/kfd)   detected"
else
    echo -e "  $CROSSMARK AMD GPU (/dev/kfd)   not found"
    MISSING_REQUIRED+=("amd-gpu")
fi

# User groups - these are warnings, not hard requirements
# The container might still work depending on system configuration
IN_VIDEO_GROUP=false
IN_RENDER_GROUP=false
if groups | grep -q '\bvideo\b'; then
    IN_VIDEO_GROUP=true
fi
if groups | grep -q '\brender\b'; then
    IN_RENDER_GROUP=true
fi

if [ "$IN_VIDEO_GROUP" = true ] && [ "$IN_RENDER_GROUP" = true ]; then
    echo -e "  $CHECKMARK User groups          video, render"
else
    MISSING_GROUPS=""
    [ "$IN_VIDEO_GROUP" = false ] && MISSING_GROUPS+="video "
    [ "$IN_RENDER_GROUP" = false ] && MISSING_GROUPS+="render"
    echo -e "  $WARNMARK User groups          missing: ${MISSING_GROUPS}(may cause GPU issues)"
    PERMISSION_WARNINGS+=("user-groups")
fi

# Check /dev/kfd permissions
if [ -e /dev/kfd ]; then
    if [ -r /dev/kfd ] && [ -w /dev/kfd ]; then
        echo -e "  $CHECKMARK /dev/kfd access      read/write OK"
    else
        echo -e "  $WARNMARK /dev/kfd access      no read/write permission"
        PERMISSION_WARNINGS+=("kfd-permissions")
    fi
fi

# Check /dev/dri permissions
if [ -d /dev/dri ]; then
    if [ -r /dev/dri/renderD128 ] 2>/dev/null; then
        echo -e "  $CHECKMARK /dev/dri access      OK"
    else
        echo -e "  $WARNMARK /dev/dri access      limited permissions"
        PERMISSION_WARNINGS+=("dri-permissions")
    fi
fi

# curl
if command -v curl &> /dev/null; then
    echo -e "  $CHECKMARK curl                 installed"
else
    echo -e "  $CROSSMARK curl                 not installed"
    MISSING_REQUIRED+=("curl")
fi

# getent
if command -v getent &> /dev/null; then
    echo -e "  $CHECKMARK getent               installed"
else
    echo -e "  $CROSSMARK getent               not installed"
    MISSING_REQUIRED+=("getent")
fi

# bc (for size calculations)
if command -v bc &> /dev/null; then
    echo -e "  $CHECKMARK bc                   installed"
else
    echo -e "  $CROSSMARK bc                   not installed"
    MISSING_REQUIRED+=("bc")
fi

# gum (for interactive menus) - only required if interactive mode
if [ "$NON_INTERACTIVE" = false ]; then
    if command -v gum &> /dev/null; then
        GUM_VERSION=$(gum --version 2>/dev/null | head -1 || echo "unknown")
        echo -e "  $CHECKMARK gum                  installed ($GUM_VERSION)"
    else
        echo -e "  $CROSSMARK gum                  not installed (required for interactive mode)"
        MISSING_REQUIRED+=("gum")
    fi
fi

echo ""

# Recommended dependencies
if command -v opencode &> /dev/null; then
    echo -e "  $CHECKMARK OpenCode             installed"
    OPENCODE_INSTALLED=true
else
    echo -e "  $WARNMARK OpenCode             not installed (optional)"
    MISSING_RECOMMENDED+=("opencode")
    OPENCODE_INSTALLED=false
fi

# -----------------------------------------------------------------------------
# Dependency Summary
# -----------------------------------------------------------------------------

if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
    print_header "Missing Required Dependencies"
    echo ""
    
    for dep in "${MISSING_REQUIRED[@]}"; do
        case $dep in
            docker)
                echo "  ${BOLD}Docker:${NC}"
                echo "    Arch Linux:  sudo pacman -S docker"
                echo "    Ubuntu:      sudo apt install docker.io"
                echo "    Fedora:      sudo dnf install docker"
                echo ""
                ;;
            docker-daemon)
                echo "  ${BOLD}Docker daemon not running:${NC}"
                echo "    Start:       sudo systemctl start docker"
                echo "    Enable:      sudo systemctl enable docker"
                echo "    Add user:    sudo usermod -aG docker \$USER"
                echo "    Then:        Log out and back in"
                echo ""
                ;;
            docker-compose)
                echo "  ${BOLD}Docker Compose:${NC}"
                echo "    Usually included with Docker. If not:"
                echo "    Arch Linux:  sudo pacman -S docker-compose"
                echo "    Ubuntu:      sudo apt install docker-compose-plugin"
                echo ""
                ;;
            amd-gpu)
                echo "  ${BOLD}AMD GPU not detected:${NC}"
                echo "    Ensure amdgpu driver is loaded"
                echo "    Check:       lsmod | grep amdgpu"
                echo "    Install:     Varies by distro (usually automatic)"
                echo ""
                ;;
            curl)
                echo "  ${BOLD}curl:${NC}"
                echo "    Arch Linux:  sudo pacman -S curl"
                echo "    Ubuntu:      sudo apt install curl"
                echo ""
                ;;
            getent)
                echo "  ${BOLD}getent:${NC}"
                echo "    Usually pre-installed. If not:"
                echo "    Arch Linux:  sudo pacman -S glibc"
                echo "    Ubuntu:      sudo apt install libc-bin"
                echo ""
                ;;
            bc)
                echo "  ${BOLD}bc (calculator):${NC}"
                echo "    Arch Linux:  sudo pacman -S bc"
                echo "    Ubuntu:      sudo apt install bc"
                echo ""
                ;;
            gum)
                echo "  ${BOLD}gum (interactive menus):${NC}"
                echo "    Arch Linux:  sudo pacman -S gum"
                echo "    Fedora:      sudo dnf install gum"
                echo "    macOS:       brew install gum"
                echo "    Ubuntu:      See https://github.com/charmbracelet/gum#installation"
                echo ""
                echo "    Or run with: ./setup.sh --non-interactive"
                echo ""
                ;;
        esac
    done
    
    print_status "Install missing dependencies and run this script again."
    echo ""
    exit 1
fi

# Handle permission warnings
if [ ${#PERMISSION_WARNINGS[@]} -gt 0 ]; then
    print_header "Permission Warnings"
    echo ""
    
    for warn in "${PERMISSION_WARNINGS[@]}"; do
        case $warn in
            user-groups)
                echo "  ${BOLD}User not in video/render groups:${NC}"
                echo "    This may prevent GPU access inside Docker."
                echo ""
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video,render \$USER"
                echo "                 Then log out and back in"
                echo ""
                ;;
            kfd-permissions)
                echo "  ${BOLD}No read/write access to /dev/kfd:${NC}"
                echo "    GPU compute device not accessible."
                echo ""
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG render \$USER"
                echo "                 Then log out and back in"
                echo ""
                ;;
            dri-permissions)
                echo "  ${BOLD}Limited access to /dev/dri:${NC}"
                echo "    GPU render devices may not be accessible."
                echo ""
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video \$USER"
                echo "                 Then log out and back in"
                echo ""
                ;;
        esac
    done
    
    if [ "$IGNORE_WARNINGS" = false ] && [ "$NON_INTERACTIVE" = false ]; then
        echo -e "  ${DIM}The setup may still work if Docker has its own GPU access.${NC}"
        echo ""
        read -p "Continue with setup? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo ""
            print_status "To fix permissions, run: ./setup.sh --fix-permissions"
            print_status "Or continue anyway with: ./setup.sh --ignore-warnings"
            echo ""
            exit 1
        fi
    else
        print_warning "Continuing despite permission warnings (--ignore-warnings or --non-interactive)"
    fi
fi

if [ ${#MISSING_RECOMMENDED[@]} -gt 0 ]; then
    print_warning "Optional dependencies not installed:"
    for dep in "${MISSING_RECOMMENDED[@]}"; do
        case $dep in
            opencode)
                echo "    OpenCode: https://opencode.ai"
                ;;
        esac
    done
    echo ""
fi

print_success "All required dependencies satisfied!"

# -----------------------------------------------------------------------------
# GPU Detection & Environment Setup
# -----------------------------------------------------------------------------

print_header "Detecting GPU Configuration"

IFS='|' read -r GPU_CHIP GPU_NAME HSA_VERSION <<< "$(detect_amd_gpu)"
echo -e "  GPU detected:     ${GREEN}$GPU_NAME${NC} ($GPU_CHIP)"
echo -e "  HSA version:      ${GREEN}$HSA_VERSION${NC}"

VIDEO_GID=$(getent group video | cut -d: -f3)
RENDER_GID=$(getent group render | cut -d: -f3)
echo -e "  Video group ID:   ${GREEN}$VIDEO_GID${NC}"
echo -e "  Render group ID:  ${GREEN}$RENDER_GID${NC}"

# Generate .env file
if [ ! -f "$ENV_FILE" ] || [ "$FORCE_ENV" = true ]; then
    print_header "Generating Environment Configuration"
    
    if [ -f "$ENV_FILE" ]; then
        BACKUP_FILE="$ENV_FILE.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$ENV_FILE" "$BACKUP_FILE"
        print_status "Backed up existing .env to: $BACKUP_FILE"
    fi
    
    cat > "$ENV_FILE" << EOF
# Ollama ROCm Configuration
# Generated by setup.sh on $(date)
# Detected GPU: $GPU_NAME ($GPU_CHIP)

# =============================================================================
# SYSTEM-SPECIFIC SETTINGS (auto-detected)
# =============================================================================

VIDEO_GROUP_ID=$VIDEO_GID
RENDER_GROUP_ID=$RENDER_GID
HSA_OVERRIDE_GFX_VERSION=$HSA_VERSION

# =============================================================================
# OLLAMA SETTINGS
# =============================================================================

OLLAMA_KEEP_ALIVE=10m
OLLAMA_NUM_PARALLEL=2
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_FLASH_ATTENTION=1

# =============================================================================
# PATHS
# =============================================================================

OLLAMA_DATA_DIR=$HOME/.ollama
EOF
    
    print_success "Created .env with detected configuration"
else
    print_status "Using existing .env file (use --force-env to regenerate)"
fi

# Source the .env file
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# -----------------------------------------------------------------------------
# Setup Ollama
# -----------------------------------------------------------------------------

print_header "Setting Up Ollama"

print_status "Creating model storage directory at $OLLAMA_DATA_DIR..."
if ! mkdir -p "$OLLAMA_DATA_DIR" 2>/dev/null; then
    print_error "Failed to create directory: $OLLAMA_DATA_DIR"
    print_status "Check permissions or try: sudo mkdir -p $OLLAMA_DATA_DIR && sudo chown \$USER:\$USER $OLLAMA_DATA_DIR"
    exit 1
fi
print_success "Directory ready"

print_status "Pulling Ollama ROCm Docker image..."
if ! docker compose pull 2>&1; then
    print_error "Failed to pull Docker image"
    echo ""
    echo "Possible causes:"
    echo "  - No internet connection"
    echo "  - Docker Hub rate limit exceeded"
    echo "  - Docker daemon not running"
    echo ""
    echo "Try:"
    echo "  - Check internet: ping docker.io"
    echo "  - Check Docker: docker info"
    echo "  - Retry later if rate limited"
    exit 1
fi

print_status "Starting Ollama container..."
if ! docker compose up -d 2>&1; then
    print_error "Failed to start container"
    echo ""
    echo "Checking for common issues..."
    
    # Check if port is in use
    if ss -tlnp 2>/dev/null | grep -q ':11434'; then
        echo "  - Port 11434 is already in use"
        echo "    Check with: ss -tlnp | grep 11434"
        echo "    Kill process or change port in docker-compose.yml"
    fi
    
    # Check if container already exists
    if docker ps -a --format '{{.Names}}' | grep -q '^ollama$'; then
        echo "  - Container 'ollama' already exists"
        echo "    Remove with: docker rm -f ollama"
    fi
    
    echo ""
    echo "View detailed logs: docker compose logs"
    exit 1
fi

print_status "Waiting for Ollama to start..."
MAX_ATTEMPTS=60
ATTEMPT=0
while ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        echo ""
        print_error "Ollama failed to start after ${MAX_ATTEMPTS} seconds"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check container status: docker ps -a | grep ollama"
        echo "  2. Check logs: docker compose logs"
        echo "  3. Check GPU access: docker exec ollama ls /dev/kfd"
        echo ""
        
        # Try to get more info
        CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' ollama 2>/dev/null || echo "unknown")
        echo "Container status: $CONTAINER_STATUS"
        
        if [ "$CONTAINER_STATUS" = "running" ]; then
            echo ""
            echo "Container is running but API not responding."
            echo "This may be a GPU permission issue."
            echo ""
            echo "Try: ./setup.sh --fix-permissions"
            echo "Then log out/in and run setup again."
        fi
        
        exit 1
    fi
    sleep 1
    echo -n "."
done
echo ""
print_success "Ollama is running"

# Verify GPU is being used
print_status "Verifying GPU access..."
GPU_INFO=$(docker exec ollama ollama --version 2>&1 || true)
print_status "Ollama version: $GPU_INFO"

# Quick GPU check - try to see if ROCm is working
if docker exec ollama ls /dev/kfd &>/dev/null; then
    print_success "GPU device accessible inside container"
else
    print_warning "GPU device may not be accessible inside container"
    print_status "Models may run on CPU instead of GPU"
fi

# -----------------------------------------------------------------------------
# Model Selection & Download
# -----------------------------------------------------------------------------

if [ "$SKIP_MODELS" = false ]; then
    print_header "Model Selection"
    
    # Load models from config
    load_models_conf
    load_metadata_conf
    
    if [ "$NON_INTERACTIVE" = false ]; then
        # Interactive model selection using gum
        interactive_model_selection
    else
        print_status "Using default model selection (--non-interactive)"
    fi
    
    # Get selected models
    read -ra SELECTED_MODELS <<< "$(get_selected_models)"
    
    if [ ${#SELECTED_MODELS[@]} -eq 0 ]; then
        print_warning "No models selected. You can pull models later with:"
        echo "    docker exec ollama ollama pull <model-name>"
    else
        print_header "Downloading Models"
        
        total_size=$(calculate_total_size)
        print_status "Selected ${#SELECTED_MODELS[@]} models (~${total_size}GB total)"
        echo ""
        
        for model in "${SELECTED_MODELS[@]}"; do
            echo "    - $model"
        done
        echo ""
        
        if [ "$NON_INTERACTIVE" = false ]; then
            print_warning "This may take a while depending on your connection."
            read -p "Proceed with download? (Y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                print_status "Skipping downloads. Pull models later with:"
                echo "    docker exec ollama ollama pull <model-name>"
                SELECTED_MODELS=()
            fi
        fi
        
        for model in "${SELECTED_MODELS[@]}"; do
            echo ""
            print_status "Pulling $model..."
            if docker exec ollama ollama pull "$model"; then
                print_success "$model downloaded"
            else
                print_warning "Failed to download $model - continuing..."
            fi
        done
    fi
else
    print_header "Skipping Model Selection (--skip-models)"
    print_status "Pull models manually with: docker exec ollama ollama pull <model-name>"
fi

# List installed models
echo ""
print_status "Installed models:"
docker exec ollama ollama list

# -----------------------------------------------------------------------------
# Configure OpenCode
# -----------------------------------------------------------------------------

print_header "Configuring OpenCode"

if [ -f "$OPENCODE_CONFIG" ]; then
    print_warning "OpenCode config already exists at: $OPENCODE_CONFIG"
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Overwrite? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Keeping existing OpenCode config"
            SKIP_OPENCODE_CONFIG=true
        else
            BACKUP_FILE="$OPENCODE_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
            cp "$OPENCODE_CONFIG" "$BACKUP_FILE"
            print_status "Backed up existing config to: $BACKUP_FILE"
            SKIP_OPENCODE_CONFIG=false
        fi
    else
        SKIP_OPENCODE_CONFIG=true
    fi
else
    SKIP_OPENCODE_CONFIG=false
fi

if [ "$SKIP_OPENCODE_CONFIG" = false ]; then
    print_status "Creating OpenCode configuration for Ollama..."
    mkdir -p "$(dirname "$OPENCODE_CONFIG")"
    
    # Load metadata if not already loaded
    if [[ ${#MODEL_DISPLAY_NAME[@]} -eq 0 ]]; then
        load_metadata_conf
    fi
    
    # Determine which models to include in config
    if [[ ${#SELECTED_MODELS[@]} -gt 0 ]]; then
        # Use selected models from model selection
        CONFIG_MODELS=("${SELECTED_MODELS[@]}")
    else
        # No models selected (--skip-models), query installed models
        readarray -t CONFIG_MODELS < <(docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
    fi
    
    if [[ ${#CONFIG_MODELS[@]} -gt 0 ]]; then
        generate_opencode_config "${CONFIG_MODELS[@]}" > "$OPENCODE_CONFIG"
        print_success "OpenCode config created at: $OPENCODE_CONFIG"
        print_status "Configured ${#CONFIG_MODELS[@]} model(s)"
    else
        print_warning "No models to configure. Run sync-opencode-config.sh after installing models."
    fi
fi
print_status "Use '/models' in OpenCode to switch between local models"
print_status "Run ./sync-opencode-config.sh to refresh config after pulling new models"

# -----------------------------------------------------------------------------
# Test GPU Acceleration
# -----------------------------------------------------------------------------

print_header "Testing GPU Acceleration"

INSTALLED_MODELS=$(docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | head -1)
if [ -n "$INSTALLED_MODELS" ]; then
    print_status "Running quick inference test with $INSTALLED_MODELS..."
    TEST_RESPONSE=$(docker exec ollama ollama run "$INSTALLED_MODELS" "Reply with exactly: GPU TEST OK" 2>&1 | head -3)
    echo "$TEST_RESPONSE"
    print_success "Inference test complete"
else
    print_warning "No models installed yet - skipping inference test"
    print_status "Run a test later with: docker exec ollama ollama run qwen2.5-coder:3b 'Hello'"
fi

# -----------------------------------------------------------------------------
# Setup Complete
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo ""
echo -e "${BOLD}Configuration:${NC}"
echo "  GPU detected:     $GPU_NAME"
echo "  HSA version:      $HSA_VERSION"
echo "  Model storage:    $OLLAMA_DATA_DIR"
echo "  API endpoint:     http://localhost:11434"
echo "  OpenCode config:  $OPENCODE_CONFIG"
echo ""
echo -e "${BOLD}Quick commands:${NC}"
echo "  Start:      docker compose -f $SCRIPT_DIR/docker-compose.yml up -d"
echo "  Stop:       docker compose -f $SCRIPT_DIR/docker-compose.yml down"
echo "  Logs:       docker compose -f $SCRIPT_DIR/docker-compose.yml logs -f"
echo "  Models:     docker exec ollama ollama list"
echo ""
echo -e "${BOLD}Adding more models:${NC}"
echo "  1. Edit models.conf to add models to the selection menu"
echo "  2. Or pull directly: docker exec ollama ollama pull <model:tag>"
echo ""
echo -e "${BOLD}Using OpenCode:${NC}"
echo "  1. Run 'opencode' in any project directory"
echo "  2. Use '/models' to select a local Ollama model"
echo ""
echo -e "${BOLD}Direct CLI chat:${NC}"
echo "  docker exec -it ollama ollama run qwen3:32b"
echo ""

if [ "$OPENCODE_INSTALLED" = false ]; then
    print_warning "Don't forget to install OpenCode: https://opencode.ai"
fi

echo -e "${GREEN}${BOLD}Happy coding!${NC}"
echo ""
