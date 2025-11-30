#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Ollama Setup Script for macOS
# Native installation using Homebrew (no Docker needed)
# =============================================================================

# -----------------------------------------------------------------------------
# Bash Version Check - Requires Bash 4+ for associative arrays
# -----------------------------------------------------------------------------

if [[ "${BASH_VERSION%%.*}" -lt 4 ]]; then
    echo ""
    echo "ERROR: This script requires Bash 4.0 or later."
    echo "       Current version: $BASH_VERSION"
    echo ""
    echo "macOS ships with Bash 3.2 due to licensing restrictions."
    echo ""
    echo "To fix this, install Bash via Homebrew:"
    echo "  brew install bash"
    echo ""
    echo "Then run this script with the new Bash:"
    echo "  /opt/homebrew/bin/bash ./setup-macos.sh"
    echo ""
    exit 1
fi

# -----------------------------------------------------------------------------
# OS Check - This script is macOS only
# -----------------------------------------------------------------------------

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo ""
    echo "ERROR: This script is for macOS only."
    echo ""
    if [[ "$(uname -s)" == "Linux" ]]; then
        echo "For Linux with AMD GPUs, use the main setup script:"
        echo "  ./setup.sh"
    else
        echo "For other platforms, see: https://ollama.com/download"
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

# Spinner for operations without their own progress indicator
SPINNER_CHARS='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
SPINNER_PID=""

cleanup_spinner() {
    if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null
    fi
    SPINNER_PID=""
    printf "\r\033[K"  # Clear the line
}

trap cleanup_spinner EXIT

start_spinner() {
    local message="$1"
    local start_time=$SECONDS
    (
        local i=0
        local spin_len=${#SPINNER_CHARS}
        while true; do
            local elapsed=$((SECONDS - start_time))
            printf "\r  ${CYAN}%s${NC} %s ${DIM}(%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$elapsed"
            i=$(( (i + 1) % spin_len ))
            sleep 0.1
        done
    ) &
    SPINNER_PID=$!
}

stop_spinner() {
    local success=${1:-true}
    local message="${2:-}"
    
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null
        SPINNER_PID=""
    fi
    printf "\r\033[K"  # Clear the line
    
    if [[ -n "$message" ]]; then
        if [[ "$success" == "true" ]]; then
            print_success "$message"
        else
            print_error "$message"
        fi
    fi
}

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MODELS_CONF="$SCRIPT_DIR/models.conf"
METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
OPENCODE_CONFIG="$HOME/.config/opencode/opencode.json"

# Parse command line arguments
SKIP_MODELS=false
NON_INTERACTIVE=false
SELECTED_MODELS=()
for arg in "$@"; do
    case $arg in
        --skip-models) SKIP_MODELS=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --help|-h)
            echo "Usage: ./setup-macos.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-models       Skip model selection and downloading"
            echo "  --non-interactive   Use default selections (no prompts)"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "This script installs Ollama natively on macOS using Homebrew."
            echo "macOS uses Metal for GPU acceleration (Apple Silicon) or CPU."
            echo ""
            echo "For Linux with AMD GPUs, use ./setup.sh instead."
            exit 0
            ;;
    esac
done

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
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_warning "models.conf not found, using default models"
        # Default models if config doesn't exist
        MODEL_ORDER=("qwen2.5-coder:3b" "qwen3:8b" "deepseek-r1:8b" "qwen3-coder:14b")
        MODEL_INFO["qwen2.5-coder:3b"]="autocomplete|2GB|Fast code completion for IDE"
        MODEL_INFO["qwen3:8b"]="general|5GB|Good all-rounder for limited resources"
        MODEL_INFO["deepseek-r1:8b"]="reasoning|5GB|Reasoning model, smaller size"
        MODEL_INFO["qwen3-coder:14b"]="coding|9GB|Coding focus, moderate size"
        MODEL_SELECTED["qwen2.5-coder:3b"]=1
        MODEL_SELECTED["qwen3:8b"]=1
        MODEL_SELECTED["deepseek-r1:8b"]=0
        MODEL_SELECTED["qwen3-coder:14b"]=0
        return
    fi
    
    while IFS='|' read -r category model size description || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$category" ]] && continue
        
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model="${model#"${model%%[![:space:]]*}"}"
        model="${model%"${model##*[![:space:]]}"}"
        size="${size#"${size%%[![:space:]]*}"}"
        size="${size%"${size##*[![:space:]]}"}"
        description="${description#"${description%%[![:space:]]*}"}"
        description="${description%"${description##*[![:space:]]}"}"
        
        MODEL_ORDER+=("$model")
        MODEL_INFO["$model"]="$category|$size|$description"
        
        # Default: select smaller models suitable for macOS
        # For any category, auto-select the first small model (8B or less)
        # This works with any category name, not just predefined ones
        if [[ -z "${CATEGORY_SEEN[$category]:-}" ]]; then
            # First model in this category - check if it's small enough for macOS
            case "$model" in
                *:3b|*:7b|*:8b)
                    MODEL_SELECTED["$model"]=1
                    CATEGORY_SEEN[$category]=1
                    ;;
                *)
                    # Larger model - don't auto-select, but mark category as seen
                    # so we can still select the first small model if one comes later
                    MODEL_SELECTED["$model"]=0
                    ;;
            esac
        else
            MODEL_SELECTED["$model"]=0
        fi
    done < "$MODELS_CONF"
}

