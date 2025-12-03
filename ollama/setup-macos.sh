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
        echo "Then run ./setup.sh inside your new premium Linux environment."
        echo ""
        echo "Alternatively, if you insist on staying in macOS territory:"
        echo "  Get a Mac, then use: ./setup-macos.sh"
    else
        echo "For other platforms, see: https://ollama.com/download"
    fi
    echo ""
    exit 1
fi

# Change to script directory (works regardless of where user runs it from)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source common library
source "$SCRIPT_DIR/../lib/common.sh"

# Set up signal handlers for graceful cancellation
setup_signal_handlers

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MODELS_CONF="$SCRIPT_DIR/models.conf"
METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
OPENCODE_CONFIG="$HOME/.config/opencode/opencode.json"

# Parse command line arguments
SKIP_MODELS=false
NON_INTERACTIVE=false
IGNORE_WARNINGS=false
RUN_STATUS=false
RUN_UPDATE=false
RESET_AGENTS=false
SELECTED_MODELS=()
for arg in "$@"; do
    case $arg in
        --skip-models) SKIP_MODELS=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --ignore-warnings) IGNORE_WARNINGS=true ;;
        --status) RUN_STATUS=true ;;
        --update) RUN_UPDATE=true ;;
        --reset-agents) RESET_AGENTS=true ;;
        --help|-h)
            echo "Usage: ./setup-macos.sh [OPTIONS]"
            echo ""
            echo "Commands:"
            echo "  --status            Show current Ollama status and configuration"
            echo "  --update            Update Ollama to latest version"
            echo ""
            echo "Setup Options:"
            echo "  --skip-models       Skip model selection and downloading"
            echo "  --non-interactive   Use default selections (no prompts)"
            echo "  --ignore-warnings   Continue setup despite warnings"
            echo "  --reset-agents      Re-copy AGENTS.md (OpenCode system prompt)"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "This script installs Ollama natively on macOS using Homebrew."
            echo "macOS uses Metal for GPU acceleration (Apple Silicon) or CPU."
            echo ""
            echo "Examples:"
            echo "  ./setup-macos.sh                  # Interactive setup"
            echo "  ./setup-macos.sh --status         # Check current status"
            echo "  ./setup-macos.sh --update         # Update Ollama"
            echo "  ./setup-macos.sh --skip-models    # Setup without downloading models"
            echo "  ./setup-macos.sh --non-interactive # Automated setup with defaults"
            echo ""
            echo "Model Performance Tuning:"
            echo "  If models seem confused or ignore instructions, increase context:"
            echo ""
            echo "    launchctl setenv OLLAMA_NUM_CTX 32768"
            echo "    brew services restart ollama"
            echo ""
            echo "  Recommended values: 16384 (basic), 32768 (general), 65536 (coding)"
            echo ""
            echo "For Linux with AMD GPUs, use ./setup.sh instead."
            exit 0
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Error Handling
# -----------------------------------------------------------------------------

trap 'handle_error $? $LINENO' ERR

handle_error() {
    local exit_code=$1
    local line_number=$2
    echo ""
    print_error "Something went wrong during setup."
    echo ""
    echo "Common solutions:"
    echo "  1. Make sure Ollama service is running:"
    echo "     brew services start ollama"
    echo ""
    echo "  2. Check Homebrew is working:"
    echo "     brew doctor"
    echo ""
    echo "  3. Try running setup again:"
    echo "     /opt/homebrew/bin/bash ./setup-macos.sh"
    echo ""
    echo -e "${DIM}(Technical: error on line $line_number, exit code $exit_code)${NC}"
    exit "$exit_code"
}

# -----------------------------------------------------------------------------
# Hardware Detection for Model Recommendations
# -----------------------------------------------------------------------------

DETECTED_MEMORY_GB=""
IGNORE_HARDWARE_RECOMMENDATIONS=false

