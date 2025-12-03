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

# Source common library
source "$SCRIPT_DIR/../lib/common.sh"

trap cleanup_spinner EXIT

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
    print_error "Something went wrong during setup."
    echo ""
    echo "Common solutions:"
    echo "  1. Make sure Docker is running:"
    echo "     sudo systemctl start docker"
    echo ""
    echo "  2. Check you have permission to use Docker:"
    echo "     groups   # Should show 'docker' in the list"
    echo ""
    echo "  3. If you just added yourself to groups, log out and back in first"
    echo ""
    echo "  4. Try running setup again - some issues resolve on retry:"
    echo "     ./setup.sh"
    echo ""
    echo "  5. View detailed logs:"
    echo "     docker compose logs"
    echo ""
    echo -e "${DIM}(Technical: error on line $line_number, exit code $exit_code)${NC}"
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
# Hardware Detection for Model Recommendations
# -----------------------------------------------------------------------------

DETECTED_VRAM_GB=""
IGNORE_HARDWARE_RECOMMENDATIONS=false

get_vram_gb() {
    # Detect GPU VRAM in GB using rocm-smi
    # Returns the VRAM of the first GPU found (or smallest if multiple)
    
    if [[ -n "$DETECTED_VRAM_GB" ]]; then
        echo "$DETECTED_VRAM_GB"
        return
    fi
    
    local vram_mb=""
    
    # Try rocm-smi first (most reliable for AMD GPUs)
    if command -v rocm-smi &>/dev/null; then
        # rocm-smi --showmeminfo vram gives total VRAM
        vram_mb=$(rocm-smi --showmeminfo vram 2>/dev/null | grep -i "total" | head -1 | grep -oE '[0-9]+' | head -1)
    fi
    
    # Fallback: try to parse from rocminfo
    if [[ -z "$vram_mb" ]] && command -v rocminfo &>/dev/null; then
        # Look for "Size:" line after "Pool 1" (VRAM pool)
        vram_mb=$(rocminfo 2>/dev/null | grep -A 20 "Pool 1" | grep "Size:" | head -1 | grep -oE '[0-9]+')
    fi
    
    # Convert MB to GB
    if [[ -n "$vram_mb" && "$vram_mb" =~ ^[0-9]+$ ]]; then
        DETECTED_VRAM_GB=$((vram_mb / 1024))
        echo "$DETECTED_VRAM_GB"
    else
        # Unknown VRAM - return 0 to disable recommendations
        DETECTED_VRAM_GB=0
        echo "0"
    fi
}

get_model_size_gb() {
    # Extract numeric GB value from model size string (e.g., "20GB" -> 20, "0.6GB" -> 0.6)
    local size_str="$1"
    echo "$size_str" | grep -oE '[0-9]+\.?[0-9]*' | head -1
}