calculate_total_size() {
    local total=0
    local num
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            IFS='|' read -r _ size _ <<< "${MODEL_INFO[$model]}"
            num=$(echo "$size" | grep -oE '[0-9]+\.?[0-9]*')
            total=$(echo "$total + $num" | bc 2>/dev/null || echo "$total")
        fi
    done
    echo "$total"
}

count_selected() {
    local count=0
    for model in "${MODEL_ORDER[@]}"; do
        [[ "${MODEL_SELECTED[$model]}" == "1" ]] && ((count++))
    done
    echo "$count"
}

display_model_menu() {
    clear
    echo ""
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo -e "${CYAN}${BOLD}  Select Models to Install${NC}"
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo ""
    echo -e "${DIM}Use number keys to toggle selection, then press Enter to continue${NC}"
    echo -e "${DIM}Tip: Start with smaller models (8B or less) for best performance${NC}"
    echo ""
    
    local current_category=""
    local index=1
    local total_size
    local selected_count
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category size description <<< "${MODEL_INFO[$model]}"
        
        if [[ "$category" != "$current_category" ]]; then
            current_category="$category"
            echo ""
            case "$category" in
                autocomplete) echo -e "  ${BOLD}IDE Autocomplete:${NC}" ;;
                general)      echo -e "  ${BOLD}General Purpose:${NC}" ;;
                reasoning)    echo -e "  ${BOLD}Reasoning:${NC}" ;;
                coding)       echo -e "  ${BOLD}Coding Focus:${NC}" ;;
                specialized)  echo -e "  ${BOLD}Specialized:${NC}" ;;
                *)            echo -e "  ${BOLD}${category^}:${NC}" ;;
            esac
        fi
        
        local checkbox
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            checkbox="${GREEN}[x]${NC}"
        else
            checkbox="[ ]"
        fi
        
        printf "    %b ${YELLOW}%2d${NC}) %-28s ${DIM}(~%-5s)${NC} %s\n" \
            "$checkbox" "$index" "$model" "$size" "$description"
        
        index=$((index + 1))
    done
    
    total_size=$(calculate_total_size)
    selected_count=$(count_selected)
    local num_models=${#MODEL_ORDER[@]}
    
    echo ""
    echo -e "  ─────────────────────────────────────────────"
    echo -e "  ${BOLD}Selected:${NC} $selected_count models (~${total_size}GB total)"
    echo ""
    echo -e "  ${DIM}Commands:${NC}"
    echo -e "    ${YELLOW}1-${num_models}${NC}   Toggle model       ${YELLOW}a${NC}  Select all"
    echo -e "    ${YELLOW}c${NC}      Clear all          ${YELLOW}Enter${NC}  Continue"
    echo ""
    echo -ne "  Enter selection: "
}

interactive_model_selection() {
    local num_models=${#MODEL_ORDER[@]}
    
    while true; do
        display_model_menu
        
        read -r input
        
        # Trim whitespace
        input="${input#"${input%%[![:space:]]*}"}"
        input="${input%"${input##*[![:space:]]}"}"
        
        case "$input" in
            "")
                break
                ;;
            [0-9]|[0-9][0-9])
                local idx=$((input - 1))
                if [[ $idx -ge 0 && $idx -lt $num_models ]]; then
                    local model="${MODEL_ORDER[$idx]}"
                    if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
                        MODEL_SELECTED["$model"]=0
                    else
                        MODEL_SELECTED["$model"]=1
                    fi
                fi
                ;;
            a|A)
                for model in "${MODEL_ORDER[@]}"; do
                    MODEL_SELECTED["$model"]=1
                done
                ;;
            c|C)
                for model in "${MODEL_ORDER[@]}"; do
                    MODEL_SELECTED["$model"]=0
                done
                ;;
        esac
    done
    
    clear
}