get_usable_memory_gb() {
    # Detect usable memory for models on macOS
    # Apple Silicon uses unified memory - models can use ~70-75% of total RAM
    # Intel Macs run on CPU and have similar constraints
    
    if [[ -n "$DETECTED_MEMORY_GB" ]]; then
        echo "$DETECTED_MEMORY_GB"
        return
    fi
    
    local total_bytes total_gb usable_gb
    
    # Get total physical memory
    total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    
    if [[ "$total_bytes" -gt 0 ]]; then
        # Convert to GB
        total_gb=$((total_bytes / 1024 / 1024 / 1024))
        # Use 70% as usable for models (leaves room for OS and other apps)
        usable_gb=$((total_gb * 70 / 100))
        DETECTED_MEMORY_GB=$usable_gb
        echo "$usable_gb"
    else
        DETECTED_MEMORY_GB=0
        echo "0"
    fi
}

get_total_memory_gb() {
    # Get total memory (for display purposes)
    local total_bytes
    total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    echo $((total_bytes / 1024 / 1024 / 1024))
}

get_model_size_gb() {
    # Extract numeric GB value from model size string (e.g., "20GB" -> 20, "0.6GB" -> 0.6)
    local size_str="$1"
    echo "$size_str" | grep -oE '[0-9]+\.?[0-9]*' | head -1
}

get_model_hardware_status() {
    # Returns hardware status for a model: "recommended", "may_struggle", or "wont_fit"
    # Args: model_size_gb, usable_memory_gb
    local model_size="$1"
    local memory="$2"
    
    # If memory unknown or recommendations disabled, return empty
    if [[ "$memory" == "0" || -z "$memory" || "$IGNORE_HARDWARE_RECOMMENDATIONS" == "true" ]]; then
        echo ""
        return
    fi
    
    # Calculate thresholds
    # - Model <= 80% usable memory = recommended
    # - Model 80-100% usable memory = may struggle
    # - Model > 100% usable memory = won't fit
    
    local threshold_recommended threshold_struggle
    threshold_recommended=$((memory * 80 / 100))
    threshold_struggle=$memory
    
    # Compare (integer comparison - use floor of model size)
    local model_int
    model_int=$(echo "$model_size" | cut -d. -f1)
    [[ -z "$model_int" ]] && model_int=0
    
    if (( model_int <= threshold_recommended )); then
        echo "recommended"
    elif (( model_int <= threshold_struggle )); then
        echo "may_struggle"
    else
        echo "wont_fit"
    fi
}

format_hardware_tag() {
    # Format the hardware status tag for display
    # Args: status, memory_gb
    local status="$1"
    local memory="$2"
    
    case "$status" in
        recommended)
            echo -e "${GREEN}[✓ recommended - fits ${memory}GB memory]${NC}"
            ;;
        may_struggle)
            echo -e "${YELLOW}[⚠ may struggle - exceeds ${memory}GB memory]${NC}"
            ;;
        wont_fit)
            echo -e "${RED}[✗ won't fit - requires more memory]${NC}"
            ;;
        *)
            echo ""
            ;;
    esac
}

# -----------------------------------------------------------------------------
# Model Selection Functions
# -----------------------------------------------------------------------------

