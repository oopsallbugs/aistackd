#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp ROCm/HIP Setup Script
# Linux-only setup for AMD GPUs with automatic system detection
# =============================================================================

# -----------------------------------------------------------------------------
# OS Check - This script is Linux-only (ROCm/HIP)
# -----------------------------------------------------------------------------

if [[ "$(uname -s)" != "Linux" ]]; then
    echo
    echo "ERROR: This setup script is for Linux only."
    echo
    echo "ROCm/HIP (AMD's GPU compute platform) is Linux-only."
    echo
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "For macOS, llama.cpp uses Metal backend instead."
        echo "A separate setup-macos.sh script may be added in the future."
        echo
        echo "Manual macOS setup:"
        echo "  git clone https://github.com/ggerganov/llama.cpp"
        echo "  cd llama.cpp && cmake -B build && cmake --build build --config Release"
    fi
    echo
    exit 1
fi

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

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

# Check for gum (nice TUI)
HAS_GUM=false
if command -v gum &>/dev/null; then
    HAS_GUM=true
fi

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

# Spinner for long operations
SPINNER_CHARS='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
SPINNER_PID=""

cleanup_spinner() {
    if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
    fi
    SPINNER_PID=""
    printf "\r\033[K"
}

# Track if we're handling a user interrupt
USER_INTERRUPTED=false

handle_interrupt() {
    USER_INTERRUPTED=true
    cleanup_spinner
    echo
    echo
    print_status "Setup cancelled by user (Ctrl+C)"
    echo
    echo -e "${DIM}You can resume setup anytime by running ./setup.sh again${NC}"
    echo
    exit 130
}

handle_exit() {
    cleanup_spinner
}

trap handle_interrupt INT TERM
trap handle_exit EXIT

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
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    printf "\r\033[K"
    
    if [[ -n "$message" ]]; then
        if [[ "$success" == true ]]; then
            print_success "$message"
        else
            print_error "$message"
        fi
    fi
}

# Download spinner with progress tracking
start_download_spinner() {
    local message="$1"
    local output_file="$2"
    local expected_size="$3"  # Optional expected size in bytes
    local start_time=$SECONDS
    (
        local i=0
        local spin_len=${#SPINNER_CHARS}
        while true; do
            local elapsed=$((SECONDS - start_time))
            local current_size=0
            local size_str=""
            
            if [[ -f "$output_file" ]]; then
                current_size=$(stat -c%s "$output_file" 2>/dev/null || stat -f%z "$output_file" 2>/dev/null || echo 0)
            fi
            
            # Format size
            if [[ $current_size -ge 1073741824 ]]; then
                size_str="$(echo "scale=1; $current_size / 1073741824" | bc 2>/dev/null || echo "?")GB"
            elif [[ $current_size -ge 1048576 ]]; then
                size_str="$(( current_size / 1048576 ))MB"
            elif [[ $current_size -gt 0 ]]; then
                size_str="$(( current_size / 1024 ))KB"
            fi
            
            # Show progress with optional percentage
            if [[ -n "$expected_size" && "$expected_size" -gt 0 && $current_size -gt 0 ]]; then
                local pct=$(( current_size * 100 / expected_size ))
                printf "\r  ${CYAN}%s${NC} %s ${DIM}[%s] %d%% (%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$size_str" "$pct" "$elapsed"
            elif [[ -n "$size_str" ]]; then
                printf "\r  ${CYAN}%s${NC} %s ${DIM}[%s] (%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$size_str" "$elapsed"
            else
                printf "\r  ${CYAN}%s${NC} %s ${DIM}(%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$elapsed"
            fi
            
            i=$(( (i + 1) % spin_len ))
            sleep 0.2
        done
    ) &
    SPINNER_PID=$!
}

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

LLAMA_CPP_DIR="$SCRIPT_DIR/llama.cpp"
MODELS_DIR="$SCRIPT_DIR/models"
MODELS_CONF="$SCRIPT_DIR/models.conf"
METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
PARENT_ENV="$PARENT_DIR/.env"
LOCAL_ENV="$SCRIPT_DIR/.env"
OPENCODE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"

# Default values (can be overridden by parent .env)
DEFAULT_CONTEXT=32768
DEFAULT_OUTPUT=8192
DEFAULT_PORT=8080
GPU_TARGET=""

# Model metadata for OpenCode config
declare -A MODEL_DISPLAY_NAME
declare -A MODEL_CONTEXT_LIMIT
declare -A MODEL_OUTPUT_LIMIT

# Parse command line arguments
SKIP_BUILD=false
SKIP_MODELS=false
FORCE_REBUILD=false
NON_INTERACTIVE=false
IGNORE_WARNINGS=false
RUN_STATUS=false
RUN_UPDATE=false
FIX_PERMISSIONS=false
RUN_VERIFY=false
VERIFY_MODEL=""
for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --skip-models) SKIP_MODELS=true ;;
        --force-rebuild) FORCE_REBUILD=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --ignore-warnings) IGNORE_WARNINGS=true ;;
        --status) RUN_STATUS=true ;;
        --update) RUN_UPDATE=true ;;
        --fix-permissions) FIX_PERMISSIONS=true ;;
        --verify) RUN_VERIFY=true ;;
        --verify=*) RUN_VERIFY=true; VERIFY_MODEL="${arg#*=}" ;;
        --help|-h)
            echo "Usage: ./setup.sh [OPTIONS]"
            echo
            echo "Commands:"
            echo "  --status            Show current llama.cpp status"
            echo "  --update            Update llama.cpp to latest version and rebuild"
            echo "  --fix-permissions   Fix GPU access permissions (add user to groups)"
            echo "  --verify[=model]    Verify model file integrity (all or specific)"
            echo
            echo "Setup Options:"
            echo "  --skip-build        Skip building llama.cpp (use existing build)"
            echo "  --skip-models       Skip model selection and downloading"
            echo "  --force-rebuild     Force rebuild even if build exists"
            echo "  --non-interactive   Use default selections (no prompts)"
            echo "  --ignore-warnings   Continue setup despite permission warnings"
            echo "  --help, -h          Show this help message"
            echo
            echo "Files:"
            echo "  models.conf         Edit to customize available GGUF models"
            echo "  models-metadata.conf  Display names and context limits for OpenCode"
            echo "  .env                Local config (inherits from parent .env)"
            echo "  .env.example        Template with all available settings"
            echo
            echo "Examples:"
            echo "  ./setup.sh                      # Interactive setup"
            echo "  ./setup.sh --status             # Check current status"
            echo "  ./setup.sh --update             # Update llama.cpp"
            echo "  ./setup.sh --fix-permissions    # Fix GPU permissions"
            echo "  ./setup.sh --verify             # Verify all downloaded models"
            echo "  ./setup.sh --non-interactive    # Automated setup with defaults"
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
    
    # Don't show error message if user cancelled (Ctrl+C)
    # Exit code 130 = 128 + 2 (SIGINT)
    if [[ "$USER_INTERRUPTED" == true ]] || [[ $exit_code -eq 130 ]]; then
        exit "$exit_code"
    fi
    
    echo
    print_error "Something went wrong during setup."
    echo
    echo "Common solutions:"
    echo "  1. Make sure ROCm is installed:"
    echo "     rocminfo"
    echo
    echo "  2. Check HIP is available:"
    echo "     hipconfig --version"
    echo
    echo "  3. Ensure you have build tools:"
    echo "     cmake --version && make --version"
    echo
    echo -e "${DIM}(Technical: error on line $line_number, exit code $exit_code)${NC}"
    exit "$exit_code"
}

# -----------------------------------------------------------------------------
# GPU Detection
# -----------------------------------------------------------------------------

# Get HSA override version based on GPU architecture
get_hsa_version() {
    local gpu_target="$1"
    case "$gpu_target" in
        gfx110*)  echo "11.0.0" ;;  # RDNA3
        gfx103*)  echo "10.3.0" ;;  # RDNA2
        gfx101*)  echo "10.1.0" ;;  # RDNA1
        gfx906)   echo "9.0.6" ;;   # Vega 20
        gfx900)   echo "9.0.0" ;;   # Vega 10
        *)        echo "11.0.0" ;;  # Default to RDNA3
    esac
}