get_selected_models() {
    local selected=()
    for model in "${MODEL_ORDER[@]}"; do
        [[ "${MODEL_SELECTED[$model]}" == "1" ]] && selected+=("$model")
    done
    echo "${selected[@]}"
}

has_small_model_selected() {
    # Check if any model from the 'small' category is selected
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            IFS='|' read -r category _ _ <<< "${MODEL_INFO[$model]}"
            if [[ "$category" == "small" ]]; then
                return 0
            fi
        fi
    done
    return 1
}

get_smallest_selected_model() {
    # Returns the smallest selected model (preferring 'small' category)
    local smallest_model=""
    local smallest_size=999999
    
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            IFS='|' read -r category size _ <<< "${MODEL_INFO[$model]}"
            # Extract numeric value from size (e.g., "0.6GB" -> 0.6)
            local num
            num=$(echo "$size" | grep -oE '[0-9]+\.?[0-9]*')
            
            # Prefer small category models, otherwise use size
            if [[ "$category" == "small" ]]; then
                echo "$model"
                return
            fi
            
            # Track smallest model as fallback
            if (( $(echo "$num < $smallest_size" | bc -l 2>/dev/null || echo "0") )); then
                smallest_size=$num
                smallest_model=$model
            fi
        fi
    done
    
    echo "$smallest_model"
}

# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------

echo ""
echo -e "${CYAN}${BOLD}============================================${NC}"
echo -e "${CYAN}${BOLD}  Ollama Setup for macOS${NC}"
echo -e "${CYAN}${BOLD}  Native Installation with Homebrew${NC}"
echo -e "${CYAN}${BOLD}============================================${NC}"
echo ""

# Detect Mac hardware
MAC_CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown")
if [[ "$MAC_CHIP" =~ "Apple" ]]; then
    echo -e "  Detected: ${GREEN}Apple Silicon${NC} (Metal GPU acceleration)"
    APPLE_SILICON=true
else
    echo -e "  Detected: ${YELLOW}Intel Mac${NC} (CPU only, no GPU acceleration)"
    APPLE_SILICON=false
fi
echo ""

# -----------------------------------------------------------------------------
# Dependency Check
# -----------------------------------------------------------------------------

print_header "Checking Dependencies"

MISSING_REQUIRED=()
HOMEBREW_INSTALLED=false
OLLAMA_INSTALLED=false

# Command Line Tools (for git, etc.)
if xcode-select -p &>/dev/null; then
    echo -e "  $CHECKMARK Xcode CLI Tools     installed"
else
    echo -e "  $CROSSMARK Xcode CLI Tools     not installed"
    MISSING_REQUIRED+=("xcode-cli")
fi

# Homebrew
if command -v brew &>/dev/null; then
    BREW_VERSION=$(brew --version | head -1 | cut -d' ' -f2)
    echo -e "  $CHECKMARK Homebrew            installed ($BREW_VERSION)"
    HOMEBREW_INSTALLED=true
else
    echo -e "  $WARNMARK Homebrew            not installed (will install)"
fi

# Ollama (check if already installed)
if command -v ollama &>/dev/null; then
    OLLAMA_VERSION=$(ollama --version 2>/dev/null | head -1 || echo "unknown")
    echo -e "  $CHECKMARK Ollama              installed ($OLLAMA_VERSION)"
    OLLAMA_INSTALLED=true
elif [ "$HOMEBREW_INSTALLED" = true ] && brew list ollama &>/dev/null; then
    echo -e "  $CHECKMARK Ollama              installed (via Homebrew)"
    OLLAMA_INSTALLED=true
else
    echo -e "  $WARNMARK Ollama              not installed (will install)"
fi

# curl
if command -v curl &>/dev/null; then
    echo -e "  $CHECKMARK curl                installed"
else
    echo -e "  $CROSSMARK curl                not installed"
    MISSING_REQUIRED+=("curl")
fi

# bc (for size calculations - usually present on macOS)
if command -v bc &>/dev/null; then
    echo -e "  $CHECKMARK bc                  installed"
else
    echo -e "  $WARNMARK bc                  not installed (size calculation may fail)"
fi

echo ""

# OpenCode (optional)
if command -v opencode &>/dev/null; then
    echo -e "  $CHECKMARK OpenCode            installed"
    OPENCODE_INSTALLED=true
else
    echo -e "  $WARNMARK OpenCode            not installed (optional)"
    OPENCODE_INSTALLED=false
fi