get_model_hardware_status() {
    # Returns hardware status for a model: "recommended", "may_struggle", or "wont_fit"
    # Args: model_size_gb, vram_gb
    local model_size="$1"
    local vram="$2"
    
    # If VRAM unknown or recommendations disabled, return empty
    if [[ "$vram" == "0" || -z "$vram" || "$IGNORE_HARDWARE_RECOMMENDATIONS" == "true" ]]; then
        echo ""
        return
    fi
    
    # Calculate thresholds
    # - Model <= 80% VRAM = recommended (leaves headroom for context/overhead)
    # - Model 80-100% VRAM = may struggle (might work but slow/limited context)
    # - Model > 100% VRAM = won't fit
    
    local threshold_recommended threshold_struggle
    threshold_recommended=$(echo "$vram * 0.80" | bc -l 2>/dev/null | cut -d. -f1)
    threshold_struggle=$vram
    
    # Handle bc failures
    if [[ -z "$threshold_recommended" ]]; then
        threshold_recommended=$((vram * 80 / 100))
    fi
    
    # Compare
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
    # Args: status, vram_gb
    local status="$1"
    local vram="$2"
    
    case "$status" in
        recommended)
            echo -e "${GREEN}[✓ recommended - fits ${vram}GB VRAM]${NC}"
            ;;
        may_struggle)
            echo -e "${YELLOW}[⚠ may struggle - exceeds ${vram}GB VRAM]${NC}"
            ;;
        wont_fit)
            echo -e "${RED}[✗ won't fit - requires more VRAM]${NC}"
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
    # Load models from models.conf file
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found at: $MODELS_CONF"
        exit 1
    fi
    
    # First pass: check for config options
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Look for IGNORE_HARDWARE_RECOMMENDATIONS setting
        if [[ "$line" =~ ^[[:space:]]*IGNORE_HARDWARE_RECOMMENDATIONS[[:space:]]*=[[:space:]]*(true|false) ]]; then
            IGNORE_HARDWARE_RECOMMENDATIONS="${BASH_REMATCH[1]}"
        fi
    done < "$MODELS_CONF"
    
    # Get VRAM for hardware recommendations
    local vram_gb
    vram_gb=$(get_vram_gb)
    
    local index=0
    while IFS='|' read -r category model size description || [[ -n "$category" ]]; do
        # Skip comments, empty lines, and config directives
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^[[:space:]]*IGNORE_HARDWARE_RECOMMENDATIONS ]] && continue
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
        
        # Default selection logic:
        # If IGNORE_HARDWARE_RECOMMENDATIONS=true: select first model in each category
        # Otherwise: select first RECOMMENDED model in each category
        
        if [[ "$IGNORE_HARDWARE_RECOMMENDATIONS" == "true" ]]; then
            # Original behavior: first model in each category
            if [[ -z "${CATEGORY_SEEN[$category]:-}" ]]; then
                MODEL_SELECTED["$model"]=1
                CATEGORY_SEEN["$category"]=1
            else
                MODEL_SELECTED["$model"]=0
            fi
        else
            # New behavior: first RECOMMENDED model in each category
            local model_size_gb hw_status
            model_size_gb=$(get_model_size_gb "$size")
            hw_status=$(get_model_hardware_status "$model_size_gb" "$vram_gb")
            
            if [[ -z "${CATEGORY_RECOMMENDED_FOUND[$category]:-}" ]]; then
                # Haven't found a recommended model for this category yet
                if [[ "$hw_status" == "recommended" || -z "$hw_status" ]]; then
                    # This model is recommended (or recommendations disabled) - select it
                    MODEL_SELECTED["$model"]=1
                    CATEGORY_RECOMMENDED_FOUND["$category"]=1
                    CATEGORY_SEEN["$category"]=1
                else
                    # Not recommended - don't select, but track that we've seen the category
                    MODEL_SELECTED["$model"]=0
                    CATEGORY_SEEN["$category"]=1
                fi
            else
                # Already found a recommended model for this category
                MODEL_SELECTED["$model"]=0
            fi
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

# Get list of already installed models from Ollama
get_installed_models() {
    docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true
}

# Check if a model is already installed
is_model_installed() {
    local model="$1"
    local installed_models="$2"
    echo "$installed_models" | grep -qx "$model"
}