declare -A MODEL_SELECTED
declare -a MODEL_ORDER
declare -A MODEL_INFO
declare -A CATEGORY_SEEN
declare -A CATEGORY_RECOMMENDED_FOUND

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
        MODEL_ORDER=("qwen2.5-coder:3b" "qwen3:8b" "deepseek-r1:8b" "qwen2.5-coder:14b")
        MODEL_INFO["qwen2.5-coder:3b"]="autocomplete|2GB|Fast code completion for IDE"
        MODEL_INFO["qwen3:8b"]="general|5GB|Good all-rounder for limited resources"
        MODEL_INFO["deepseek-r1:8b"]="reasoning|5GB|Reasoning model, smaller size"
        MODEL_INFO["qwen2.5-coder:14b"]="coding|9GB|Coding focus, moderate size"
        MODEL_SELECTED["qwen2.5-coder:3b"]=1
        MODEL_SELECTED["qwen3:8b"]=1
        MODEL_SELECTED["deepseek-r1:8b"]=0
        MODEL_SELECTED["qwen2.5-coder:14b"]=0
        return
    fi
    
    # First pass: check for config options
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Look for IGNORE_HARDWARE_RECOMMENDATIONS setting
        if [[ "$line" =~ ^[[:space:]]*IGNORE_HARDWARE_RECOMMENDATIONS[[:space:]]*=[[:space:]]*(true|false) ]]; then
            IGNORE_HARDWARE_RECOMMENDATIONS="${BASH_REMATCH[1]}"
        fi
    done < "$MODELS_CONF"
    
    # Get usable memory for hardware recommendations
    local memory_gb
    memory_gb=$(get_usable_memory_gb)
    
    while IFS='|' read -r category model size description || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^[[:space:]]*IGNORE_HARDWARE_RECOMMENDATIONS ]] && continue
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
        
        # Default selection logic:
        # If IGNORE_HARDWARE_RECOMMENDATIONS=true: select first model in each category (with size limits for macOS)
        # Otherwise: select first RECOMMENDED model in each category
        
        if [[ "$IGNORE_HARDWARE_RECOMMENDATIONS" == "true" ]]; then
            # Original behavior: first model in category (with macOS size filter)
            if [[ -z "${CATEGORY_SEEN[$category]:-}" ]]; then
                if [[ "$category" == "small" ]]; then
                    # Always select first small model
                    MODEL_SELECTED["$model"]=1
                    CATEGORY_SEEN[$category]=1
                else
                    # Only auto-select smaller models for macOS
                    case "$model" in
                        *:0.5b|*:1b|*:3b|*:7b|*:8b|*:135m|*:360m|*:latest)
                            MODEL_SELECTED["$model"]=1
                            CATEGORY_SEEN[$category]=1
                            ;;
                        *)
                            MODEL_SELECTED["$model"]=0
                            ;;
                    esac
                fi
            else
                MODEL_SELECTED["$model"]=0
            fi
        else
            # New behavior: first RECOMMENDED model in each category
            local model_size_gb hw_status
            model_size_gb=$(get_model_size_gb "$size")
            hw_status=$(get_model_hardware_status "$model_size_gb" "$memory_gb")
            
            if [[ -z "${CATEGORY_RECOMMENDED_FOUND[$category]:-}" ]]; then
                # Haven't found a recommended model for this category yet
                if [[ "$hw_status" == "recommended" || -z "$hw_status" ]]; then
                    # This model is recommended (or recommendations disabled) - select it
                    MODEL_SELECTED["$model"]=1
                    CATEGORY_RECOMMENDED_FOUND["$category"]=1
                    CATEGORY_SEEN["$category"]=1
                else
                    # Not recommended - don't select
                    MODEL_SELECTED["$model"]=0
                    CATEGORY_SEEN["$category"]=1
                fi
            else
                # Already found a recommended model for this category
                MODEL_SELECTED["$model"]=0
            fi
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

# Get list of already installed models from Ollama
get_installed_models() {
    ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true
}

# Check if a model is already installed
is_model_installed() {
    local model="$1"
    local installed_models="$2"
    echo "$installed_models" | grep -qx "$model"
}

# -----------------------------------------------------------------------------
# Interactive Model Selection (using gum)
# -----------------------------------------------------------------------------