detect_amd_gpu() {
    local gpu_info
    gpu_info=$(lspci 2>/dev/null | grep -i 'vga.*amd\|display.*amd' | head -1) || true
    
    if [[ -z "$gpu_info" ]]; then
        echo "unknown|Unknown AMD GPU|gfx900"
        return
    fi
    
    # Map GPU to architecture
    if [[ "$gpu_info" =~ "Navi 31" ]]; then
        echo "navi31|RX 7900 XTX/XT/GRE|gfx1100"
    elif [[ "$gpu_info" =~ "Navi 32" ]]; then
        echo "navi32|RX 7800/7700 XT|gfx1101"
    elif [[ "$gpu_info" =~ "Navi 33" ]]; then
        echo "navi33|RX 7600|gfx1102"
    elif [[ "$gpu_info" =~ "Navi 21" ]]; then
        echo "navi21|RX 6900/6800 XT|gfx1030"
    elif [[ "$gpu_info" =~ "Navi 22" ]]; then
        echo "navi22|RX 6700 XT|gfx1031"
    elif [[ "$gpu_info" =~ "Navi 23" ]]; then
        echo "navi23|RX 6600 XT/6600|gfx1032"
    elif [[ "$gpu_info" =~ "Navi 10" ]]; then
        echo "navi10|RX 5700 XT/5700|gfx1010"
    elif [[ "$gpu_info" =~ "Vega 20" ]]; then
        echo "vega20|Radeon VII|gfx906"
    elif [[ "$gpu_info" =~ "Vega 10" ]]; then
        echo "vega10|RX Vega 64/56|gfx900"
    else
        echo "unknown|Unknown AMD GPU|gfx900"
    fi
}

# -----------------------------------------------------------------------------
# VRAM Detection and Model Recommendations
# -----------------------------------------------------------------------------

DETECTED_VRAM_GB=""

get_vram_gb() {
    # Detect GPU VRAM in GB using rocm-smi
    # Returns the VRAM of the first GPU found
    
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
    # Extract numeric GB value from model size string (e.g., "20GB" -> 20, "0.6GB" -> 1)
    local size_str="$1"
    local size_num
    size_num=$(echo "$size_str" | grep -oE '[0-9]+\.?[0-9]*' | head -1)
    # Round up for fractional sizes
    echo "${size_num%.*}"
}

get_model_hardware_status() {
    # Returns hardware status for a model: "recommended", "may_struggle", or "wont_fit"
    # Args: model_size_str, vram_gb
    local model_size_str="$1"
    local vram="$2"
    
    # If VRAM unknown, return empty
    if [[ "$vram" == "0" || -z "$vram" ]]; then
        echo
        return
    fi
    
    local model_size
    model_size=$(get_model_size_gb "$model_size_str")
    [[ -z "$model_size" || "$model_size" == "0" ]] && model_size=1
    
    # Calculate thresholds
    # - Model <= 80% VRAM = recommended (leaves headroom for context/overhead)
    # - Model 80-100% VRAM = may struggle (might work but slow/limited context)
    # - Model > 100% VRAM = won't fit
    local threshold_recommended=$((vram * 80 / 100))
    local threshold_struggle=$vram
    
    if (( model_size <= threshold_recommended )); then
        echo "recommended"
    elif (( model_size <= threshold_struggle )); then
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
            echo -e "${GREEN}[fits ${vram}GB]${NC}"
            ;;
        may_struggle)
            echo -e "${YELLOW}[tight fit]${NC}"
            ;;
        wont_fit)
            echo -e "${RED}[too large]${NC}"
            ;;
        *)
            echo
            ;;
    esac
}

# -----------------------------------------------------------------------------
# Load Parent Environment
# -----------------------------------------------------------------------------

load_parent_env() {
    if [[ -f "$PARENT_ENV" ]]; then
        print_status "Loading GPU configuration from parent .env"
        set -a
        # shellcheck source=/dev/null
        source "$PARENT_ENV"
        set +a
        return 0
    fi
    return 1
}

# -----------------------------------------------------------------------------
# Load Model Metadata for OpenCode Config
# -----------------------------------------------------------------------------

load_metadata_conf() {
    # Load model metadata for OpenCode config generation
    if [[ ! -f "$METADATA_CONF" ]]; then
        return  # Silently skip if file doesn't exist
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

# -----------------------------------------------------------------------------
# Model Selection Functions
# -----------------------------------------------------------------------------
# Models are loaded from models.conf. New models can be added via:
#   ./download-model.sh --add <repo>
# This will append them to models.conf and they'll appear here on next run.
# -----------------------------------------------------------------------------

declare -A MODEL_SELECTED
declare -a MODEL_ORDER
declare -A MODEL_INFO

load_models_conf() {
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found at: $MODELS_CONF"
        exit 1
    fi
    
    # Reset arrays to avoid duplicates on subsequent calls
    MODEL_ORDER=()
    MODEL_SELECTED=()
    MODEL_INFO=()
    
    local first_in_category=""
    declare -A CATEGORY_SEEN
    
    while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
        # Skip comments and empty lines
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$category" ]] && continue
        # Skip ALIAS lines
        [[ "$category" =~ ^ALIAS: ]] && continue
        
        # Trim whitespace
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        
        MODEL_ORDER+=("$model_id")
        MODEL_INFO["$model_id"]="$category|$hf_repo|$gguf_file|$size|$description"
        
        # Select first model in each category by default
        if [[ -z "${CATEGORY_SEEN[$category]:-}" ]]; then
            MODEL_SELECTED["$model_id"]=1
            CATEGORY_SEEN["$category"]=1
        else
            MODEL_SELECTED["$model_id"]=0
        fi
    done < "$MODELS_CONF"
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

gum_model_selection() {
    local options=()
    local vram_gb
    vram_gb=$(get_vram_gb)
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
        
        # Check if model already downloaded
        local downloaded_prefix=""
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            downloaded_prefix="★ "
        fi
        
        local label="${downloaded_prefix}$model (~$size) - $description"
        options+=("$label")
    done
    
    echo
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo -e "${CYAN}${BOLD}  Select GGUF Models to Download${NC}"
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo
    echo -e "${DIM}★ = already downloaded${NC}"
    if [[ "$vram_gb" -gt 0 ]]; then
        echo -e "${DIM}Detected VRAM: ${vram_gb}GB${NC}"
    fi
    echo -e "${DIM}Use Space to toggle, Enter to confirm${NC}"
    echo
    
    # Build preselected list
    local preselected_labels=()
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
            local downloaded_prefix=""
            if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
                downloaded_prefix="★ "
            fi
            preselected_labels+=("${downloaded_prefix}$model (~$size) - $description")
        fi
    done
    
    local selected_csv=""
    if [[ ${#preselected_labels[@]} -gt 0 ]]; then
        selected_csv=$(IFS=,; echo "${preselected_labels[*]}")
    fi
    
    local selections
    if [[ -n "$selected_csv" ]]; then
        selections=$(gum choose --no-limit \
            --cursor-prefix="○ " \
            --selected-prefix="✓ " \
            --unselected-prefix="○ " \
            --cursor.foreground="212" \
            --selected.foreground="212" \
            --height=20 \
            --selected="$selected_csv" \
            "${options[@]}") || {
            echo
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
            echo
            print_status "Model selection cancelled"
            exit 0
        }
    fi
    
    # Reset selections
    for model in "${MODEL_ORDER[@]}"; do
        MODEL_SELECTED["$model"]=0
    done
    
    # Parse selections
    while IFS= read -r line; do
        line="${line#★ }"  # Strip star prefix
        local selected_model="${line%% (~*}"
        if [[ -n "$selected_model" && -n "${MODEL_INFO[$selected_model]+x}" ]]; then
            MODEL_SELECTED["$selected_model"]=1
        fi
    done <<< "$selections"
}

download_model() {
    local model_id="$1"
    IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model_id]}"
    
    local output_path="$MODELS_DIR/$gguf_file"
    
    if [[ -f "$output_path" ]]; then
        print_status "$model_id already downloaded"
        return 0
    fi
    
    mkdir -p "$MODELS_DIR"
    
    # Get expected file size from HuggingFace API (optional, for progress %)
    local expected_bytes=""
    if command -v curl &>/dev/null && command -v jq &>/dev/null; then
        expected_bytes=$(curl -sf "https://huggingface.co/api/models/$hf_repo/tree/main" 2>/dev/null | \
            jq -r ".[] | select(.path == \"$gguf_file\") | .size" 2>/dev/null || echo)
    fi
    
    if command -v huggingface-cli &>/dev/null; then
        # huggingface-cli has its own progress, use spinner alongside
        start_download_spinner "Downloading $model_id ($size)" "$output_path" "$expected_bytes"
        huggingface-cli download "$hf_repo" "$gguf_file" --local-dir "$MODELS_DIR" --local-dir-use-symlinks False --quiet 2>/dev/null
        local dl_status=$?
        stop_spinner
        
        if [[ $dl_status -ne 0 ]]; then
            print_error "Failed to download $model_id"
            return 1
        fi
    else
        # Fallback to curl with spinner
        local url="https://huggingface.co/$hf_repo/resolve/main/$gguf_file"
        start_download_spinner "Downloading $model_id ($size)" "$output_path" "$expected_bytes"
        curl -sfL -o "$output_path" "$url" 2>/dev/null
        local dl_status=$?
        stop_spinner
        
        if [[ $dl_status -ne 0 ]]; then
            print_error "Failed to download $model_id"
            rm -f "$output_path"
            return 1
        fi
    fi
    
    if [[ -f "$output_path" ]]; then
        local actual_size
        actual_size=$(du -h "$output_path" | cut -f1)
        print_success "$model_id downloaded ($actual_size)"
    else
        print_error "Failed to download $model_id"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# OpenCode Config Generation
# -----------------------------------------------------------------------------

generate_opencode_config() {
    local models=("$@")
    local config=""
    local first=true
    
    # Load metadata if available
    load_metadata_conf
    
    config='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "llama.cpp": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "llama.cpp (local)",
      "options": {
        "baseURL": "http://127.0.0.1:'"$DEFAULT_PORT"'/v1"
      },
      "models": {'
    
    for model in "${models[@]}"; do
        [[ -z "$model" ]] && continue
        
        IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
        
        local display_name context_limit output_limit
        
        # Check if we have metadata for this model
        if [[ -n "${MODEL_DISPLAY_NAME[$model]:-}" ]]; then
            display_name="${MODEL_DISPLAY_NAME[$model]}"
            context_limit="${MODEL_CONTEXT_LIMIT[$model]}"
            output_limit="${MODEL_OUTPUT_LIMIT[$model]}"
        else
            # Fall back to description from models.conf and category-based limits
            display_name="$description"
            context_limit=$DEFAULT_CONTEXT
            output_limit=$DEFAULT_OUTPUT
            if [[ "$category" == "coding" ]]; then
                context_limit=65536
                output_limit=16384
            fi
        fi
        
        if [[ "$first" == true ]]; then
            first=false
        else
            config+=","
        fi
        
        config+="
        \"$model\": {
          \"name\": \"$display_name\",
          \"tools\": true,
          \"limit\": { \"context\": $context_limit, \"output\": $output_limit }
        }"
    done
    
    config+='
      }
    }
  }
}'
    
    echo "$config"
}