# Handle missing Xcode CLI tools
if [[ " ${MISSING_REQUIRED[*]} " =~ " xcode-cli " ]]; then
    print_header "Installing Xcode Command Line Tools"
    echo ""
    print_status "This will open a dialog to install Xcode CLI tools."
    print_status "Please follow the prompts, then run this script again."
    echo ""
    xcode-select --install 2>/dev/null || true
    echo ""
    print_warning "After installation completes, run this script again:"
    echo "    ./setup-macos.sh"
    echo ""
    exit 1
fi

# Handle missing curl (unlikely on macOS)
if [[ " ${MISSING_REQUIRED[*]} " =~ " curl " ]]; then
    print_error "curl is required but not installed"
    print_status "This is unusual for macOS. Try reinstalling Xcode CLI tools."
    exit 1
fi

# -----------------------------------------------------------------------------
# Install Homebrew if needed
# -----------------------------------------------------------------------------

if [ "$HOMEBREW_INSTALLED" = false ]; then
    print_header "Installing Homebrew"
    
    echo ""
    print_status "Homebrew is the package manager for macOS."
    print_status "This will install Homebrew from https://brew.sh"
    echo ""
    
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "Install Homebrew? (Y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            print_error "Homebrew is required. Install manually from https://brew.sh"
            exit 1
        fi
    fi
    
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add Homebrew to PATH for this session (Apple Silicon location)
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f "/usr/local/bin/brew" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    
    if command -v brew &>/dev/null; then
        print_success "Homebrew installed successfully"
        HOMEBREW_INSTALLED=true
    else
        print_error "Homebrew installation failed"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Install Ollama
# -----------------------------------------------------------------------------

if [ "$OLLAMA_INSTALLED" = false ]; then
    print_header "Installing Ollama"
    
    print_status "Installing Ollama via Homebrew..."
    
    if brew install ollama; then
        print_success "Ollama installed successfully"
        OLLAMA_INSTALLED=true
    else
        print_error "Failed to install Ollama"
        echo ""
        echo "Try installing manually:"
        echo "  brew install ollama"
        echo ""
        echo "Or download from: https://ollama.com/download"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Start Ollama Service
# -----------------------------------------------------------------------------

print_header "Starting Ollama Service"

# Check if Ollama is already running
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    print_success "Ollama is already running"
else
    print_status "Starting Ollama service..."
    
    # Start Ollama as a background service
    if brew services start ollama 2>/dev/null; then
        print_status "Started via Homebrew services"
    else
        # Fallback: start manually in background
        print_status "Starting Ollama in background..."
        ollama serve &>/dev/null &
        disown
    fi
    
    # Wait for Ollama to start
    start_spinner "Waiting for Ollama to start"
    MAX_ATTEMPTS=30
    ATTEMPT=0
    while ! curl -sf http://localhost:11434/api/tags &>/dev/null; do
        ATTEMPT=$((ATTEMPT + 1))
        if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
            stop_spinner false "Ollama failed to start after ${MAX_ATTEMPTS} seconds"
            echo ""
            echo "Try starting manually:"
            echo "  ollama serve"
            echo ""
            exit 1
        fi
        sleep 1
    done
    stop_spinner true "Ollama is running"
fi

# -----------------------------------------------------------------------------
# Model Selection & Download
# -----------------------------------------------------------------------------