gum_model_selection() {
    # Build options array and list of preselected labels
    local options=()
    local preselected_labels=()
    local memory_gb
    memory_gb=$(get_usable_memory_gb)
    
    # Get list of already installed models
    local installed_models
    installed_models=$(get_installed_models)
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category size description <<< "${MODEL_INFO[$model]}"
        
        # Get hardware status tag
        local model_size_gb hw_status hw_tag=""
        model_size_gb=$(get_model_size_gb "$size")
        hw_status=$(get_model_hardware_status "$model_size_gb" "$memory_gb")
        
        case "$hw_status" in
            recommended)  hw_tag=" [✓ recommended]" ;;
            may_struggle) hw_tag=" [⚠ may struggle]" ;;
            wont_fit)     hw_tag=" [✗ won't fit]" ;;
        esac
        
        # Check if model is already installed and add star prefix
        local installed_prefix=""
        if is_model_installed "$model" "$installed_models"; then
            installed_prefix="★ "
        fi
        
        # Format: "★ model_name (~size) - description [status]" (star prefix if installed)
        local label="${installed_prefix}${model} (~${size}) - ${description}${hw_tag}"
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
    
    # Show memory info if detected
    local total_gb
    total_gb=$(get_total_memory_gb)
    if [[ "$memory_gb" -gt 0 && "$IGNORE_HARDWARE_RECOMMENDATIONS" != "true" ]]; then
        echo -e "  ${BOLD}System Memory:${NC} ${GREEN}${total_gb}GB${NC} (${memory_gb}GB usable for models)"
        echo ""
    fi
    
    echo -e "${DIM}Use Space or x to toggle, Enter to confirm, Ctrl+C to cancel${NC}"
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
        # Strip star prefix if present (installed models have ★ prefix)
        line="${line#★ }"
        # Extract the model name (everything before " (~")
        local selected_model="${line%% (~*}"
        if [[ -n "$selected_model" && -n "${MODEL_INFO[$selected_model]+x}" ]]; then
            MODEL_SELECTED["$selected_model"]=1
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