gum_model_selection() {
    # Build options array and list of preselected labels
    local options=()
    local preselected_labels=()
    local vram_gb
    vram_gb=$(get_vram_gb)
    
    # Get list of already installed models
    local installed_models
    installed_models=$(get_installed_models)
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category size description <<< "${MODEL_INFO[$model]}"
        
        # Get hardware status tag
        local model_size_gb hw_status hw_tag=""
        model_size_gb=$(get_model_size_gb "$size")
        hw_status=$(get_model_hardware_status "$model_size_gb" "$vram_gb")
        
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
        local label="${installed_prefix}$model (~$size) - $description$hw_tag"
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
    # Show VRAM info if detected
    if [[ "$vram_gb" -gt 0 && "$IGNORE_HARDWARE_RECOMMENDATIONS" != "true" ]]; then
        echo -e "  ${BOLD}Detected VRAM:${NC} ${GREEN}${vram_gb}GB${NC}"
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
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            selected+=("$model")
        fi
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
            if (( $(echo "$num < $smallest_size" | bc -l) )); then
                smallest_size=$num
                smallest_model=$model
            fi
        fi
    done
    
    echo "$smallest_model"
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
        docker compose down || true
        docker compose up -d || true
        
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
        stop_spinner true "Ollama updated successfully"
        
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
    print_status "Adding user to video, render, and docker groups for GPU access."
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

# Recommended dependencies
if command -v opencode &> /dev/null; then
    echo -e "  $CHECKMARK OpenCode             installed"
    OPENCODE_INSTALLED=true
else
    echo -e "  $WARNMARK OpenCode             not installed (optional)"
    MISSING_RECOMMENDED+=("opencode")
    OPENCODE_INSTALLED=false
fi

echo ""

# -----------------------------------------------------------------------------
# Dependency Summary
# -----------------------------------------------------------------------------

if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
    print_header "Missing Required Dependencies"
    echo ""
    
    # Track if we can offer to fix some issues automatically
    CAN_AUTO_FIX=false
    
    for dep in "${MISSING_REQUIRED[@]}"; do
        case $dep in
            docker)
                echo -e "  ${BOLD}Docker:${NC}"
                echo "    Arch Linux:  sudo pacman -S docker"
                echo "    Ubuntu:      sudo apt install docker.io"
                echo "    Fedora:      sudo dnf install docker"
                echo ""
                ;;
            docker-daemon)
                echo -e "  ${BOLD}Docker daemon not running:${NC}"
                echo "    Start:       sudo systemctl start docker"
                echo "    Enable:      sudo systemctl enable docker"
                echo ""
                # Check if we can offer to start it
                if command -v systemctl &>/dev/null; then
                    CAN_AUTO_FIX=true
                fi
                ;;
            docker-compose)
                echo -e "  ${BOLD}Docker Compose:${NC}"
                echo "    Usually included with Docker. If not:"
                echo "    Arch Linux:  sudo pacman -S docker-compose"
                echo "    Ubuntu:      sudo apt install docker-compose-plugin"
                echo ""
                ;;
            amd-gpu)
                echo -e "  ${BOLD}AMD GPU not detected:${NC}"
                echo "    Ensure amdgpu driver is loaded"
                echo "    Check:       lsmod | grep amdgpu"
                echo "    Install:     Varies by distro (usually automatic)"
                echo ""
                ;;
            curl)
                echo -e "  ${BOLD}curl:${NC}"
                echo "    Arch Linux:  sudo pacman -S curl"
                echo "    Ubuntu:      sudo apt install curl"
                echo ""
                ;;
            getent)
                echo -e "  ${BOLD}getent:${NC}"
                echo "    Usually pre-installed. If not:"
                echo "    Arch Linux:  sudo pacman -S glibc"
                echo "    Ubuntu:      sudo apt install libc-bin"
                echo ""
                ;;
            bc)
                echo -e "  ${BOLD}bc (calculator):${NC}"
                echo "    Arch Linux:  sudo pacman -S bc"
                echo "    Ubuntu:      sudo apt install bc"
                echo ""
                ;;
            gum)
                echo -e "  ${BOLD}gum (interactive menus):${NC}"
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
    
    # Offer to auto-start docker daemon if that's the only issue
    if [[ "$CAN_AUTO_FIX" == "true" && " ${MISSING_REQUIRED[*]} " == *" docker-daemon "* && ${#MISSING_REQUIRED[@]} -eq 1 ]]; then
        echo ""
        if [ "$NON_INTERACTIVE" = false ]; then
            read -p "Would you like to start the Docker daemon now? (requires sudo) (Y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                print_status "Starting Docker daemon..."
                if sudo systemctl start docker; then
                    print_success "Docker daemon started"
                    echo ""
                    print_status "Continuing setup..."
                    echo ""
                    # Clear the missing required array and continue
                    MISSING_REQUIRED=()
                else
                    print_error "Failed to start Docker daemon"
                    echo ""
                    print_status "Try manually: sudo systemctl start docker"
                    echo "Then run this script again: ./setup.sh"
                    echo ""
                    exit 1
                fi
            fi
        fi
    fi
    
    # Exit if there are still missing dependencies
    if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}${BOLD}After installing dependencies, run this script again:${NC}"
        echo "  ./setup.sh"
        echo ""
        exit 1
    fi
fi

# Handle permission warnings
if [ ${#PERMISSION_WARNINGS[@]} -gt 0 ]; then
    print_header "Permission Warnings"
    echo ""
    
    for warn in "${PERMISSION_WARNINGS[@]}"; do
        case $warn in
            user-groups)
                echo -e "  ${BOLD}User not in video/render groups:${NC}"
                echo "    This may prevent GPU access inside Docker."
                echo ""
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video,render \$USER"
                echo "                 Then log out and back in"
                echo ""
                ;;
            kfd-permissions)
                echo -e "  ${BOLD}No read/write access to /dev/kfd:${NC}"
                echo "    GPU compute device not accessible."
                echo ""
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG render \$USER"
                echo "                 Then log out and back in"
                echo ""
                ;;
            dri-permissions)
                echo -e "  ${BOLD}Limited access to /dev/dri:${NC}"
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
    
    # Get current user's UID/GID for non-root container operation
    CURRENT_UID=$(id -u)
    CURRENT_GID=$(id -g)
    
    cat > "$ENV_FILE" << EOF
# Ollama ROCm Configuration
# Generated by setup.sh on $(date)
# Detected GPU: $GPU_NAME ($GPU_CHIP)

# =============================================================================
# MODEL PERFORMANCE TUNING
# =============================================================================
# These settings directly affect model quality and responsiveness.
# See .env.example for detailed descriptions of each setting.
#
# IMPORTANT: If models seem to forget context, ignore instructions, or give
# confused responses, increase OLLAMA_NUM_CTX first.

# Context window size (tokens) - CRITICAL for agentic/coding tasks
# Recommended: 32768 (general), 65536 (coding/agentic tasks)
OLLAMA_NUM_CTX=32768

# GPU layer offloading (-1 = all layers on GPU)
OLLAMA_NUM_GPU=-1

# Request timeout in seconds
OLLAMA_REQUEST_TIMEOUT=300

# =============================================================================
# SYSTEM-SPECIFIC SETTINGS (auto-detected)
# =============================================================================

VIDEO_GROUP_ID=$VIDEO_GID
RENDER_GROUP_ID=$RENDER_GID
HSA_OVERRIDE_GFX_VERSION=$HSA_VERSION

# Container user (runs as your user instead of root for easier cleanup)
OLLAMA_UID=$CURRENT_UID
OLLAMA_GID=$CURRENT_GID

# =============================================================================
# RUNTIME SETTINGS
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

# Check if the data directory has root-owned files (from previous root container)
# This can happen when upgrading from root to non-root container configuration
if [ -d "$OLLAMA_DATA_DIR" ]; then
    ROOT_OWNED_FILES=$(find "$OLLAMA_DATA_DIR" -user root 2>/dev/null | head -5)
    if [ -n "$ROOT_OWNED_FILES" ]; then
        echo ""
        print_warning "Found root-owned files in $OLLAMA_DATA_DIR"
        print_status "This is from a previous installation that ran as root."
        print_status "The container now runs as your user for easier cleanup."
        echo ""
        
        if [ "$NON_INTERACTIVE" = false ]; then
            echo -e "  ${BOLD}To fix ownership, sudo is required.${NC}"
            echo ""
            if gum confirm "Fix ownership now? (requires sudo)"; then
                print_status "Fixing ownership of $OLLAMA_DATA_DIR..."
                if sudo chown -R "$(id -u):$(id -g)" "$OLLAMA_DATA_DIR"; then
                    print_success "Ownership fixed"
                else
                    print_error "Failed to fix ownership"
                    echo ""
                    echo "Try manually:"
                    echo "  sudo chown -R \$(id -u):\$(id -g) $OLLAMA_DATA_DIR"
                    echo ""
                    exit 1
                fi
            else
                print_warning "Skipping ownership fix - container may fail to start"
                print_status "You can fix this later with:"
                echo "  sudo chown -R \$(id -u):\$(id -g) $OLLAMA_DATA_DIR"
                echo ""
            fi
        else
            print_status "Non-interactive mode: attempting to fix ownership with sudo..."
            if sudo chown -R "$(id -u):$(id -g)" "$OLLAMA_DATA_DIR" 2>/dev/null; then
                print_success "Ownership fixed"
            else
                print_warning "Could not fix ownership - container may fail to start"
                print_status "Fix manually with: sudo chown -R \$(id -u):\$(id -g) $OLLAMA_DATA_DIR"
            fi
        fi
    fi
fi

print_status "Pulling Ollama ROCm Docker image..."
print_status "This may take a few minutes on first run..."
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
print_success "Docker image pulled"

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
print_success "Container started"

print_status "Waiting for Ollama to start..."
MAX_ATTEMPTS=60
ATTEMPT=0
start_spinner "Waiting for Ollama API to respond"
while ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        stop_spinner false "Ollama failed to start after ${MAX_ATTEMPTS} seconds"
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
            echo -e "${YELLOW}${BOLD}To fix:${NC}"
            echo -e "  1. Run: ${CYAN}./setup.sh --fix-permissions${NC}"
            echo -e "  2. Log out and log back in"
            echo -e "  3. Run: ${CYAN}./setup.sh${NC}"
        fi
        
        exit 1
    fi
    sleep 1
done
stop_spinner true "Ollama is running"

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
# Check for Pre-existing Models
# -----------------------------------------------------------------------------

# Check if there are already models installed (from a previous installation)
EXISTING_MODELS=$(docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
if [ -n "$EXISTING_MODELS" ]; then
    echo ""
    print_warning "Found pre-existing models from a previous installation:"
    echo ""
    docker exec ollama ollama list || true
    echo ""
    
    if [ "$NON_INTERACTIVE" = false ]; then
        echo -e "${YELLOW}These models may be left over from a failed uninstall.${NC}"
        echo -e "${DIM}You can keep them or remove them to start fresh.${NC}"
        echo ""
        
        if gum confirm "Remove pre-existing models and start fresh?"; then
            echo ""
            print_status "Removing pre-existing models..."
            while IFS= read -r model; do
                [ -z "$model" ] && continue
                print_status "Removing $model..."
                docker exec ollama ollama rm "$model" 2>/dev/null || true
            done <<< "$EXISTING_MODELS"
            print_success "Pre-existing models removed"
        else
            print_status "Keeping pre-existing models"
        fi
        echo ""
    else
        print_status "Use --non-interactive skips cleanup prompt. Models will be kept."
    fi
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
            echo -e "  ${DIM}Download time depends on your internet speed.${NC}"
            echo -e "  ${DIM}Rough estimate: 5-15 minutes per 10GB on typical broadband.${NC}"
            echo -e "  ${DIM}Downloads can be resumed if interrupted.${NC}"
            echo ""
            echo -e "  Press ${BOLD}Enter${NC} to start downloading, or ${BOLD}n${NC} to skip for now."
            read -p "  Download now? [Y/n] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                print_status "Skipping downloads. You can download models later with:"
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
docker exec ollama ollama list || true

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
            print_status "Merging new models into existing OpenCode config..."
            "$SCRIPT_DIR/sync-opencode-config.sh" --merge
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

# Ensure model info is loaded for category detection
if [[ ${#MODEL_INFO[@]} -eq 0 ]]; then
    load_models_conf
fi

# Find the best model for testing
# Preference order: small category models > preferred models > any model
TEST_MODEL=""
INSTALLED_MODELS=$(docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')

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

# Fallback: check for preferred models (good instruction following)
if [ -z "$TEST_MODEL" ]; then
    PREFERRED_TEST_MODELS=("qwen2:0.5b" "qwen3:8b" "qwen3:14b" "qwen2.5-coder:3b")
    for preferred in "${PREFERRED_TEST_MODELS[@]}"; do
        if echo "$INSTALLED_MODELS" | grep -qx "$preferred"; then
            TEST_MODEL="$preferred"
            break
        fi
    done
fi

# Final fallback: use first installed model
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
    
    # Run the inference test with spinner (first run loads model into VRAM)
    TEST_OUTPUT_FILE=$(mktemp)
    start_spinner "Loading model into VRAM and running inference"
    START_TIME=$(date +%s)
    docker exec ollama ollama run "$TEST_MODEL" "Respond in English with only these three words: GPU TEST OK" > "$TEST_OUTPUT_FILE" 2>&1 || true
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    stop_spinner true
    
    # Show the response
    TEST_RESPONSE=$(head -5 "$TEST_OUTPUT_FILE")
    rm -f "$TEST_OUTPUT_FILE"
    
    echo "$TEST_RESPONSE"
    echo ""
    print_success "Inference test complete (${DURATION}s)"
    
    # Provide feedback on GPU vs CPU
    if docker exec ollama ls /dev/kfd &>/dev/null; then
        print_success "GPU acceleration is available"
    else
        print_warning "Running on CPU (GPU device not detected)"
    fi
    
    # Tip about removing test model if it's a small one
    if [ "$IS_SMALL_MODEL" = true ]; then
        echo ""
        echo -e "${DIM}Tip: The small test model ($TEST_MODEL) can be removed to save space:${NC}"
        echo -e "${DIM}  docker exec ollama ollama rm $TEST_MODEL${NC}"
    fi
else
    print_warning "No models installed yet - skipping inference test"
    print_status "Run a test later with: docker exec ollama ollama run qwen2:0.5b 'Hello'"
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
echo "  1. Edit models.conf and re-run ./setup.sh to select new models for download"
echo "     and to regenerate the OpenCode config file"
echo "  2. Or pull directly: docker exec ollama ollama pull <model:tag>"
echo "  3. After pulling directly, run ./sync-opencode-config.sh to update OpenCode"
echo ""
echo -e "${BOLD}Using OpenCode:${NC}"
echo "  1. Run 'opencode' in any project directory"
echo "  2. Use '/models' to select a local Ollama model"
echo ""
echo -e "${BOLD}Direct CLI chat:${NC}"
if [[ ${#CONFIG_MODELS[@]} -gt 0 ]]; then
    echo "  docker exec -it ollama ollama run ${CONFIG_MODELS[0]}"
else
    echo "  docker exec -it ollama ollama run <model-name>"
fi
echo ""

if [ "$OPENCODE_INSTALLED" = false ]; then
    print_warning "Don't forget to install OpenCode: https://opencode.ai"
fi

echo -e "${GREEN}${BOLD}Happy coding!${NC}"
echo ""