if [ "$SKIP_MODELS" = false ]; then
    print_header "Model Selection"
    
    load_models_conf
    load_metadata_conf
    
    if [ "$NON_INTERACTIVE" = false ]; then
        print_status "Loading model selection menu..."
        sleep 1
        interactive_model_selection
        
        # Warn if no small model selected for inference testing
        if ! has_small_model_selected; then
            TEST_MODEL=$(get_smallest_selected_model)
            if [ -n "$TEST_MODEL" ]; then
                echo ""
                print_warning "No small model selected for inference testing."
                print_status "The inference test will use '$TEST_MODEL' which may take longer."
                echo ""
                echo -e "  ${DIM}Tip: Add a model from the 'Small/Fast' category (e.g., tinyllama)${NC}"
                echo -e "  ${DIM}for quick setup verification.${NC}"
                echo ""
                read -p "Continue without a small model? (Y/n) " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Nn]$ ]]; then
                    print_status "Returning to model selection..."
                    interactive_model_selection
                fi
            fi
        fi
    else
        print_status "Using default model selection (--non-interactive)"
    fi
    
    read -ra SELECTED_MODELS <<< "$(get_selected_models)"
    
    if [ ${#SELECTED_MODELS[@]} -eq 0 ]; then
        print_warning "No models selected. You can pull models later with:"
        echo "    ollama pull <model-name>"
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
                echo "    ollama pull <model-name>"
                SELECTED_MODELS=()
            fi
        fi
        
        for model in "${SELECTED_MODELS[@]}"; do
            echo ""
            print_status "Pulling $model..."
            if ollama pull "$model"; then
                print_success "$model downloaded"
            else
                print_warning "Failed to download $model - continuing..."
            fi
        done
    fi
else
    print_header "Skipping Model Selection (--skip-models)"
    print_status "Pull models manually with: ollama pull <model-name>"
fi

# List installed models
echo ""
print_status "Installed models:"
ollama list 2>/dev/null || echo "  (none yet)"

# -----------------------------------------------------------------------------
# Configure OpenCode
# -----------------------------------------------------------------------------

print_header "Configuring OpenCode"

SKIP_OPENCODE_CONFIG=false

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
        fi
    else
        SKIP_OPENCODE_CONFIG=true
    fi
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
        readarray -t CONFIG_MODELS < <(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
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
# Test Ollama
# -----------------------------------------------------------------------------

print_header "Testing Ollama"

# Find the best model for testing (prefer small category)
TEST_MODEL=""
if [[ ${#MODEL_ORDER[@]} -gt 0 ]] && has_small_model_selected; then
    TEST_MODEL=$(get_smallest_selected_model)
fi

# Fallback: use first installed model
if [ -z "$TEST_MODEL" ]; then
    TEST_MODEL=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | head -1)
fi

if [ -n "$TEST_MODEL" ]; then
    # Check if this is a small model for timing expectations
    IS_SMALL_MODEL=false
    if [[ ${#MODEL_INFO[@]} -gt 0 ]]; then
        IFS='|' read -r category _ _ <<< "${MODEL_INFO[$TEST_MODEL]:-}"
        [[ "$category" == "small" ]] && IS_SMALL_MODEL=true
    fi
    
    if [ "$IS_SMALL_MODEL" = true ]; then
        print_status "Running quick inference test with $TEST_MODEL (small model)..."
    else
        print_status "Running inference test with $TEST_MODEL..."
        print_warning "This may take a minute since no small model was selected."
    fi
    
    # Run the inference test with spinner (first run loads model into memory)
    TEST_OUTPUT_FILE=$(mktemp)
    start_spinner "Loading model and running inference"
    START_TIME=$(date +%s)
    ollama run "$TEST_MODEL" "Reply with exactly: TEST OK" > "$TEST_OUTPUT_FILE" 2>&1 || true
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    stop_spinner true
    
    # Show the response
    TEST_RESPONSE=$(head -5 "$TEST_OUTPUT_FILE")
    rm -f "$TEST_OUTPUT_FILE"
    
    echo "$TEST_RESPONSE"
    echo ""
    print_success "Inference test complete (${DURATION}s)"
    
    # Provide feedback on acceleration
    if [ "$APPLE_SILICON" = true ]; then
        print_success "Metal GPU acceleration is available"
    else
        print_status "Running on CPU (Intel Mac)"
    fi
else
    print_warning "No models installed yet - skipping inference test"
    print_status "Run a test later with: ollama run tinyllama 'Hello'"
fi

# -----------------------------------------------------------------------------
# Setup Complete
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo ""
echo -e "${BOLD}Configuration:${NC}"
if [ "$APPLE_SILICON" = true ]; then
    echo "  Hardware:         Apple Silicon (Metal GPU)"
else
    echo "  Hardware:         Intel Mac (CPU)"
fi
echo "  Model storage:    ~/.ollama"
echo "  API endpoint:     http://localhost:11434"
echo "  OpenCode config:  $OPENCODE_CONFIG"
echo ""
echo -e "${BOLD}Quick commands:${NC}"
echo "  Start:      brew services start ollama"
echo "  Stop:       brew services stop ollama"
echo "  Status:     brew services info ollama"
echo "  Models:     ollama list"
echo ""
echo -e "${BOLD}Adding more models:${NC}"
echo "  ollama pull <model:tag>"
echo "  Browse: https://ollama.com/library"
echo ""
echo -e "${BOLD}Using OpenCode:${NC}"
echo "  1. Run 'opencode' in any project directory"
echo "  2. Use '/models' to select a local Ollama model"
echo ""
echo -e "${BOLD}Direct CLI chat:${NC}"
echo "  ollama run qwen3:8b"
echo ""

if [ "$OPENCODE_INSTALLED" = false ]; then
    print_warning "Don't forget to install OpenCode: https://opencode.ai"
fi

if [ "$APPLE_SILICON" = false ]; then
    echo ""
    print_warning "Intel Macs run models on CPU only (no GPU acceleration)."
    print_status "Consider using smaller models (7B or less) for better performance."
fi

echo -e "${GREEN}${BOLD}Happy coding!${NC}"
echo ""