# -----------------------------------------------------------------------------
# Status Mode
# -----------------------------------------------------------------------------

if [[ $RUN_STATUS == true ]]; then
    print_header "llama.cpp Status"
    echo
    
    # Build status
    echo -e "  ${BOLD}Build:${NC}"
    if [[ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]]; then
        echo -e "    $CHECKMARK llama-server binary: ${GREEN}found${NC}"
        echo -e "    $CHECKMARK Location: $LLAMA_CPP_DIR/build/bin/llama-server"
    else
        echo -e "    $CROSSMARK llama-server binary: ${RED}not built${NC}"
        echo -e "    ${DIM}Run ./setup.sh to build${NC}"
    fi
    
    # Server status
    echo
    echo -e "  ${BOLD}Server:${NC}"
    if curl -sf "http://127.0.0.1:$DEFAULT_PORT/health" &>/dev/null; then
        echo -e "    $CHECKMARK Status: ${GREEN}running${NC}"
        echo -e "    $CHECKMARK Endpoint: http://127.0.0.1:$DEFAULT_PORT"
    else
        echo -e "    $CROSSMARK Status: ${RED}not running${NC}"
        echo -e "    ${DIM}Start with: ./start-server.sh <model>${NC}"
    fi
    
    # Models
    echo
    echo -e "  ${BOLD}Downloaded Models:${NC}"
    if [[ -d "$MODELS_DIR" ]]; then
        model_count=0
        for gguf in "$MODELS_DIR"/*.gguf; do
            [[ -f "$gguf" ]] || continue
            fname=$(basename "$gguf")
            fsize=$(du -h "$gguf" | cut -f1)
            echo -e "    - $fname ($fsize)"
            ((model_count++))
        done
        if [[ $model_count -eq 0 ]]; then
            echo -e "    ${DIM}No models downloaded${NC}"
        fi
    else
        echo -e "    ${DIM}Models directory not found${NC}"
    fi
    
    # GPU
    echo
    echo -e "  ${BOLD}GPU:${NC}"
    IFS='|' read -r GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
    echo -e "    $CHECKMARK Detected: ${GREEN}$GPU_NAME${NC}"
    echo -e "    $CHECKMARK Target: $GPU_TARGET"
    
    # VRAM
    vram_gb=$(get_vram_gb)
    if [[ "$vram_gb" -gt 0 ]]; then
        echo -e "    $CHECKMARK VRAM: ${GREEN}${vram_gb}GB${NC}"
    fi
    
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Fix Permissions Mode
# -----------------------------------------------------------------------------

if [[ $FIX_PERMISSIONS == true ]]; then
    print_header "Fixing GPU Access Permissions"
    echo
    
    CURRENT_USER=$(whoami)
    CHANGES_MADE=false
    NEEDS_LOGOUT=false
    
    # Check video group
    if getent group video &>/dev/null; then
        if groups "$CURRENT_USER" | grep -qw video; then
            echo -e "  $CHECKMARK User '$CURRENT_USER' already in 'video' group"
        else
            echo -e "  ${YELLOW}Adding '$CURRENT_USER' to 'video' group...${NC}"
            if sudo usermod -aG video "$CURRENT_USER"; then
                echo -e "  $CHECKMARK Added to 'video' group"
                CHANGES_MADE=true
                NEEDS_LOGOUT=true
            else
                echo -e "  $CROSSMARK Failed to add to 'video' group"
            fi
        fi
    else
        echo -e "  $WARNMARK 'video' group does not exist on this system"
    fi
    
    # Check render group
    if getent group render &>/dev/null; then
        if groups "$CURRENT_USER" | grep -qw render; then
            echo -e "  $CHECKMARK User '$CURRENT_USER' already in 'render' group"
        else
            echo -e "  ${YELLOW}Adding '$CURRENT_USER' to 'render' group...${NC}"
            if sudo usermod -aG render "$CURRENT_USER"; then
                echo -e "  $CHECKMARK Added to 'render' group"
                CHANGES_MADE=true
                NEEDS_LOGOUT=true
            else
                echo -e "  $CROSSMARK Failed to add to 'render' group"
            fi
        fi
    else
        echo -e "  $WARNMARK 'render' group does not exist on this system"
    fi
    
    # Check /dev/kfd permissions
    echo
    echo -e "  ${BOLD}Device Permissions:${NC}"
    if [[ -e /dev/kfd ]]; then
        if [[ -r /dev/kfd && -w /dev/kfd ]]; then
            echo -e "  $CHECKMARK /dev/kfd is accessible"
        else
            echo -e "  $CROSSMARK /dev/kfd exists but is not accessible"
            echo -e "    ${DIM}This may require a logout/login after group changes${NC}"
        fi
    else
        echo -e "  $CROSSMARK /dev/kfd not found - ROCm may not be installed"
    fi
    
    # Check /dev/dri permissions
    if [[ -d /dev/dri ]]; then
        if [[ -r /dev/dri/renderD128 ]]; then
            echo -e "  $CHECKMARK /dev/dri/renderD128 is accessible"
        else
            echo -e "  $CROSSMARK /dev/dri/renderD128 not accessible"
        fi
    fi
    
    echo
    if [[ $NEEDS_LOGOUT == true ]]; then
        print_warning "Group changes require logout/login to take effect"
        echo
        echo "Options:"
        echo "  1. Log out and log back in"
        echo "  2. Reboot your system"
        echo "  3. Run: newgrp video && newgrp render (temporary, current shell only)"
        echo
    elif [[ $CHANGES_MADE == false ]]; then
        print_success "All permissions are correctly configured!"
    fi
    
    exit 0
fi

# -----------------------------------------------------------------------------
# Update Mode
# -----------------------------------------------------------------------------

if [[ $RUN_UPDATE == true ]]; then
    print_header "Updating llama.cpp"
    echo
    
    if [[ ! -d "$LLAMA_CPP_DIR" ]]; then
        print_error "llama.cpp not found at: $LLAMA_CPP_DIR"
        echo "Run ./setup.sh first to clone and build llama.cpp"
        exit 1
    fi
    
    cd "$LLAMA_CPP_DIR"
    
    # Get current commit
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    print_status "Current version: $CURRENT_COMMIT"
    
    # Fetch and check for updates
    print_status "Checking for updates..."
    git fetch origin main --quiet
    
    LOCAL_HEAD=$(git rev-parse HEAD)
    REMOTE_HEAD=$(git rev-parse origin/main)
    
    if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
        print_success "Already up to date!"
        cd "$SCRIPT_DIR"
        exit 0
    fi
    
    # Show what's new
    COMMITS_BEHIND=$(git rev-list HEAD..origin/main --count)
    print_status "Updates available: $COMMITS_BEHIND new commit(s)"
    echo
    echo -e "${DIM}Recent changes:${NC}"
    git log HEAD..origin/main --oneline | head -5
    echo
    
    # Pull updates
    print_status "Pulling updates..."
    if ! git pull origin main; then
        print_error "Failed to pull updates. You may have local changes."
        echo "Try: cd llama.cpp && git stash && git pull"
        cd "$SCRIPT_DIR"
        exit 1
    fi
    
    NEW_COMMIT=$(git rev-parse --short HEAD)
    print_success "Updated: $CURRENT_COMMIT -> $NEW_COMMIT"
    
    # Rebuild
    print_header "Rebuilding llama.cpp"
    
    # Detect GPU for build
    IFS='|' read -r GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
    print_status "Building for: $GPU_NAME ($GPU_TARGET)"
    
    # Set up HIP environment
    export HIPCXX="$(hipconfig -l)/clang"
    export HIP_PATH="$(hipconfig -R)"
    
    # Clean and rebuild
    print_status "Cleaning previous build..."
    rm -rf build
    
    print_status "Configuring CMake..."
    cmake -S . -B build \
        -DGGML_HIP=ON \
        -DGPU_TARGETS="$GPU_TARGET" \
        -DCMAKE_BUILD_TYPE=Release
    
    print_status "Building (this may take 10-20 minutes)..."
    start_spinner "Compiling llama.cpp"
    cmake --build build --config Release -- -j"$(nproc)" > /dev/null 2>&1
    stop_spinner true "Build complete"
    
    # Verify build
    if [[ -f "build/bin/llama-server" ]]; then
        print_success "llama-server rebuilt successfully"
    else
        print_error "Build failed - llama-server not found"
        cd "$SCRIPT_DIR"
        exit 1
    fi
    
    cd "$SCRIPT_DIR"
    
    echo
    print_success "Update complete!"
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Verify Mode
# -----------------------------------------------------------------------------

if [[ $RUN_VERIFY == true ]]; then
    print_header "Verifying Model Files"
    echo
    
    if [[ ! -d "$MODELS_DIR" ]]; then
        print_error "Models directory not found: $MODELS_DIR"
        exit 1
    fi
    
    VERIFY_COUNT=0
    VERIFY_PASS=0
    VERIFY_FAIL=0
    
    verify_model() {
        local model_path="$1"
        local model_name
        model_name=$(basename "$model_path")
        
        ((VERIFY_COUNT++))
        
        # Check file exists and is readable
        if [[ ! -f "$model_path" ]]; then
            echo -e "  $CROSSMARK $model_name - file not found"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        if [[ ! -r "$model_path" ]]; then
            echo -e "  $CROSSMARK $model_name - file not readable"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        # Check file size (GGUF files should be at least 1MB)
        local file_size
        file_size=$(stat -c%s "$model_path" 2>/dev/null || stat -f%z "$model_path" 2>/dev/null)
        if [[ "$file_size" -lt 1048576 ]]; then
            echo -e "  $CROSSMARK $model_name - file too small ($(numfmt --to=iec "$file_size" 2>/dev/null || echo "${file_size}B"))"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        # Check GGUF magic number (first 4 bytes should be "GGUF")
        local magic
        magic=$(head -c 4 "$model_path" 2>/dev/null | tr -d '\0')
        if [[ "$magic" != "GGUF" ]]; then
            echo -e "  $CROSSMARK $model_name - invalid GGUF format (magic: $magic)"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        # Get file size for display
        local size_human
        size_human=$(du -h "$model_path" | cut -f1)
        
        echo -e "  $CHECKMARK $model_name ($size_human) - valid GGUF"
        ((VERIFY_PASS++))
        return 0
    }
    
    if [[ -n "$VERIFY_MODEL" ]]; then
        # Verify specific model
        load_models_conf
        if [[ -n "${MODEL_INFO[$VERIFY_MODEL]:-}" ]]; then
            IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$VERIFY_MODEL]}"
            verify_model "$MODELS_DIR/$gguf_file"
        elif [[ -f "$MODELS_DIR/$VERIFY_MODEL" ]]; then
            verify_model "$MODELS_DIR/$VERIFY_MODEL"
        elif [[ -f "$MODELS_DIR/${VERIFY_MODEL}.gguf" ]]; then
            verify_model "$MODELS_DIR/${VERIFY_MODEL}.gguf"
        else
            print_error "Model not found: $VERIFY_MODEL"
            exit 1
        fi
    else
        # Verify all models in directory
        for gguf in "$MODELS_DIR"/*.gguf; do
            [[ -f "$gguf" ]] || continue
            verify_model "$gguf"
        done
    fi
    
    echo
    if [[ $VERIFY_COUNT -eq 0 ]]; then
        print_warning "No model files found in $MODELS_DIR"
    else
        echo -e "  ${BOLD}Results:${NC} $VERIFY_PASS passed, $VERIFY_FAIL failed, $VERIFY_COUNT total"
        if [[ $VERIFY_FAIL -gt 0 ]]; then
            echo
            print_warning "Some models failed verification"
            echo "Re-download failed models with: ./download-model.sh --force <model>"
            exit 1
        else
            print_success "All models verified!"
        fi
    fi
    
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------

echo
echo -e "${CYAN}${BOLD}============================================${NC}"
echo -e "${CYAN}${BOLD}  llama.cpp ROCm/HIP Setup${NC}"
echo -e "${CYAN}${BOLD}============================================${NC}"
echo

# -----------------------------------------------------------------------------
# Load Configuration
# -----------------------------------------------------------------------------

if load_parent_env; then
    print_success "Loaded GPU config from parent .env"
else
    print_warning "No parent .env found, will detect GPU settings"
fi

# Detect GPU
IFS='|' read -r GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
print_status "Detected GPU: $GPU_NAME ($GPU_TARGET)"

# -----------------------------------------------------------------------------
# Dependency Check
# -----------------------------------------------------------------------------

print_header "Checking Dependencies"

MISSING_REQUIRED=()
PERMISSION_WARNINGS=()

# Git
if command -v git &>/dev/null; then
    echo -e "  $CHECKMARK git                  installed"
else
    echo -e "  $CROSSMARK git                  not installed"
    MISSING_REQUIRED+=("git")
fi

# CMake
if command -v cmake &>/dev/null; then
    CMAKE_VERSION=$(cmake --version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
    echo -e "  $CHECKMARK cmake                installed ($CMAKE_VERSION)"
else
    echo -e "  $CROSSMARK cmake                not installed"
    MISSING_REQUIRED+=("cmake")
fi

# Make or Ninja
if command -v ninja &>/dev/null; then
    echo -e "  $CHECKMARK ninja                installed"
    BUILD_TOOL="ninja"
elif command -v make &>/dev/null; then
    echo -e "  $CHECKMARK make                 installed"
    BUILD_TOOL="make"
else
    echo -e "  $CROSSMARK make/ninja           not installed"
    MISSING_REQUIRED+=("make")
fi

# HIP/ROCm
if command -v hipconfig &>/dev/null; then
    HIP_VERSION=$(hipconfig --version 2>/dev/null || echo "unknown")
    echo -e "  $CHECKMARK hipconfig            installed ($HIP_VERSION)"
else
    echo -e "  $CROSSMARK hipconfig            not installed"
    MISSING_REQUIRED+=("rocm")
fi

# Check for HIP compiler
if command -v hipcc &>/dev/null; then
    echo -e "  $CHECKMARK hipcc                installed"
else
    echo -e "  $CROSSMARK hipcc                not installed"
    MISSING_REQUIRED+=("hipcc")
fi

# curl or huggingface-cli for downloads
if command -v huggingface-cli &>/dev/null; then
    echo -e "  $CHECKMARK huggingface-cli      installed (recommended)"
elif command -v curl &>/dev/null; then
    echo -e "  $CHECKMARK curl                 installed (fallback for downloads)"
else
    echo -e "  $CROSSMARK curl                 not installed"
    MISSING_REQUIRED+=("curl")
fi

# gum (required for interactive mode)
if [[ $NON_INTERACTIVE == false ]]; then
    if command -v gum &>/dev/null; then
        echo -e "  $CHECKMARK gum                  installed"
    else
        echo -e "  $CROSSMARK gum                  not installed (required for interactive mode)"
        MISSING_REQUIRED+=("gum")
    fi
fi

# AMD GPU device
if [[ -e /dev/kfd ]]; then
    echo -e "  $CHECKMARK AMD GPU (/dev/kfd)   detected"
else
    echo -e "  $CROSSMARK AMD GPU (/dev/kfd)   not found"
    MISSING_REQUIRED+=("amd-gpu")
fi

# User groups - these are warnings, not hard requirements
IN_VIDEO_GROUP=false
IN_RENDER_GROUP=false
if groups | grep -q '\bvideo\b'; then
    IN_VIDEO_GROUP=true
fi
if groups | grep -q '\brender\b'; then
    IN_RENDER_GROUP=true
fi

if [[ $IN_VIDEO_GROUP == true && $IN_RENDER_GROUP == true ]]; then
    echo -e "  $CHECKMARK User groups          video, render"
else
    MISSING_GROUPS=""
    [[ $IN_VIDEO_GROUP == false ]] && MISSING_GROUPS+="video "
    [[ $IN_RENDER_GROUP == false ]] && MISSING_GROUPS+="render"
    echo -e "  $WARNMARK User groups          missing: ${MISSING_GROUPS}(may cause GPU issues)"
    PERMISSION_WARNINGS+=("user-groups")
fi

# Check /dev/kfd permissions
if [[ -e /dev/kfd ]]; then
    if [[ -r /dev/kfd && -w /dev/kfd ]]; then
        echo -e "  $CHECKMARK /dev/kfd access      read/write OK"
    else
        echo -e "  $WARNMARK /dev/kfd access      no read/write permission"
        PERMISSION_WARNINGS+=("kfd-permissions")
    fi
fi

# Check /dev/dri permissions
if [[ -d /dev/dri ]]; then
    if [[ -r /dev/dri/renderD128 ]]; then
        echo -e "  $CHECKMARK /dev/dri access      OK"
    else
        echo -e "  $WARNMARK /dev/dri access      limited permissions"
        PERMISSION_WARNINGS+=("dri-permissions")
    fi
fi

echo

if [[ ${#MISSING_REQUIRED[@]} -gt 0 ]]; then
    print_header "Missing Required Dependencies"
    echo
    
    for dep in "${MISSING_REQUIRED[@]}"; do
        case $dep in
            git)
                echo -e "  ${BOLD}git:${NC}"
                echo "    Arch Linux:  sudo pacman -S git"
                echo "    Ubuntu:      sudo apt install git"
                echo
                ;;
            cmake)
                echo -e "  ${BOLD}cmake:${NC}"
                echo "    Arch Linux:  sudo pacman -S cmake"
                echo "    Ubuntu:      sudo apt install cmake"
                echo
                ;;
            make)
                echo -e "  ${BOLD}make (or ninja):${NC}"
                echo "    Arch Linux:  sudo pacman -S make ninja"
                echo "    Ubuntu:      sudo apt install build-essential ninja-build"
                echo
                ;;
            rocm|hipcc)
                echo -e "  ${BOLD}ROCm/HIP:${NC}"
                echo "    See: https://rocm.docs.amd.com/projects/install-on-linux/en/latest/"
                echo "    Arch Linux:  yay -S rocm-hip-sdk"
                echo "    Ubuntu:      Follow AMD ROCm installation guide"
                echo
                ;;
            curl)
                echo -e "  ${BOLD}curl:${NC}"
                echo "    Arch Linux:  sudo pacman -S curl"
                echo "    Ubuntu:      sudo apt install curl"
                echo
                ;;
            gum)
                echo -e "  ${BOLD}gum (interactive menus):${NC}"
                echo "    Arch Linux:  sudo pacman -S gum"
                echo "    Ubuntu:      See https://github.com/charmbracelet/gum#installation"
                echo "    Or run with: ./setup.sh --non-interactive"
                echo
                ;;
            amd-gpu)
                echo -e "  ${BOLD}AMD GPU (/dev/kfd):${NC}"
                echo "    No AMD GPU detected. This setup requires an AMD GPU with ROCm support."
                echo "    See: https://rocm.docs.amd.com/projects/install-on-linux/en/latest/"
                echo
                ;;
        esac
    done
    
    echo -e "${YELLOW}${BOLD}After installing dependencies, run this script again.${NC}"
    exit 1
fi

# Handle permission warnings
if [[ ${#PERMISSION_WARNINGS[@]} -gt 0 ]]; then
    print_header "Permission Warnings"
    echo
    
    for warn in "${PERMISSION_WARNINGS[@]}"; do
        case $warn in
            user-groups)
                echo -e "  ${BOLD}User not in video/render groups:${NC}"
                echo "    This may prevent GPU access for llama-server."
                echo
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video,render \$USER"
                echo "                 Then log out and back in"
                echo
                ;;
            kfd-permissions)
                echo -e "  ${BOLD}No read/write access to /dev/kfd:${NC}"
                echo "    GPU compute device not accessible."
                echo
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG render \$USER"
                echo "                 Then log out and back in"
                echo
                ;;
            dri-permissions)
                echo -e "  ${BOLD}Limited access to /dev/dri:${NC}"
                echo "    GPU render devices may not be accessible."
                echo
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video \$USER"
                echo "                 Then log out and back in"
                echo
                ;;
        esac
    done
    
    if [[ $IGNORE_WARNINGS == false && $NON_INTERACTIVE == false ]]; then
        echo -e "  ${DIM}The build may still succeed, but llama-server might not access the GPU.${NC}"
        echo
        
        local continue_setup=""
        if [[ "$HAS_GUM" == true ]]; then
            if gum confirm "Continue with setup?"; then
                continue_setup="y"
            else
                continue_setup="n"
            fi
        else
            read -p "Continue with setup? (y/N) " -n 1 -r
            echo
            continue_setup="$REPLY"
        fi
        
        if [[ ! "$continue_setup" =~ ^[Yy]$ ]]; then
            echo
            print_status "To fix permissions, run: ./setup.sh --fix-permissions"
            print_status "Or continue anyway with: ./setup.sh --ignore-warnings"
            echo
            exit 1
        fi
    elif [[ $NON_INTERACTIVE == true ]]; then
        echo -e "  ${DIM}Non-interactive mode: continuing despite permission warnings.${NC}"
        echo -e "  ${DIM}Fix later with: ./setup.sh --fix-permissions${NC}"
        print_warning "GPU access may fail until permissions are fixed"
    else
        print_warning "Continuing despite permission warnings (--ignore-warnings)"
    fi
fi

print_success "All dependencies satisfied!"

# -----------------------------------------------------------------------------
# Clone/Update llama.cpp
# -----------------------------------------------------------------------------

print_header "Setting Up llama.cpp Repository"

if [[ -d "$LLAMA_CPP_DIR" ]]; then
    if [[ "$FORCE_REBUILD" == true ]]; then
        print_status "Force rebuild requested, removing existing directory..."
        rm -rf "$LLAMA_CPP_DIR"
    else
        print_status "llama.cpp directory exists, pulling latest..."
        cd "$LLAMA_CPP_DIR"
        git pull || print_warning "Failed to pull latest (continuing with existing)"
        cd "$SCRIPT_DIR"
    fi
fi

if [[ ! -d "$LLAMA_CPP_DIR" ]]; then
    print_status "Cloning llama.cpp..."
    git clone https://github.com/ggerganov/llama.cpp "$LLAMA_CPP_DIR"
fi

print_success "llama.cpp repository ready"

# -----------------------------------------------------------------------------
# Build llama.cpp with HIP
# -----------------------------------------------------------------------------

if [[ "$SKIP_BUILD" == false ]]; then
    print_header "Building llama.cpp with HIP/ROCm"
    
    cd "$LLAMA_CPP_DIR"
    
    # Check if already built
    if [[ -f "build/bin/llama-server" && "$FORCE_REBUILD" != true ]]; then
        print_status "llama-server already built (use --force-rebuild to rebuild)"
    else
        print_status "Configuring CMake with HIP for $GPU_TARGET..."
        
        # Set up HIP environment
        export HIPCXX="$(hipconfig -l)/clang"
        export HIP_PATH="$(hipconfig -R)"
        
        # Configure with CMake
        cmake -S . -B build \
            -DGGML_HIP=ON \
            -DGPU_TARGETS="$GPU_TARGET" \
            -DCMAKE_BUILD_TYPE=Release
        
        print_status "Building (this may take 10-20 minutes)..."
        start_spinner "Compiling llama.cpp"
        cmake --build build --config Release -- -j"$(nproc)" > /dev/null 2>&1
        stop_spinner true "Build complete"
    fi
    
    # Verify build
    if [[ -f "build/bin/llama-server" ]]; then
        print_success "llama-server built successfully"
    else
        print_error "Build failed - llama-server not found"
        exit 1
    fi
    
    cd "$SCRIPT_DIR"
else
    print_status "Skipping build (--skip-build)"
fi

# -----------------------------------------------------------------------------
# Model Selection & Download
# -----------------------------------------------------------------------------

if [[ "$SKIP_MODELS" == false ]]; then
    print_header "Model Selection"
    
    load_models_conf
    
    if [[ "$NON_INTERACTIVE" == false ]]; then
        gum_model_selection
    else
        print_status "Using default model selection (--non-interactive)"
    fi
    
    read -ra SELECTED_MODELS <<< "$(get_selected_models)"
    
    if [[ ${#SELECTED_MODELS[@]} -eq 0 ]]; then
        print_warning "No models selected"
    else
        print_header "Downloading Models"
        
        for model in "${SELECTED_MODELS[@]}"; do
            download_model "$model"
        done
    fi
else
    print_status "Skipping model selection (--skip-models)"
fi

# -----------------------------------------------------------------------------
# Generate OpenCode Config
# -----------------------------------------------------------------------------

print_header "OpenCode Configuration"

# Get list of downloaded models
DOWNLOADED_MODELS=()
load_models_conf
for model in "${MODEL_ORDER[@]}"; do
    IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
    if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
        DOWNLOADED_MODELS+=("$model")
    fi
done

if [[ ${#DOWNLOADED_MODELS[@]} -gt 0 ]]; then
    # Check if OpenCode config exists
    if [[ -f "$OPENCODE_CONFIG" ]]; then
        print_warning "OpenCode config already exists at: $OPENCODE_CONFIG"
        print_status "To use llama.cpp, manually add the provider or backup/replace the config"
        echo
        echo "Example llama.cpp provider config:"
        echo
        generate_opencode_config "${DOWNLOADED_MODELS[@]}"
        echo
    else
        print_status "Creating OpenCode configuration..."
        mkdir -p "$(dirname "$OPENCODE_CONFIG")"
        generate_opencode_config "${DOWNLOADED_MODELS[@]}" > "$OPENCODE_CONFIG"
        print_success "OpenCode config created at: $OPENCODE_CONFIG"
    fi
else
    print_warning "No models downloaded, skipping OpenCode config"
fi

# -----------------------------------------------------------------------------
# Orphan Model Cleanup
# -----------------------------------------------------------------------------

# Check for orphan .gguf files not in models.conf
check_orphan_models() {
    # Build list of known GGUF files from models.conf
    declare -A known_files
    declare -A whitelisted_files
    
    if [[ -f "$MODELS_CONF" ]]; then
        while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
            [[ "$category" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$category" ]] && continue
            
            # Handle WHITELIST entries
            if [[ "$category" =~ ^WHITELIST: ]]; then
                local wl_file="${category#WHITELIST:}"
                wl_file="${wl_file#"${wl_file%%[![:space:]]*}"}"
                wl_file="${wl_file%"${wl_file##*[![:space:]]}"}"
                whitelisted_files["$wl_file"]=1
                continue
            fi
            
            [[ "$category" =~ ^ALIAS: ]] && continue
            
            gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
            gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
            [[ -n "$gguf_file" ]] && known_files["$gguf_file"]=1
        done < "$MODELS_CONF"
    fi
    
    # Find orphan files
    declare -a orphan_files=()
    local total_bytes=0
    
    for gguf in "$MODELS_DIR"/*.gguf; do
        [[ -f "$gguf" ]] || continue
        local filename
        filename=$(basename "$gguf")
        
        if [[ -z "${known_files[$filename]:-}" && -z "${whitelisted_files[$filename]:-}" ]]; then
            orphan_files+=("$filename")
            local fsize
            fsize=$(stat -c%s "$gguf" 2>/dev/null || stat -f%z "$gguf" 2>/dev/null || echo 0)
            total_bytes=$((total_bytes + fsize))
        fi
    done
    
    if [[ ${#orphan_files[@]} -eq 0 ]]; then
        return 0
    fi
    
    # Format total size
    local total_human
    if [[ $total_bytes -ge 1073741824 ]]; then
        total_human="$(echo "scale=1; $total_bytes / 1073741824" | bc 2>/dev/null || echo "?")GB"
    else
        total_human="$(( total_bytes / 1048576 ))MB"
    fi
    
    print_header "Orphan Models Detected"
    echo
    print_warning "Found ${#orphan_files[@]} .gguf file(s) not in models.conf (${total_human}):"
    echo
    for fname in "${orphan_files[@]}"; do
        local fpath="$MODELS_DIR/$fname"
        local fsize_human
        fsize_human=$(du -h "$fpath" 2>/dev/null | cut -f1)
        echo -e "    ${YELLOW}○${NC} $fname ${DIM}($fsize_human)${NC}"
    done
    echo
    
    if [[ "$NON_INTERACTIVE" == false ]]; then
        echo -e "${DIM}These files take up disk space but aren't tracked.${NC}"
        echo
        
        local cleanup_choice=""
        if [[ "$HAS_GUM" == true ]]; then
            cleanup_choice=$(gum choose --cursor-prefix="○ " --selected-prefix="◉ " \
                --cursor.foreground="212" \
                "Run cleanup now" \
                "Skip for now") || cleanup_choice="Skip for now"
        else
            read -r -p "Run cleanup? [y/N] " reply
            [[ "$reply" =~ ^[Yy]$ ]] && cleanup_choice="Run cleanup now"
        fi
        
        if [[ "$cleanup_choice" == "Run cleanup now" ]]; then
            echo
            "$SCRIPT_DIR/download-model.sh" --cleanup
        else
            echo -e "${DIM}Run './download-model.sh --cleanup' later to manage these files${NC}"
        fi
    else
        echo -e "${DIM}Run './download-model.sh --cleanup' to manage orphan models${NC}"
    fi
    echo
}

# Only check if models directory exists
if [[ -d "$MODELS_DIR" ]]; then
    check_orphan_models
fi

# -----------------------------------------------------------------------------
# Create local .env
# -----------------------------------------------------------------------------

print_header "Creating Local Configuration"

# Get appropriate HSA version for detected GPU
DETECTED_HSA_VERSION=$(get_hsa_version "$GPU_TARGET")

cat > "$LOCAL_ENV" << EOF
# llama.cpp Configuration
# Generated by setup.sh on $(date)

# GPU Target (detected: $GPU_NAME)
GPU_TARGET=$GPU_TARGET

# Server settings
LLAMA_PORT=$DEFAULT_PORT
LLAMA_CONTEXT=$DEFAULT_CONTEXT

# Paths
LLAMA_CPP_DIR=$LLAMA_CPP_DIR
MODELS_DIR=$MODELS_DIR

# GPU settings (auto-detected based on GPU architecture)
HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION:-$DETECTED_HSA_VERSION}
EOF

print_success "Created .env"

# -----------------------------------------------------------------------------
# Inference Test (Optional)
# -----------------------------------------------------------------------------

run_inference_test() {
    local model_id="$1"
    local gguf_file="$2"
    local model_size_mb="$3"  # Size in MB for timeout scaling
    local model_path="$MODELS_DIR/$gguf_file"
    local server_binary="$LLAMA_CPP_DIR/build/bin/llama-server"
    local test_port=18080  # Use different port to avoid conflicts
    local server_pid=""
    local server_log="/tmp/llama-server-test-$$.log"
    
    # Scale timeouts based on model size
    # Base: 60s server start, 60s inference for small models (<2GB)
    # Scale up for larger models
    local server_timeout=60
    local inference_timeout=60
    
    if [[ $model_size_mb -gt 15000 ]]; then
        # >15GB models (e.g., 32B models)
        server_timeout=180
        inference_timeout=180
    elif [[ $model_size_mb -gt 8000 ]]; then
        # 8-15GB models (e.g., 14B models)
        server_timeout=120
        inference_timeout=120
    elif [[ $model_size_mb -gt 4000 ]]; then
        # 4-8GB models (e.g., 8B models)
        server_timeout=90
        inference_timeout=90
    fi
    
    echo
    print_header "Running Inference Test"
    echo
    print_status "Testing $model_id..."
    
    # Warn about large models
    if [[ $model_size_mb -gt 8000 ]]; then
        print_warning "Large model - this may take a while (timeout: ${inference_timeout}s)"
    fi
    
    # Clean up any existing server on test port
    local existing_pid
    existing_pid=$(lsof -ti:$test_port 2>/dev/null || true)
    if [[ -n "$existing_pid" ]]; then
        kill "$existing_pid" 2>/dev/null || true
        sleep 1
    fi
    
    # Start server in background with logging
    start_spinner "Starting llama-server"
    
    HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-11.0.0}" \
    "$server_binary" \
        -m "$model_path" \
        --host 127.0.0.1 \
        --port "$test_port" \
        -c 2048 \
        -ngl 99 \
        > "$server_log" 2>&1 &
    server_pid=$!
    
    # Wait for server to be ready
    local waited=0
    local ready=false
    
    while [[ $waited -lt $server_timeout ]]; do
        # Check if process is still running
        if ! kill -0 "$server_pid" 2>/dev/null; then
            stop_spinner
            print_error "Server process died unexpectedly"
            echo -e "  ${DIM}Check log: $server_log${NC}"
            tail -5 "$server_log" 2>/dev/null | sed 's/^/  /'
            return 1
        fi
        
        if curl -sf "http://127.0.0.1:$test_port/health" &>/dev/null; then
            ready=true
            break
        fi
        sleep 1
        ((waited++))
    done
    
    stop_spinner
    
    if [[ "$ready" != true ]]; then
        print_error "Server failed to start within ${server_timeout}s"
        echo -e "  ${DIM}Check log: $server_log${NC}"
        tail -5 "$server_log" 2>/dev/null | sed 's/^/  /'
        kill "$server_pid" 2>/dev/null || true
        return 1
    fi
    
    print_success "Server ready (${waited}s)"
    
    # Run inference test
    start_spinner "Running inference test"
    
    local prompt="Say 'Hello, world!' and nothing else."
    local start_time=$SECONDS
    
    local response
    local curl_exit
    response=$(curl -s --max-time "$inference_timeout" "http://127.0.0.1:$test_port/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "test",
            "messages": [{"role": "user", "content": "'"$prompt"'"}],
            "max_tokens": 50,
            "temperature": 0.1
        }' 2>&1)
    curl_exit=$?
    
    local end_time=$SECONDS
    local duration=$((end_time - start_time))
    
    stop_spinner
    
    # Stop server
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    
    # Clean up log on success
    if [[ $curl_exit -eq 0 && -n "$response" ]]; then
        local content
        local reasoning_content
        # Try regular content first, then reasoning_content for thinking models
        content=$(echo "$response" | jq -r '.choices[0].message.content // empty' 2>/dev/null)
        reasoning_content=$(echo "$response" | jq -r '.choices[0].message.reasoning_content // empty' 2>/dev/null)
        
        # Use reasoning_content if content is empty (for reasoning/thinking models)
        if [[ -z "$content" && -n "$reasoning_content" ]]; then
            content="[thinking] ${reasoning_content:0:100}..."
        fi
        
        local tokens
        tokens=$(echo "$response" | jq -r '.usage.completion_tokens // 0' 2>/dev/null)
        local error_msg
        error_msg=$(echo "$response" | jq -r '.error.message // empty' 2>/dev/null)
        
        if [[ -n "$error_msg" ]]; then
            print_error "Server returned error: $error_msg"
            rm -f "$server_log"
            return 1
        fi
        
        # Check if we got any response (content, reasoning, or just a valid finish_reason)
        local finish_reason
        finish_reason=$(echo "$response" | jq -r '.choices[0].finish_reason // empty' 2>/dev/null)
        
        if [[ -n "$content" || -n "$finish_reason" ]]; then
            echo
            if [[ -n "$content" ]]; then
                echo -e "  ${BOLD}Response:${NC} $content"
            else
                echo -e "  ${BOLD}Status:${NC} Got valid response (finish_reason: $finish_reason)"
            fi
            echo -e "  ${BOLD}Time:${NC} ${duration}s"
            if [[ "$tokens" != "0" && "$tokens" != "null" && $duration -gt 0 ]]; then
                local tps=$(( tokens / duration ))
                echo -e "  ${BOLD}Speed:${NC} ~${tps} tokens/sec"
            fi
            echo
            print_success "Inference test passed!"
            rm -f "$server_log"
            return 0
        fi
    fi
    
    print_error "Inference test failed - no valid response"
    if [[ $curl_exit -ne 0 ]]; then
        echo -e "  ${DIM}curl exit code: $curl_exit${NC}"
    fi
    if [[ -n "$response" ]]; then
        echo -e "  ${DIM}Response: ${response:0:200}${NC}"
    fi
    rm -f "$server_log"
    return 1
}

# Ask to run inference test if we have a downloaded model
# (EXAMPLE_MODEL is set in the final summary section below)

# -----------------------------------------------------------------------------
# Setup Complete
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo
echo -e "${BOLD}Configuration:${NC}"
echo "  GPU:              $GPU_NAME ($GPU_TARGET)"
echo "  llama.cpp:        $LLAMA_CPP_DIR"
echo "  Models:           $MODELS_DIR"
echo "  Server port:      $DEFAULT_PORT"
echo
echo -e "${BOLD}Quick commands:${NC}"
echo "  Start server:     ./start-server.sh <model-id>"
echo "  Download model:   ./download-model.sh <model-id>"
echo "  Check status:     ./setup.sh --status"
echo
echo -e "${BOLD}Available models:${NC}"
for model in "${MODEL_ORDER[@]}"; do
    IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
    if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
        echo -e "  $CHECKMARK $model ($size)"
    else
        echo -e "  $CROSSMARK $model ($size) - not downloaded"
    fi
done
# Parse size string to MB for comparison (e.g., "20GB" -> 20000, "500MB" -> 500, "0.4GB" -> 400)
parse_size_mb() {
    local size="$1"
    # Handle GB with decimals (e.g., "0.4GB", "2.5GB", "20GB")
    if [[ "$size" =~ ^([0-9]+)\.([0-9]+)GB$ ]]; then
        local whole="${BASH_REMATCH[1]}"
        local frac="${BASH_REMATCH[2]}"
        # Pad or truncate fraction to 1 digit and multiply
        frac="${frac:0:1}"
        echo $(( whole * 1000 + frac * 100 ))
    elif [[ "$size" =~ ^([0-9]+)GB$ ]]; then
        echo $(( BASH_REMATCH[1] * 1000 ))
    elif [[ "$size" =~ ^([0-9]+)\.([0-9]+)MB$ ]]; then
        echo "${BASH_REMATCH[1]}"
    elif [[ "$size" =~ ^([0-9]+)MB$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo 0
    fi
}

# Category priority for EXAMPLE_MODEL (best model for daily use)
# Priority: coding > general > reasoning > autocomplete > small
get_category_priority() {
    case "$1" in
        coding)       echo 5 ;;
        general)      echo 4 ;;
        reasoning)    echo 3 ;;
        autocomplete) echo 2 ;;
        small)        echo 1 ;;
        *)            echo 0 ;;
    esac
}

# Pick EXAMPLE_MODEL: best category, largest model (for daily use recommendation)
EXAMPLE_MODEL=""
EXAMPLE_PRIORITY=-1
EXAMPLE_SIZE=0

for model in "${MODEL_ORDER[@]}"; do
    IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
    if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
        priority=$(get_category_priority "$category")
        size_mb=$(parse_size_mb "$size")
        
        # Pick this model if: higher priority category, OR same priority but larger
        if [[ $priority -gt $EXAMPLE_PRIORITY ]] || \
           [[ $priority -eq $EXAMPLE_PRIORITY && $size_mb -gt $EXAMPLE_SIZE ]]; then
            EXAMPLE_MODEL="$model"
            EXAMPLE_PRIORITY=$priority
            EXAMPLE_SIZE=$size_mb
        fi
    fi
done

# Pick TEST_MODEL: simply the smallest downloaded model (fastest for quick test)
TEST_MODEL=""
TEST_SIZE=999999

for model in "${MODEL_ORDER[@]}"; do
    IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
    if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
        size_mb=$(parse_size_mb "$size")
        
        if [[ $size_mb -lt $TEST_SIZE ]]; then
            TEST_MODEL="$model"
            TEST_SIZE=$size_mb
        fi
    fi
done

# Fall back to EXAMPLE_MODEL if no TEST_MODEL found
[[ -z "$TEST_MODEL" ]] && TEST_MODEL="$EXAMPLE_MODEL"

# Run inference test if we have a model (use TEST_MODEL for speed)
if [[ -n "$TEST_MODEL" ]]; then
    IFS='|' read -r _ _ test_gguf_file test_size _ <<< "${MODEL_INFO[$TEST_MODEL]}"
    test_size_mb=$(parse_size_mb "$test_size")
    
    if [[ "$NON_INTERACTIVE" == false ]]; then
        echo
        
        # Build list of downloaded models for "other" option
        declare -a test_models=()
        declare -a test_model_labels=()
        for model in "${MODEL_ORDER[@]}"; do
            IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
            if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
                test_models+=("$model")
                test_model_labels+=("$model ($size)")
            fi
        done
        
        test_choice=""
        selected_model=""
        
        if [[ "$HAS_GUM" == true ]]; then
            # Use gum for nice 3-option selector
            echo -e "${BOLD}Run inference test?${NC}"
            echo
            test_choice=$(gum choose --cursor-prefix="○ " --selected-prefix="◉ " \
                --cursor.foreground="212" \
                "Yes - test with $TEST_MODEL (smallest)" \
                "Choose different model" \
                "Skip test") || true
        else
            # Fallback to text prompt
            read -p "Run inference test with $TEST_MODEL (smallest)? [Y/n/other] " -r
            if [[ "$REPLY" =~ ^[Nn]$ ]]; then
                test_choice="Skip test"
            elif [[ "$REPLY" =~ ^[Oo]$ ]] || [[ "$REPLY" == "other" ]]; then
                test_choice="Choose different model"
            else
                test_choice="Yes"
            fi
        fi
        
        case "$test_choice" in
            "Skip test")
                print_status "Skipping inference test"
                ;;
            "Choose different model")
                echo
                
                if [[ "$HAS_GUM" == true ]]; then
                    # Use gum for model selection
                    echo -e "${BOLD}Select model for inference test:${NC}"
                    echo
                    selected_label=$(gum choose --cursor-prefix="○ " --selected-prefix="◉ " \
                        --cursor.foreground="212" \
                        "${test_model_labels[@]}" \
                        "Skip test") || true
                    
                    if [[ "$selected_label" == "Skip test" ]] || [[ -z "$selected_label" ]]; then
                        print_status "Skipping inference test"
                    else
                        # Find selected model from label
                        for i in "${!test_model_labels[@]}"; do
                            if [[ "${test_model_labels[$i]}" == "$selected_label" ]]; then
                                selected_model="${test_models[$i]}"
                                break
                            fi
                        done
                    fi
                else
                    # Fallback to numbered list
                    echo -e "${BOLD}Select model for inference test:${NC}"
                    echo
                    idx=1
                    for label in "${test_model_labels[@]}"; do
                        echo "  $idx) $label"
                        ((idx++))
                    done
                    echo "  0) Skip test"
                    echo
                    read -p "Select [0-$((idx-1))]: " choice
                    
                    if [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -gt 0 ]] && [[ "$choice" -lt $idx ]]; then
                        selected_model="${test_models[$((choice-1))]}"
                    elif [[ "$choice" != "0" ]]; then
                        print_warning "Invalid selection, skipping test"
                    fi
                fi
                
                # Run test with selected model
                if [[ -n "$selected_model" ]]; then
                    IFS='|' read -r _ _ sel_gguf_file sel_size _ <<< "${MODEL_INFO[$selected_model]}"
                    sel_size_mb=$(parse_size_mb "$sel_size")
                    run_inference_test "$selected_model" "$sel_gguf_file" "$sel_size_mb" || true
                fi
                ;;
            *)
                # Yes or default - run with smallest model
                run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" || true
                ;;
        esac
    else
        # In non-interactive mode, always run the test with smallest model
        run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" || true
    fi
fi

echo
echo -e "${BOLD}Using with OpenCode:${NC}"
echo "  1. Start server:  ./start-server.sh ${EXAMPLE_MODEL:-<model-id>}"
echo "  2. Run opencode in any project"
echo "  3. Use '/models' to select llama.cpp provider"
echo
echo -e "${GREEN}${BOLD}Happy coding!${NC}"
echo