interactive_model_selection() {
    # gum is required for interactive mode (checked during dependency validation)
    gum_model_selection
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
# Status Mode
# -----------------------------------------------------------------------------

if [ "$RUN_STATUS" = true ]; then
    print_header "Ollama Status"
    echo ""
    
    # Service status
    echo -e "  ${BOLD}Service:${NC}"
    if brew services info ollama 2>/dev/null | grep -q "running"; then
        echo -e "    $CHECKMARK Status: ${GREEN}running${NC}"
    elif pgrep -x "ollama" &>/dev/null; then
        echo -e "    $CHECKMARK Status: ${GREEN}running${NC} (manual)"
    else
        echo -e "    $CROSSMARK Status: ${RED}stopped${NC}"
        echo -e "    ${DIM}Start with: brew services start ollama${NC}"
    fi
    
    # API status
    echo ""
    echo -e "  ${BOLD}API:${NC}"
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo -e "    $CHECKMARK Endpoint: ${GREEN}http://localhost:11434${NC}"
        OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
        echo -e "    $CHECKMARK Version: $OLLAMA_VERSION"
    else
        echo -e "    $CROSSMARK Endpoint: ${RED}not responding${NC}"
    fi
    
    # Hardware
    echo ""
    echo -e "  ${BOLD}Hardware:${NC}"
    if [[ "$APPLE_SILICON" = true ]]; then
        echo -e "    $CHECKMARK ${GREEN}Apple Silicon${NC} (Metal GPU)"
    else
        echo -e "    $WARNMARK ${YELLOW}Intel Mac${NC} (CPU only)"
    fi
    TOTAL_MEM=$(get_total_memory_gb)
    echo -e "    $CHECKMARK Memory: ${TOTAL_MEM}GB"
    
    # Models
    echo ""
    echo -e "  ${BOLD}Models:${NC}"
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        MODEL_LIST=$(ollama list 2>/dev/null | tail -n +2)
        if [ -n "$MODEL_LIST" ]; then
            MODEL_COUNT=$(echo "$MODEL_LIST" | wc -l | tr -d ' ')
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
        LOADED=$(ollama ps 2>/dev/null | tail -n +2)
        if [ -n "$LOADED" ]; then
            echo ""
            echo -e "  ${BOLD}Currently Loaded (in memory):${NC}"
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
    OLLAMA_DIR="$HOME/.ollama"
    if [ -d "$OLLAMA_DIR" ]; then
        DIR_SIZE=$(du -sh "$OLLAMA_DIR" 2>/dev/null | cut -f1 || echo "unknown")
        echo -e "    $CHECKMARK Location: $OLLAMA_DIR"
        echo -e "    $CHECKMARK Size: $DIR_SIZE"
    else
        echo -e "    $CROSSMARK Directory not found: $OLLAMA_DIR"
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
    
    print_status "Checking for updates via Homebrew..."
    
    # Get current version
    CURRENT_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    
    # Run upgrade
    if brew upgrade ollama 2>&1; then
        NEW_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
        if [ "$CURRENT_VERSION" = "$NEW_VERSION" ]; then
            print_success "Ollama is already up to date ($CURRENT_VERSION)"
        else
            print_success "Ollama updated: $CURRENT_VERSION → $NEW_VERSION"
        fi
    else
        # brew upgrade returns non-zero if already up to date
        if brew list ollama &>/dev/null; then
            print_success "Ollama is already up to date"
        else
            print_error "Failed to update Ollama"
            exit 1
        fi
    fi
    
    # Restart service if running
    if brew services info ollama 2>/dev/null | grep -q "running"; then
        print_status "Restarting Ollama service..."
        brew services restart ollama
        
        # Wait for startup
        start_spinner "Waiting for Ollama to start"
        ATTEMPT=0
        while ! curl -sf http://localhost:11434/api/tags &>/dev/null; do
            ATTEMPT=$((ATTEMPT + 1))
            if [ $ATTEMPT -ge 30 ]; then
                stop_spinner false "Ollama failed to start after update"
                exit 1
            fi
            sleep 1
        done
        stop_spinner true "Ollama restarted successfully"
    elif pgrep -x "ollama" &>/dev/null; then
        print_warning "Ollama is running manually. Restart it to use the new version:"
        echo "    pkill ollama && ollama serve &"
    fi
    
    # Show version
    OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    print_status "Version: $OLLAMA_VERSION"
    
    echo ""
    exit 0
fi

# -----------------------------------------------------------------------------
# Reset AGENTS.md Mode
# -----------------------------------------------------------------------------

if [ "$RESET_AGENTS" = true ]; then
    print_header "Resetting AGENTS.md"
    OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
    handle_agents_md "$SCRIPT_DIR/.." "$OPENCODE_CONFIG_DIR" "false" "true"
    echo ""
    exit 0
fi

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

# gum (for interactive menus) - required for interactive mode
if [ "$NON_INTERACTIVE" = false ]; then
    if command -v gum &>/dev/null; then
        GUM_VERSION=$(gum --version 2>/dev/null | head -1 || echo "unknown")
        echo -e "  $CHECKMARK gum                 installed ($GUM_VERSION)"
    else
        echo -e "  $CROSSMARK gum                 not installed (required for interactive mode)"
        MISSING_REQUIRED+=("gum")
    fi
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
    echo "    /opt/homebrew/bin/bash ./setup-macos.sh"
    echo ""
    exit 1
fi

# Handle missing curl (unlikely on macOS)
if [[ " ${MISSING_REQUIRED[*]} " =~ " curl " ]]; then
    print_error "curl is required but not installed"
    print_status "This is unusual for macOS. Try reinstalling Xcode CLI tools."
    exit 1
fi

# Handle missing gum (required for interactive mode)
if [[ " ${MISSING_REQUIRED[*]} " =~ " gum " ]]; then
    print_header "Missing Required Dependency: gum"
    echo ""
    print_status "gum is required for interactive model selection."
    echo ""
    echo -e "  ${BOLD}Install with Homebrew:${NC}"
    echo "    brew install gum"
    echo ""
    echo -e "  ${BOLD}Or run in non-interactive mode:${NC}"
    echo "    /opt/homebrew/bin/bash ./setup-macos.sh --non-interactive"
    echo ""
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
            echo -e "  ${DIM}Download time depends on your internet speed.${NC}"
            echo -e "  ${DIM}Rough estimate: 5-15 minutes per 10GB on typical broadband.${NC}"
            echo -e "  ${DIM}Downloads can be resumed if interrupted.${NC}"
            echo ""
            echo -e "  Press ${BOLD}Enter${NC} to start downloading, or ${BOLD}n${NC} to skip for now."
            read -p "  Download now? [Y/n] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                print_status "Skipping downloads. You can download models later with:"
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
    # Callback function for config generation
    _generate_config() { generate_opencode_config "${CONFIG_MODELS[@]}"; }
    handle_opencode_config "$OPENCODE_CONFIG" "$SCRIPT_DIR/sync-opencode-config.sh" "$NON_INTERACTIVE" _generate_config
else
    print_warning "No models to configure. Run sync-opencode-config.sh after installing models."
fi
print_status "Use '/models' in OpenCode to switch between local models"
print_status "Run ./sync-opencode-config.sh to refresh config after pulling new models"

# Handle AGENTS.md (OpenCode system prompt)
OPENCODE_CONFIG_DIR="$(dirname "$OPENCODE_CONFIG")"
handle_agents_md "$SCRIPT_DIR/.." "$OPENCODE_CONFIG_DIR" "$NON_INTERACTIVE" "false"

# -----------------------------------------------------------------------------
# Test Ollama
# -----------------------------------------------------------------------------

print_header "Testing Ollama"

# Ensure model info is loaded for category detection
if [[ ${#MODEL_INFO[@]} -eq 0 ]]; then
    load_models_conf
fi

# Find the best model for testing (prefer small category from installed models)
TEST_MODEL=""
INSTALLED_MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')

# First, try to find a small category model from installed models
for model in $INSTALLED_MODELS; do
    if [[ -n "${MODEL_INFO[$model]:-}" ]]; then
        IFS='|' read -r category _ _ <<< "${MODEL_INFO[$model]}"
        if [[ "$category" == "small" ]]; then
            TEST_MODEL="$model"
            break
        fi
    fi
done

# Fallback: use first installed model
if [ -z "$TEST_MODEL" ]; then
    TEST_MODEL=$(echo "$INSTALLED_MODELS" | head -1)
fi

if [ -n "$TEST_MODEL" ]; then
    # Check if this is a small model for timing expectations
    IS_SMALL_MODEL=false
    if [[ -n "${MODEL_INFO[$TEST_MODEL]:-}" ]]; then
        IFS='|' read -r category _ _ <<< "${MODEL_INFO[$TEST_MODEL]}"
        [[ "$category" == "small" ]] && IS_SMALL_MODEL=true
    fi
    
    if [ "$IS_SMALL_MODEL" = true ]; then
        print_status "Running quick inference test with $TEST_MODEL (small model)..."
    else
        print_status "Running inference test with $TEST_MODEL..."
        print_warning "This may take a minute since no small model is installed."
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
echo -e "${BOLD}Model Performance Tuning:${NC}"
echo "  If models seem confused, forget context, or ignore instructions,"
echo "  increase the context window size:"
echo ""
echo "    launchctl setenv OLLAMA_NUM_CTX 32768"
echo "    brew services restart ollama"
echo ""
echo "  Recommended OLLAMA_NUM_CTX values:"
echo "    16384  - Basic chat, limited memory"
echo "    32768  - General purpose (default)"
echo "    65536  - Agentic coding tasks, complex reasoning"
echo ""
echo "  To make permanent, add to ~/.zshrc or ~/.bash_profile:"
echo "    export OLLAMA_NUM_CTX=32768"
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
