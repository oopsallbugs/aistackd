#!/usr/bin/env bash
# =============================================================================
# Common Library for llama.cpp Setup Scripts
# Shared functions for Linux (ROCm) and macOS (Metal) setup
# =============================================================================

# shellcheck disable=SC2034  # Variables are used by scripts that source this file

# Prevent multiple sourcing
[[ -n "${_COMMON_SH_LOADED:-}" ]] && return 0
_COMMON_SH_LOADED=1

# -----------------------------------------------------------------------------
# Bash Version Check
# -----------------------------------------------------------------------------
# Associative arrays require bash 4+. macOS ships with bash 3.2 by default.
# Scripts requiring associative arrays should check BASH_SUPPORTS_ASSOC_ARRAYS.

BASH_SUPPORTS_ASSOC_ARRAYS=false
if [[ ${BASH_VERSINFO[0]} -ge 4 ]]; then
    BASH_SUPPORTS_ASSOC_ARRAYS=true
fi

# -----------------------------------------------------------------------------
# Colors and Output Helpers
# -----------------------------------------------------------------------------

# Colors - only use if terminal supports them
if [[ -t 1 ]] && [[ "${TERM:-dumb}" != "dumb" ]]; then
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
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    BOLD=''
    DIM=''
    NC=''
    CHECKMARK="[OK]"
    CROSSMARK="[X]"
    WARNMARK="[!]"
fi

# Check for gum (nice TUI)
HAS_GUM=false
if command -v gum &>/dev/null; then
    HAS_GUM=true
fi

# Gum prefix styles (consistent across all scripts)
GUM_CURSOR_PREFIX="○ "
GUM_SELECTED_PREFIX="✓ "
GUM_UNSELECTED_PREFIX="○ "
# For single-select (radio button style)
GUM_RADIO_CURSOR="○ "
GUM_RADIO_SELECTED="◉ "

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

# Print main banner with gum style (falls back to plain text if gum unavailable)
# Usage: print_banner "Script Title"
print_banner() {
    local title="$1"
    echo
    if [[ "$HAS_GUM" == true ]]; then
        gum style \
            --border rounded \
            --border-foreground 212 \
            --padding "0 2" \
            --margin "0" \
            "$title"
    else
        echo -e "${CYAN}${BOLD}============================================${NC}"
        echo -e "${CYAN}${BOLD}  $title${NC}"
        echo -e "${CYAN}${BOLD}============================================${NC}"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Spinner for Long Operations
# -----------------------------------------------------------------------------

SPINNER_CHARS='⣾⣽⣻⢿⡿⣟⣯⣷'
SPINNER_PID=""

# Hide cursor for cleaner spinner animation (no flickering)
hide_cursor() {
    [[ -t 1 ]] && tput civis 2>/dev/null || true
}

# Show cursor (must be called on cleanup/exit to restore terminal)
show_cursor() {
    [[ -t 1 ]] && tput cnorm 2>/dev/null || true
}

cleanup_spinner() {
    if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
    fi
    SPINNER_PID=""
    printf "\r\033[K"
    show_cursor
}

start_spinner() {
    local message="$1"
    local start_time=$SECONDS
    
    hide_cursor
    
    (
        local i=0
        local spin_len=${#SPINNER_CHARS}
        while true; do
            local elapsed=$((SECONDS - start_time))
            printf "\r  ${CYAN}%s${NC} %s ${DIM}(%ds)${NC}\033[K" "${SPINNER_CHARS:i:1}" "$message" "$elapsed"
            i=$(( (i + 1) % spin_len ))
            sleep 0.1
        done
    ) &
    SPINNER_PID=$!
}

# shellcheck disable=SC2120  # Function has optional parameters with defaults
stop_spinner() {
    local success=${1:-true}
    local message="${2:-}"
    
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    printf "\r\033[K"
    show_cursor
    
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
    
    hide_cursor
    
    (
        local i=0
        local spin_len=${#SPINNER_CHARS}
        while true; do
            local elapsed=$((SECONDS - start_time))
            local current_size=0
            local size_str=""
            
            if [[ -f "$output_file" ]]; then
                # Cross-platform file size
                if [[ "$(uname -s)" == "Darwin" ]]; then
                    current_size=$(stat -f%z "$output_file" 2>/dev/null || echo 0)
                else
                    current_size=$(stat -c%s "$output_file" 2>/dev/null || echo 0)
                fi
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
                printf "\r  ${CYAN}%s${NC} %s ${DIM}[%s] %d%% (%ds)${NC}\033[K" "${SPINNER_CHARS:i:1}" "$message" "$size_str" "$pct" "$elapsed"
            elif [[ -n "$size_str" ]]; then
                printf "\r  ${CYAN}%s${NC} %s ${DIM}[%s] (%ds)${NC}\033[K" "${SPINNER_CHARS:i:1}" "$message" "$size_str" "$elapsed"
            else
                printf "\r  ${CYAN}%s${NC} %s ${DIM}(%ds)${NC}\033[K" "${SPINNER_CHARS:i:1}" "$message" "$elapsed"
            fi
            
            i=$(( (i + 1) % spin_len ))
            sleep 0.2
        done
    ) &
    SPINNER_PID=$!
}

# -----------------------------------------------------------------------------
# Signal Handling
# -----------------------------------------------------------------------------

# Track if we're handling a user interrupt
USER_INTERRUPTED=false

handle_interrupt() {
    USER_INTERRUPTED=true
    cleanup_spinner
    echo
    echo
    print_status "Cancelled by user (Ctrl+C)"
    echo
    echo -e "${DIM}You can resume anytime by running the script again${NC}"
    echo
    exit 130
}

handle_exit() {
    cleanup_spinner
}

# Set up signal handlers (can be overridden by sourcing script)
setup_signal_handlers() {
    trap handle_interrupt INT TERM PIPE
    trap handle_exit EXIT
}

# Check if gum command was interrupted by user (Ctrl+C)
# Usage: check_user_interrupt $?
# Call this after gum commands to exit on Ctrl+C
check_user_interrupt() {
    local exit_code="$1"
    # Exit code 130 = SIGINT (Ctrl+C), 143 = SIGTERM
    if [[ $exit_code -eq 130 || $exit_code -eq 143 ]]; then
        handle_interrupt
    fi
}

# -----------------------------------------------------------------------------
# Argument Helpers
# -----------------------------------------------------------------------------

# Check if --help or -h is in arguments (for early exit before .env validation)
# Usage: if has_help_arg "$@"; then SHOW_HELP_EARLY=true; fi
has_help_arg() {
    for arg in "$@"; do
        [[ "$arg" == "--help" || "$arg" == "-h" ]] && return 0
    done
    return 1
}

# -----------------------------------------------------------------------------
# Configuration Paths
# -----------------------------------------------------------------------------

# These can be overridden by the sourcing script before calling init_paths
init_paths() {
    local script_dir="$1"
    
    LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$script_dir/llama.cpp}"
    MODELS_DIR="${MODELS_DIR:-$script_dir/models}"
    MODELS_CONF="${MODELS_CONF:-$script_dir/models.conf}"
    LOCAL_ENV="${LOCAL_ENV:-$script_dir/.env}"
    OPENCODE_CONFIG="${OPENCODE_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json}"
    
    # Default values
    DEFAULT_CONTEXT=${DEFAULT_CONTEXT:-32768}
    DEFAULT_OUTPUT=${DEFAULT_OUTPUT:-8192}
    DEFAULT_PORT=${DEFAULT_PORT:-8080}
}

# -----------------------------------------------------------------------------
# Model Metadata for OpenCode Config
# -----------------------------------------------------------------------------

# Associative arrays for model metadata (requires bash 4+)
if [[ "$BASH_SUPPORTS_ASSOC_ARRAYS" == true ]]; then
    declare -A MODEL_DISPLAY_NAME
    declare -A MODEL_CONTEXT_LIMIT
    declare -A MODEL_OUTPUT_LIMIT
fi

load_metadata_conf() {
    # Load model metadata from models.conf (context_limit and output_limit are optional fields 7 and 8)
    # Format: category|model_id|huggingface_repo|gguf_filename|size|description|context_limit|output_limit
    if [[ ! -f "$MODELS_CONF" ]]; then
        return  # Silently skip if file doesn't exist
    fi
    
    while IFS='|' read -r category model_id hf_repo gguf_file size description context_limit output_limit || [[ -n "$category" ]]; do
        # Skip comments, empty lines, and aliases
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ "$category" =~ ^WHITELIST: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim whitespace
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        description="${description#"${description%%[![:space:]]*}"}"
        description="${description%"${description##*[![:space:]]}"}"
        context_limit="${context_limit#"${context_limit%%[![:space:]]*}"}"
        context_limit="${context_limit%"${context_limit##*[![:space:]]}"}"
        output_limit="${output_limit#"${output_limit%%[![:space:]]*}"}"
        output_limit="${output_limit%"${output_limit##*[![:space:]]}"}"
        
        # Use description as display name
        MODEL_DISPLAY_NAME["$model_id"]="$description"
        
        # Use explicit limits if provided, otherwise use category-based defaults
        if [[ -n "$context_limit" && "$context_limit" =~ ^[0-9]+$ ]]; then
            MODEL_CONTEXT_LIMIT["$model_id"]="$context_limit"
        else
            # Category-based defaults
            case "$category" in
                coding)       MODEL_CONTEXT_LIMIT["$model_id"]=65536 ;;
                vision)       MODEL_CONTEXT_LIMIT["$model_id"]=16384 ;;
                *)            MODEL_CONTEXT_LIMIT["$model_id"]=32768 ;;
            esac
        fi
        
        if [[ -n "$output_limit" && "$output_limit" =~ ^[0-9]+$ ]]; then
            MODEL_OUTPUT_LIMIT["$model_id"]="$output_limit"
        else
            # Category-based defaults
            case "$category" in
                coding)       MODEL_OUTPUT_LIMIT["$model_id"]=16384 ;;
                vision)       MODEL_OUTPUT_LIMIT["$model_id"]=4096 ;;
                *)            MODEL_OUTPUT_LIMIT["$model_id"]=8192 ;;
            esac
        fi
    done < "$MODELS_CONF"
}

# -----------------------------------------------------------------------------
# Model Selection Functions
# -----------------------------------------------------------------------------

# Associative arrays for model selection (requires bash 4+)
if [[ "$BASH_SUPPORTS_ASSOC_ARRAYS" == true ]]; then
    declare -A MODEL_SELECTED
    declare -a MODEL_ORDER
    declare -A MODEL_INFO
fi

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
    
    print_banner "Select GGUF Models to Download"

    echo -e "${DIM}★ = already downloaded${NC}"
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
    
    local selections gum_exit
    if [[ -n "$selected_csv" ]]; then
        selections=$(gum choose --no-limit \
            --cursor-prefix="$GUM_CURSOR_PREFIX" \
            --selected-prefix="$GUM_SELECTED_PREFIX" \
            --unselected-prefix="$GUM_UNSELECTED_PREFIX" \
            --cursor.foreground="212" \
            --selected.foreground="212" \
            --height=20 \
            --selected="$selected_csv" \
            "${options[@]}") && gum_exit=0 || gum_exit=$?
        check_user_interrupt $gum_exit
        if [[ -z "$selections" ]]; then
            echo
            print_status "Model selection cancelled"
            exit 0
        fi
    else
        selections=$(gum choose --no-limit \
            --cursor-prefix="$GUM_CURSOR_PREFIX" \
            --selected-prefix="$GUM_SELECTED_PREFIX" \
            --unselected-prefix="$GUM_UNSELECTED_PREFIX" \
            --cursor.foreground="212" \
            --selected.foreground="212" \
            --height=20 \
            "${options[@]}") && gum_exit=0 || gum_exit=$?
        check_user_interrupt $gum_exit
        if [[ -z "$selections" ]]; then
            echo
            print_status "Model selection cancelled"
            exit 0
        fi
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
        
        # For vision models, still check/offer mmproj download if missing
        if [[ "$category" == "vision" ]]; then
            if detect_mmproj "$output_path" "$MODELS_DIR" >/dev/null 2>&1; then
                print_status "mmproj file already exists"
            else
                local mmproj_mode="${NON_INTERACTIVE:-false}"
                handle_vision_model_mmproj "$hf_repo" "$MODELS_DIR" "$mmproj_mode"
            fi
        fi
        
        return 0
    fi
    
    # Create models directory
    mkdir -p "$MODELS_DIR"
    
    echo
    echo -e "${CYAN}${BOLD}Downloading: $model_id${NC}"
    echo
    echo -e "  ${BOLD}File:${NC}        $gguf_file"
    echo -e "  ${BOLD}Size:${NC}        ~$size"
    echo -e "  ${BOLD}Source:${NC}      huggingface.co/$hf_repo"
    echo
    
    # Get expected file size from HuggingFace API (for progress %)
    local expected_bytes=""
    if command -v jq &>/dev/null; then
        expected_bytes=$(curl -sf "https://huggingface.co/api/models/$hf_repo/tree/main" 2>/dev/null | \
            jq -r ".[] | select(.path == \"$gguf_file\") | .size" 2>/dev/null || echo)
    fi
    
    # Download using huggingface-cli (preferred) or curl (fallback)
    if command -v huggingface-cli &>/dev/null; then
        start_download_spinner "Downloading with huggingface-cli" "$output_path" "$expected_bytes"
        
        huggingface-cli download "$hf_repo" "$gguf_file" \
            --local-dir "$MODELS_DIR" \
            --local-dir-use-symlinks False \
            --quiet 2>/dev/null
        local dl_status=$?
        
        stop_spinner
        
        # huggingface-cli may create nested directories, move file if needed
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            : # File is where we expect
        elif [[ -f "$MODELS_DIR/$hf_repo/$gguf_file" ]]; then
            mv "$MODELS_DIR/$hf_repo/$gguf_file" "$output_path"
            rm -rf "${MODELS_DIR:?}/${hf_repo%%/*}" 2>/dev/null || true
        fi
        
        if [[ $dl_status -ne 0 ]]; then
            print_error "Download failed"
            return 1
        fi
    else
        local url="https://huggingface.co/$hf_repo/resolve/main/$gguf_file"
        start_download_spinner "Downloading with curl" "$output_path" "$expected_bytes"
        
        curl -fL \
            --connect-timeout 30 \
            --retry 3 \
            --retry-delay 5 \
            --retry-connrefused \
            -C - \
            -o "$output_path" "$url" 2>/dev/null
        local dl_status=$?
        
        stop_spinner
        
        if [[ $dl_status -ne 0 ]]; then
            print_error "Download failed"
            rm -f "$output_path"
            return 1
        fi
    fi
    
    # Verify download
    if [[ -f "$output_path" ]]; then
        local actual_size
        actual_size=$(du -h "$output_path" | cut -f1)
        print_success "Downloaded: $model_id ($actual_size)"
        
        # Handle mmproj for vision models
        # Uses global NON_INTERACTIVE variable (set by setup scripts) or defaults to interactive
        if [[ "$category" == "vision" ]]; then
            local mmproj_mode="${NON_INTERACTIVE:-false}"
            handle_vision_model_mmproj "$hf_repo" "$MODELS_DIR" "$mmproj_mode"
        fi
    else
        print_error "Download failed - file not found"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Display Name Generation
# -----------------------------------------------------------------------------

# Generate a display name for models not in metadata
# Usage: generate_display_name "qwen2.5-coder:7b" -> "Qwen2.5-coder 7B"
generate_display_name() {
    local model="$1"
    local base_name size_tag
    
    base_name="${model%%:*}"
    size_tag="${model##*:}"
    base_name="${base_name^}"  # Capitalize first letter
    size_tag="${size_tag^^}"   # Uppercase size tag
    
    echo "$base_name $size_tag"
}

# -----------------------------------------------------------------------------
# GGUF Model Verification
# -----------------------------------------------------------------------------

# Verify a GGUF model file is valid
# Usage: verify_gguf_model "/path/to/model.gguf"
# Returns: 0 if valid, 1 if invalid
# Outputs: Status message with checkmark/crossmark
verify_gguf_model() {
    local model_path="$1"
    local model_name
    model_name=$(basename "$model_path")
    
    if [[ ! -f "$model_path" ]]; then
        echo -e "  $CROSSMARK $model_name - file not found"
        return 1
    fi
    
    if [[ ! -r "$model_path" ]]; then
        echo -e "  $CROSSMARK $model_name - file not readable"
        return 1
    fi
    
    local file_size
    file_size=$(stat -c%s "$model_path" 2>/dev/null || stat -f%z "$model_path" 2>/dev/null)
    if [[ "$file_size" -lt 1048576 ]]; then
        local size_display
        size_display=$(numfmt --to=iec "$file_size" 2>/dev/null || echo "${file_size}B")
        echo -e "  $CROSSMARK $model_name - file too small ($size_display)"
        return 1
    fi
    
    local magic
    magic=$(head -c 4 "$model_path" 2>/dev/null | tr -d '\0')
    if [[ "$magic" != "GGUF" ]]; then
        echo -e "  $CROSSMARK $model_name - invalid GGUF format (magic: $magic)"
        return 1
    fi
    
    local size_human
    size_human=$(du -h "$model_path" | cut -f1)
    
    echo -e "  $CHECKMARK $model_name ($size_human) - valid GGUF"
    return 0
}

# -----------------------------------------------------------------------------
# Dependency Checking
# -----------------------------------------------------------------------------

# Check if a command exists and print status
# Usage: check_dependency "name" "command" [required]
# Example: check_dependency "git" "git" true
check_dependency() {
    local name="$1"
    local cmd="$2"
    local required="${3:-false}"
    local version_info=""
    
    # Pad name for alignment (20 chars)
    local padded_name
    padded_name=$(printf "%-18s" "$name")
    
    if command -v "$cmd" &>/dev/null; then
        echo -e "  $CHECKMARK $padded_name installed"
        return 0
    else
        echo -e "  $CROSSMARK $padded_name not installed"
        if [[ "$required" == "true" ]]; then
            return 1
        fi
        return 0
    fi
}

# -----------------------------------------------------------------------------
# Git Repository Management
# -----------------------------------------------------------------------------

# Clone or update a git repository
# Usage: clone_or_update_repo "url" "target_dir" [force_reclone]
# Returns: 0 on success, 1 on failure
clone_or_update_repo() {
    local repo_url="$1"
    local target_dir="$2"
    local force_reclone="${3:-false}"
    
    if [[ -d "$target_dir" ]]; then
        if [[ "$force_reclone" == "true" ]]; then
            print_status "Force rebuild requested, removing existing directory..."
            rm -rf "$target_dir"
        else
            print_status "Repository exists, pulling latest..."
            local original_dir
            original_dir=$(pwd)
            cd "$target_dir" || return 1
            if git rev-parse --git-dir &>/dev/null; then
                git pull 2>/dev/null || print_warning "Failed to pull latest (continuing with existing)"
            else
                print_warning "Not a valid git repository, will re-clone"
                cd "$original_dir" || return 1
                rm -rf "$target_dir"
            fi
            cd "$original_dir" || return 1
        fi
    fi
    
    if [[ ! -d "$target_dir" ]]; then
        print_status "Cloning repository..."
        if ! git clone --depth 1 "$repo_url" "$target_dir"; then
            print_error "Failed to clone repository"
            echo "Check your network connection and try again"
            return 1
        fi
    fi
    
    print_success "Repository ready"
    return 0
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
  "instructions": [
    "CONTRIBUTING.md",
    "docs/*.md"
  ],
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
# Model Size Parsing
# -----------------------------------------------------------------------------

# Parse size string to MB for comparison (e.g., "20GB" -> 20000, "500MB" -> 500, "0.4GB" -> 400)
parse_size_mb() {
    local size="$1"
    local result=0
    
    # Handle GB with decimals (e.g., "0.4GB", "2.5GB", "20GB")
    if [[ "$size" =~ ^([0-9]+)\.([0-9]+)GB$ ]]; then
        local whole="${BASH_REMATCH[1]}"
        local frac="${BASH_REMATCH[2]}"
        # Pad or truncate fraction to 1 digit and multiply
        frac="${frac:0:1}"
        result=$(( whole * 1000 + frac * 100 ))
    elif [[ "$size" =~ ^([0-9]+)GB$ ]]; then
        result=$(( BASH_REMATCH[1] * 1000 ))
    elif [[ "$size" =~ ^([0-9]+)\.([0-9]+)MB$ ]]; then
        result="${BASH_REMATCH[1]}"
    elif [[ "$size" =~ ^([0-9]+)MB$ ]]; then
        result="${BASH_REMATCH[1]}"
    fi
    
    # Ensure we always return a valid number
    if [[ ! "$result" =~ ^[0-9]+$ ]]; then
        result=0
    fi
    echo "$result"
}

# Category priority for model selection (best model for daily use)
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

# Pick the best model for daily use (highest priority category, largest size)
pick_example_model() {
    local example_model=""
    local example_priority=-1
    local example_size=0
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            local priority
            priority=$(get_category_priority "$category")
            local size_mb
            size_mb=$(parse_size_mb "$size")
            
            # Pick this model if: higher priority category, OR same priority but larger
            if [[ $priority -gt $example_priority ]] || \
               [[ $priority -eq $example_priority && $size_mb -gt $example_size ]]; then
                example_model="$model"
                example_priority=$priority
                example_size=$size_mb
            fi
        fi
    done
    
    echo "$example_model"
}

# Pick the smallest downloaded model (fastest for quick test)
pick_test_model() {
    local test_model=""
    local test_size=999999
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            local size_mb
            size_mb=$(parse_size_mb "$size")
            
            if [[ $size_mb -lt $test_size ]]; then
                test_model="$model"
                test_size=$size_mb
            fi
        fi
    done
    
    echo "$test_model"
}

# -----------------------------------------------------------------------------
# Inference Test
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
    
    # Extra environment variables (e.g., HSA_OVERRIDE_GFX_VERSION for ROCm)
    local extra_env="${4:-}"
    
    # Scale timeouts based on model size
    local server_timeout=60
    local inference_timeout=60
    
    if [[ $model_size_mb -gt 15000 ]]; then
        server_timeout=180
        inference_timeout=180
    elif [[ $model_size_mb -gt 8000 ]]; then
        server_timeout=120
        inference_timeout=120
    elif [[ $model_size_mb -gt 4000 ]]; then
        server_timeout=90
        inference_timeout=90
    fi
    
    echo
    print_header "Running Inference Test"
    echo
    print_status "Testing $model_id..."
    
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
    
    if [[ -n "$extra_env" ]]; then
        # shellcheck disable=SC2086  # Word splitting is intentional for env vars
        env $extra_env "$server_binary" \
            -m "$model_path" \
            --host 127.0.0.1 \
            --port "$test_port" \
            -c 2048 \
            -ngl 99 \
            > "$server_log" 2>&1 &
    else
        "$server_binary" \
            -m "$model_path" \
            --host 127.0.0.1 \
            --port "$test_port" \
            -c 2048 \
            -ngl 99 \
            > "$server_log" 2>&1 &
    fi
    server_pid=$!
    
    # Wait for server to be ready
    local waited=0
    local ready=false
    
    while [[ $waited -lt $server_timeout ]]; do
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
    
    # Check response
    if [[ $curl_exit -eq 0 && -n "$response" ]]; then
        local content
        local reasoning_content
        content=$(echo "$response" | jq -r '.choices[0].message.content // empty' 2>/dev/null)
        reasoning_content=$(echo "$response" | jq -r '.choices[0].message.reasoning_content // empty' 2>/dev/null)
        
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

# -----------------------------------------------------------------------------
# Orphan Model Cleanup
# -----------------------------------------------------------------------------

check_orphan_models() {
    local script_dir="$1"
    local non_interactive="${2:-false}"
    
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
        
        # Skip mmproj files (companion files for vision models, not main models)
        [[ "$filename" == mmproj-* ]] && continue
        
        if [[ -z "${known_files[$filename]:-}" && -z "${whitelisted_files[$filename]:-}" ]]; then
            orphan_files+=("$filename")
            local fsize
            if [[ "$(uname -s)" == "Darwin" ]]; then
                fsize=$(stat -f%z "$gguf" 2>/dev/null || echo 0)
            else
                fsize=$(stat -c%s "$gguf" 2>/dev/null || echo 0)
            fi
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
        echo -e "    ${YELLOW}o${NC} $fname ${DIM}($fsize_human)${NC}"
    done
    echo
    
    if [[ "$non_interactive" == false ]]; then
        echo -e "${DIM}These files take up disk space but aren't tracked.${NC}"
        echo
        
        local cleanup_choice="" gum_exit
        if [[ "$HAS_GUM" == true ]]; then
            cleanup_choice=$(gum choose --cursor-prefix="$GUM_RADIO_CURSOR" --selected-prefix="$GUM_RADIO_SELECTED" \
                --cursor.foreground="212" \
                "Run cleanup now" \
                "Skip for now") && gum_exit=0 || gum_exit=$?
            check_user_interrupt $gum_exit
            [[ -z "$cleanup_choice" ]] && cleanup_choice="Skip for now"
        else
            read -r -p "Run cleanup? [y/N] " reply
            [[ "$reply" =~ ^[Yy]$ ]] && cleanup_choice="Run cleanup now"
        fi
        
        if [[ "$cleanup_choice" == "Run cleanup now" ]]; then
            echo
            "$script_dir/download-model.sh" --cleanup
        else
            echo -e "${DIM}Run './download-model.sh --cleanup' later to manage these files${NC}"
        fi
    else
        echo -e "${DIM}Run './download-model.sh --cleanup' to manage orphan models${NC}"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Platform Detection
# -----------------------------------------------------------------------------

IS_MACOS=false
IS_LINUX=false

detect_platform() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        IS_MACOS=true
    elif [[ "$(uname -s)" == "Linux" ]]; then
        IS_LINUX=true
    fi
}

# Run platform detection on source
detect_platform

# -----------------------------------------------------------------------------
# GPU Vendor Detection (Linux)
# -----------------------------------------------------------------------------

# Detected GPU vendor (cached after first call)
DETECTED_GPU_VENDOR=""

# Detect GPU vendor on Linux
# Returns: nvidia, amd, or cpu
# Usage: vendor=$(detect_gpu_vendor)
detect_gpu_vendor() {
    # Return cached value if already detected
    if [[ -n "$DETECTED_GPU_VENDOR" ]]; then
        echo "$DETECTED_GPU_VENDOR"
        return 0
    fi
    
    if [[ "$IS_LINUX" != true ]]; then
        DETECTED_GPU_VENDOR="cpu"
        echo "$DETECTED_GPU_VENDOR"
        return 0
    fi
    
    # Check for NVIDIA first (nvidia-smi is installed with drivers)
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        DETECTED_GPU_VENDOR="nvidia"
    # Check for AMD (ROCm/HIP)
    elif [[ -e /dev/kfd ]] && command -v hipconfig &>/dev/null; then
        DETECTED_GPU_VENDOR="amd"
    # Fallback to CPU-only
    else
        DETECTED_GPU_VENDOR="cpu"
    fi
    
    echo "$DETECTED_GPU_VENDOR"
}

# Find nvcc compiler (CUDA toolkit)
# Returns: path to nvcc, or empty string if not found
# Usage: nvcc_path=$(detect_nvcc)
detect_nvcc() {
    # Check PATH first (covers most distros when properly installed)
    if command -v nvcc &>/dev/null; then
        command -v nvcc
        return 0
    fi
    
    # Check common install locations
    local cuda_paths=(
        "/usr/local/cuda/bin/nvcc"
        "/opt/cuda/bin/nvcc"
        "/usr/bin/nvcc"
    )
    
    for path in "${cuda_paths[@]}"; do
        if [[ -x "$path" ]]; then
            echo "$path"
            return 0
        fi
    done
    
    return 1
}

# Get NVIDIA GPU info via nvidia-smi
# Returns: gpu_name|vram_gb
# Usage: IFS='|' read -r gpu_name vram_gb <<< "$(detect_nvidia_gpu)"
detect_nvidia_gpu() {
    if ! command -v nvidia-smi &>/dev/null; then
        echo "Unknown NVIDIA GPU|0"
        return 1
    fi
    
    local gpu_name vram_mb vram_gb
    gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | xargs)
    vram_mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)
    
    if [[ -n "$vram_mb" && "$vram_mb" =~ ^[0-9]+$ ]]; then
        vram_gb=$((vram_mb / 1024))
    else
        vram_gb=0
    fi
    
    echo "${gpu_name:-Unknown NVIDIA GPU}|${vram_gb}"
}

# Get NVIDIA VRAM in GB
# Usage: vram=$(get_nvidia_vram_gb)
get_nvidia_vram_gb() {
    local vram_mb
    vram_mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)
    
    if [[ -n "$vram_mb" && "$vram_mb" =~ ^[0-9]+$ ]]; then
        echo $((vram_mb / 1024))
    else
        echo "0"
    fi
}

# Get CMake GPU flags for building llama.cpp
# Usage: cmake_flags=$(get_cmake_gpu_flags "$vendor" "$gpu_target")
# Arguments:
#   vendor: nvidia, amd, or cpu
#   gpu_target: AMD GPU target (e.g., gfx1100) - only used for AMD
get_cmake_gpu_flags() {
    local vendor="$1"
    local gpu_target="${2:-}"
    
    case "$vendor" in
        nvidia)
            echo "-DGGML_CUDA=ON"
            ;;
        amd)
            if [[ -n "$gpu_target" ]]; then
                echo "-DGGML_HIP=ON -DGPU_TARGETS=$gpu_target"
            else
                echo "-DGGML_HIP=ON"
            fi
            ;;
        *)
            # CPU-only build, no special flags
            echo ""
            ;;
    esac
}

# Get GPU vendor display name
# Usage: name=$(get_gpu_vendor_display_name "$vendor")
get_gpu_vendor_display_name() {
    local vendor="$1"
    case "$vendor" in
        nvidia) echo "NVIDIA (CUDA)" ;;
        amd)    echo "AMD (ROCm/HIP)" ;;
        cpu)    echo "CPU-only" ;;
        *)      echo "Unknown" ;;
    esac
}

# -----------------------------------------------------------------------------
# Dependency Notice for Uninstall Scripts
# -----------------------------------------------------------------------------

# Detect and show dependencies that were installed but won't be removed
# Usage: show_dependency_notice
#
# This function detects common dependencies and shows a notice explaining
# they are kept because other applications may use them.
show_dependency_notice() {
    local -a installed_deps=()
    
    # Detect dependencies based on platform
    if [[ "$IS_LINUX" == true ]]; then
        # llama.cpp Linux (ROCm) dependencies
        command -v hipcc &>/dev/null && installed_deps+=("ROCm/HIP")
        command -v cmake &>/dev/null && installed_deps+=("cmake")
        command -v make &>/dev/null && installed_deps+=("make")
        command -v git &>/dev/null && installed_deps+=("git")
        command -v gum &>/dev/null && installed_deps+=("gum")
        command -v curl &>/dev/null && installed_deps+=("curl")
        command -v jq &>/dev/null && installed_deps+=("jq")
    fi
    
    if [[ "$IS_MACOS" == true ]]; then
        # llama.cpp macOS (Metal) dependencies
        command -v brew &>/dev/null && installed_deps+=("Homebrew")
        xcode-select -p &>/dev/null && installed_deps+=("Xcode Command Line Tools")
        command -v cmake &>/dev/null && installed_deps+=("cmake")
        command -v git &>/dev/null && installed_deps+=("git")
        command -v gum &>/dev/null && installed_deps+=("gum")
        command -v curl &>/dev/null && installed_deps+=("curl")
        command -v jq &>/dev/null && installed_deps+=("jq")
    fi
    
    # If no dependencies found, nothing to show
    if [[ ${#installed_deps[@]} -eq 0 ]]; then
        return 0
    fi
    
    # Show notice
    echo
    echo -e "${YELLOW}${BOLD}Dependencies not removed:${NC}"
    for dep in "${installed_deps[@]}"; do
        echo -e "  ${DIM}○ ${dep}${NC}"
    done
    echo
    echo -e "${DIM}These are kept because they may be used by other applications.${NC}"
    echo -e "${DIM}To remove them manually:${NC}"
    
    if [[ "$IS_LINUX" == true ]]; then
        echo -e "${DIM}  # ROCm: Follow AMD's uninstall guide${NC}"
        echo -e "${DIM}  sudo pacman -R cmake make gum jq  # Arch${NC}"
        echo -e "${DIM}  sudo apt remove cmake make gum jq  # Ubuntu${NC}"
    fi
    
    if [[ "$IS_MACOS" == true ]]; then
        echo -e "${DIM}  brew uninstall gum cmake jq${NC}"
        echo -e "${DIM}  # Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)\"${NC}"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Model Entry Validation
# -----------------------------------------------------------------------------

# Validate a models.conf entry
# Usage: validate_model_entry <category> <model_id> <hf_repo> <gguf_file> <size> [line_num]
# Returns 0 if valid, 1 if invalid (with warning printed)
validate_model_entry() {
    local category="$1"
    local model_id="$2"
    local hf_repo="$3"
    local gguf_file="$4"
    local size="$5"
    local line_num="${6:-}"
    
    local line_info=""
    [[ -n "$line_num" ]] && line_info=" (line $line_num)"
    
    # Required fields must not be empty
    if [[ -z "$category" || -z "$model_id" || -z "$hf_repo" || -z "$gguf_file" ]]; then
        print_warning "Skipping invalid entry${line_info}: missing required fields"
        return 1
    fi
    
    # model_id should be alphanumeric with hyphens/underscores/dots
    if [[ ! "$model_id" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        print_warning "Skipping invalid entry${line_info}: model_id contains invalid characters: $model_id"
        return 1
    fi
    
    # gguf_file must end in .gguf
    if [[ ! "$gguf_file" =~ \.gguf$ ]]; then
        print_warning "Skipping invalid entry${line_info}: gguf_file must end in .gguf: $gguf_file"
        return 1
    fi
    
    # gguf_file should not contain path traversal
    if [[ "$gguf_file" =~ \.\. || "$gguf_file" =~ ^/ ]]; then
        print_warning "Skipping invalid entry${line_info}: gguf_file contains invalid path: $gguf_file"
        return 1
    fi
    
    # hf_repo should look like owner/repo
    if [[ ! "$hf_repo" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]]; then
        print_warning "Skipping invalid entry${line_info}: hf_repo format invalid: $hf_repo"
        return 1
    fi
    
    return 0
}

# -----------------------------------------------------------------------------
# Cross-Platform File Size
# -----------------------------------------------------------------------------

# Get file size in bytes (cross-platform)
# Usage: size=$(get_file_size "/path/to/file")
get_file_size() {
    local file="$1"
    if [[ "$IS_MACOS" == true ]]; then
        stat -f%z "$file" 2>/dev/null
    else
        stat -c%s "$file" 2>/dev/null
    fi
}

# -----------------------------------------------------------------------------
# OpenCode Config Backup/Restore
# -----------------------------------------------------------------------------

# List available config backups (newest first)
# Usage: backups=$(list_config_backups "/path/to/config.json")
list_config_backups() {
    local config_file="${1:-$OPENCODE_CONFIG}"
    local backup_dir
    backup_dir="$(dirname "$config_file")"
    local config_name
    config_name="$(basename "$config_file")"
    local backup_pattern="${config_name}.backup.*"
    
    # Find all backups sorted by date (newest first)
    find "$backup_dir" -maxdepth 1 -name "$backup_pattern" -print 2>/dev/null | sort -r
}

# Restore a config backup
# Usage: restore_config_backup "/path/to/backup.json" "/path/to/config.json"
restore_config_backup() {
    local backup_file="$1"
    local config_file="${2:-$OPENCODE_CONFIG}"
    
    if [[ ! -f "$backup_file" ]]; then
        print_error "Backup file not found: $backup_file"
        return 1
    fi
    
    # Validate it's valid JSON
    if command -v jq &>/dev/null; then
        if ! jq empty "$backup_file" 2>/dev/null; then
            print_error "Backup file is not valid JSON: $backup_file"
            return 1
        fi
    fi
    
    # Create a backup of current config before restoring
    if [[ -f "$config_file" ]]; then
        local pre_restore_backup
        pre_restore_backup="$config_file.pre-restore.$(date +%Y%m%d_%H%M%S)"
        cp "$config_file" "$pre_restore_backup"
        print_status "Backed up current config to: $pre_restore_backup"
    fi
    
    # Restore the backup
    cp "$backup_file" "$config_file"
    print_success "Restored config from: $backup_file"
}

# Create a backup of the config file
# Usage: backup_config "/path/to/config.json"
backup_config() {
    local config_file="${1:-$OPENCODE_CONFIG}"
    
    if [[ -f "$config_file" ]]; then
        local backup_file
        backup_file="$config_file.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$config_file" "$backup_file"
        print_status "Backed up existing config to: $backup_file"
        echo "$backup_file"
    fi
}

# Interactive restore handler
# Usage: handle_config_restore "/path/to/config.json" [--latest]
handle_config_restore() {
    local config_file="${1:-$OPENCODE_CONFIG}"
    local restore_latest="${2:-false}"
    local backup_dir
    backup_dir="$(dirname "$config_file")"
    
    echo
    echo -e "${CYAN}${BOLD}Restore OpenCode Configuration${NC}"
    echo
    
    # Get list of backups into array
    local -a backups=()
    while IFS= read -r file; do
        [[ -n "$file" ]] && backups+=("$file")
    done < <(list_config_backups "$config_file")
    
    if [[ ${#backups[@]} -eq 0 ]]; then
        print_warning "No backup files found in: $backup_dir"
        return 0
    fi
    
    # If --latest, use the first (newest) backup
    if [[ "$restore_latest" == true || "$restore_latest" == "--latest" ]]; then
        local latest="${backups[0]}"
        print_status "Restoring latest backup..."
        restore_config_backup "$latest" "$config_file"
        return 0
    fi
    
    # Interactive mode - list backups and let user choose
    print_status "Available backups (newest first):"
    echo
    
    local i=1
    for backup in "${backups[@]}"; do
        local bname
        bname=$(basename "$backup")
        # Extract timestamp from filename
        local timestamp="${bname#*.backup.}"
        # Format: YYYYMMDD_HHMMSS -> YYYY-MM-DD HH:MM:SS
        local formatted_date=""
        if [[ "$timestamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
            formatted_date="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
        else
            formatted_date="$timestamp"
        fi
        echo "  $i) $formatted_date"
        ((i++))
    done
    
    echo
    echo "  0) Cancel"
    echo
    
    local choice=""
    if [[ "$HAS_GUM" == true ]]; then
        # Build options for gum
        local gum_options=()
        for gum_backup in "${backups[@]}"; do
            local gum_bname gum_timestamp gum_formatted
            gum_bname=$(basename "$gum_backup")
            gum_timestamp="${gum_bname#*.backup.}"
            if [[ "$gum_timestamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
                gum_formatted="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
            else
                gum_formatted="$gum_timestamp"
            fi
            gum_options+=("$gum_formatted")
        done
        gum_options+=("Cancel")
        
        local selected gum_exit
        selected=$(gum choose --cursor-prefix="$GUM_RADIO_CURSOR" --selected-prefix="$GUM_RADIO_SELECTED" \
            --cursor.foreground="212" \
            "${gum_options[@]}") && gum_exit=0 || gum_exit=$?
        check_user_interrupt $gum_exit
        
        if [[ -z "$selected" || "$selected" == "Cancel" ]]; then
            print_status "Restore cancelled"
            return 0
        fi
        
        # Find matching backup
        local idx
        for idx in "${!backups[@]}"; do
            local match_bname match_timestamp match_formatted
            match_bname=$(basename "${backups[$idx]}")
            match_timestamp="${match_bname#*.backup.}"
            if [[ "$match_timestamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
                match_formatted="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
            else
                match_formatted="$match_timestamp"
            fi
            if [[ "$selected" == "$match_formatted" ]]; then
                choice=$((idx + 1))
                break
            fi
        done
    else
        read -rp "Select backup to restore [0-${#backups[@]}]: " choice
    fi
    
    # Validate input
    if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
        print_error "Invalid selection"
        return 1
    fi
    
    if [[ "$choice" -eq 0 ]]; then
        print_status "Restore cancelled"
        return 0
    fi
    
    if [[ "$choice" -lt 1 || "$choice" -gt ${#backups[@]} ]]; then
        print_error "Invalid selection: $choice"
        return 1
    fi
    
    # Restore selected backup (array is 0-indexed, selection is 1-indexed)
    local selected_backup="${backups[$((choice-1))]}"
    echo
    restore_config_backup "$selected_backup" "$config_file"
}

# -----------------------------------------------------------------------------
# Agent Directory Management
# -----------------------------------------------------------------------------

# Sync agent directory to OpenCode config
# Usage: sync_agents <script_dir> <target_dir> <non_interactive> [reset_mode]
#
# script_dir: Directory containing the source agent/ folder
# target_dir: OpenCode config directory (usually ~/.config/opencode)
# non_interactive: "true" to skip prompts, "false" for interactive mode
# reset_mode: "true" to force reset to default (used with --reset-agents flag)
#
# Syncs:
#   agent/AGENTS.md -> ~/.config/opencode/AGENTS.md
#   agent/plan.md   -> ~/.config/opencode/agent/plan.md
#   agent/review.md -> ~/.config/opencode/agent/review.md
#   agent/debug.md  -> ~/.config/opencode/agent/debug.md
#
# Returns: 0 if files were created/updated, 1 if skipped
sync_agents() {
    local script_dir="$1"
    local target_dir="$2"
    local non_interactive="$3"
    local reset_mode="${4:-false}"
    
    local source_dir="$script_dir/agent"
    local agent_target_dir="$target_dir/agent"
    
    # Check source exists
    if [[ ! -d "$source_dir" ]]; then
        print_warning "agent/ directory not found in: $script_dir"
        return 1
    fi
    
    # Files to sync
    local -a main_files=("AGENTS.md")
    local -a agent_files=("plan.md" "review.md" "debug.md")
    
    # Reset mode - copy all with backups
    if [[ "$reset_mode" == "true" ]]; then
        local backup_timestamp
        backup_timestamp="$(date +%Y%m%d_%H%M%S)"
        
        # Sync AGENTS.md to target root
        for file in "${main_files[@]}"; do
            local src="$source_dir/$file"
            local dst="$target_dir/$file"
            if [[ -f "$src" ]]; then
                if [[ -f "$dst" ]]; then
                    cp "$dst" "$dst.backup.$backup_timestamp"
                    print_status "Backed up $file"
                fi
                mkdir -p "$target_dir"
                cp "$src" "$dst"
            fi
        done
        
        # Sync agent files to agent/ subdirectory
        for file in "${agent_files[@]}"; do
            local src="$source_dir/$file"
            local dst="$agent_target_dir/$file"
            if [[ -f "$src" ]]; then
                if [[ -f "$dst" ]]; then
                    cp "$dst" "$dst.backup.$backup_timestamp"
                    print_status "Backed up agent/$file"
                fi
                mkdir -p "$agent_target_dir"
                cp "$src" "$dst"
            fi
        done
        
        print_success "Agent files reset to defaults"
        print_status "  AGENTS.md -> $target_dir/AGENTS.md"
        print_status "  agent/   -> $agent_target_dir/"
        return 0
    fi
    
    # Check if any target files exist
    local has_existing=false
    local has_changes=false
    
    for file in "${main_files[@]}"; do
        local src="$source_dir/$file"
        local dst="$target_dir/$file"
        if [[ -f "$dst" ]]; then
            has_existing=true
            if ! diff -q "$src" "$dst" &>/dev/null 2>&1; then
                has_changes=true
            fi
        fi
    done
    
    for file in "${agent_files[@]}"; do
        local src="$source_dir/$file"
        local dst="$agent_target_dir/$file"
        if [[ -f "$dst" ]]; then
            has_existing=true
            if ! diff -q "$src" "$dst" &>/dev/null 2>&1; then
                has_changes=true
            fi
        fi
    done
    
    # If files exist but no changes, we're done
    if [[ "$has_existing" == true && "$has_changes" == false ]]; then
        print_status "Agent files already up to date"
        return 0
    fi
    
    # If files exist with changes, prompt user
    if [[ "$has_existing" == true && "$has_changes" == true ]]; then
        print_warning "Agent files already exist with modifications"
        
        if [[ "$non_interactive" == "false" && "$HAS_GUM" == true ]]; then
            echo
            print_status "How would you like to handle existing agent files?"
            echo
            
            local choice gum_exit
            choice=$(gum choose \
                "Skip - Keep existing files unchanged" \
                "Overwrite - Replace with defaults (backups created)" \
                "View diff - Show differences") && gum_exit=0 || gum_exit=$?
            check_user_interrupt $gum_exit
            [[ -z "$choice" ]] && choice="Skip"
            
            case "$choice" in
                "View diff"*)
                    echo
                    echo -e "${CYAN}${BOLD}Differences (your files vs defaults):${NC}"
                    echo
                    for file in "${main_files[@]}"; do
                        local src="$source_dir/$file"
                        local dst="$target_dir/$file"
                        if [[ -f "$dst" ]] && ! diff -q "$src" "$dst" &>/dev/null 2>&1; then
                            echo -e "${BOLD}=== $file ===${NC}"
                            diff --color=auto "$dst" "$src" || true
                            echo
                        fi
                    done
                    for file in "${agent_files[@]}"; do
                        local src="$source_dir/$file"
                        local dst="$agent_target_dir/$file"
                        if [[ -f "$dst" ]] && ! diff -q "$src" "$dst" &>/dev/null 2>&1; then
                            echo -e "${BOLD}=== agent/$file ===${NC}"
                            diff --color=auto "$dst" "$src" || true
                            echo
                        fi
                    done
                    
                    # Ask again after showing diff
                    local choice2 gum_exit2
                    choice2=$(gum choose \
                        "Skip - Keep existing files unchanged" \
                        "Overwrite - Replace with defaults (backups created)") && gum_exit2=0 || gum_exit2=$?
                    check_user_interrupt $gum_exit2
                    [[ -z "$choice2" ]] && choice2="Skip"
                    
                    if [[ "$choice2" == "Overwrite"* ]]; then
                        sync_agents "$script_dir" "$target_dir" "$non_interactive" "true"
                    else
                        print_status "Keeping existing agent files"
                    fi
                    return 0
                    ;;
                "Overwrite"*)
                    sync_agents "$script_dir" "$target_dir" "$non_interactive" "true"
                    return 0
                    ;;
                "Skip"*|"")
                    print_status "Keeping existing agent files"
                    return 0
                    ;;
            esac
        else
            print_status "Non-interactive mode: keeping existing agent files"
            print_status "Run setup.sh --reset-agents to reset to defaults"
            return 0
        fi
    else
        # No existing files - create all
        print_status "Setting up OpenCode agent files..."
        
        # Sync AGENTS.md to target root
        for file in "${main_files[@]}"; do
            local src="$source_dir/$file"
            if [[ -f "$src" ]]; then
                mkdir -p "$target_dir"
                cp "$src" "$target_dir/$file"
            fi
        done
        
        # Sync agent files to agent/ subdirectory
        for file in "${agent_files[@]}"; do
            local src="$source_dir/$file"
            if [[ -f "$src" ]]; then
                mkdir -p "$agent_target_dir"
                cp "$src" "$agent_target_dir/$file"
            fi
        done
        
        print_success "Agent files created:"
        print_status "  AGENTS.md -> $target_dir/AGENTS.md"
        print_status "  agent/   -> $agent_target_dir/"
        return 0
    fi
}



# -----------------------------------------------------------------------------
# OpenCode Config Management
# -----------------------------------------------------------------------------

# Handle OpenCode config creation/update with user choice
# Usage: handle_opencode_config <config_path> <sync_script_path> <non_interactive> <generate_config_callback>
# 
# The generate_config_callback should be a function that outputs the config JSON to stdout
# Returns: Always 0 (success) - skipping is not an error
#
# Example:
#   generate_my_config() { generate_opencode_config "${DOWNLOADED_MODELS[@]}"; }
#   handle_opencode_config "$OPENCODE_CONFIG" "$SCRIPT_DIR/sync-opencode.sh" "$NON_INTERACTIVE" generate_my_config
handle_opencode_config() {
    local config_path="$1"
    local sync_script="$2"
    local non_interactive="$3"
    local generate_callback="$4"
    
    if [[ -f "$config_path" ]]; then
        print_warning "OpenCode config already exists at: $config_path"
        
        if [[ "$non_interactive" == "false" ]]; then
            echo
            print_status "How would you like to handle the existing config?"
            echo
            
            local choice gum_exit
            choice=$(gum choose \
                "Merge - Add new models to existing config" \
                "Overwrite - Replace with new config (backup created)" \
                "Skip - Keep existing config unchanged") && gum_exit=0 || gum_exit=$?
            check_user_interrupt $gum_exit
            [[ -z "$choice" ]] && choice="Skip"
            
            case "$choice" in
                Merge*)
                    print_status "Merging new models into existing OpenCode config..."
                    "$sync_script" --merge
                    return 0
                    ;;
                Overwrite*)
                    local backup_file
                    backup_file="$config_path.backup.$(date +%Y%m%d_%H%M%S)"
                    cp "$config_path" "$backup_file"
                    print_status "Backed up existing config to: $backup_file"
                    mkdir -p "$(dirname "$config_path")"
                    $generate_callback > "$config_path"
                    print_success "OpenCode config created at: $config_path"
                    return 0
                    ;;
                Skip*|"")
                    print_status "Keeping existing OpenCode config"
                    return 0
                    ;;
            esac
        else
            print_status "Non-interactive mode: keeping existing config"
            print_status "Run sync-opencode.sh --merge to add new models"
            return 0
        fi
    else
        # No existing config - create new one
        print_status "Creating OpenCode configuration..."
        mkdir -p "$(dirname "$config_path")"
        $generate_callback > "$config_path"
        print_success "OpenCode config created at: $config_path"
        return 0
    fi
}

# -----------------------------------------------------------------------------
# Size Calculation Helpers
# -----------------------------------------------------------------------------

# Get human-readable directory size (e.g., "1.5G")
get_dir_size() {
    local dir="$1"
    if [[ -d "$dir" ]]; then
        du -sh "$dir" 2>/dev/null | cut -f1
    else
        echo "0"
    fi
}

# Get human-readable file size (e.g., "256M")
get_file_size_human() {
    local file="$1"
    if [[ -f "$file" ]]; then
        du -sh "$file" 2>/dev/null | cut -f1
    else
        echo "0"
    fi
}

# Get file size in bytes
get_file_size_bytes() {
    local file="$1"
    if [[ -f "$file" ]]; then
        stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# Parse size string to bytes (e.g., "4.5GB" -> bytes)
parse_size_bytes() {
    local size="$1"
    local mb
    mb=$(parse_size_mb "$size")
    echo $((mb * 1048576))
}

# =============================================================================
# Update Check Functions
# =============================================================================

# Cache location and settings
UPDATE_CHECK_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/llama-cpp-setup/update-check"
UPDATE_CHECK_MAX_AGE=86400  # 24 hours in seconds

# -----------------------------------------------------------------------------
# Cache Helpers
# -----------------------------------------------------------------------------

# Check if cache entry is fresh (< 24 hours old)
# Usage: is_update_cache_fresh "llama.cpp"
# Returns: 0 if fresh (skip check), 1 if stale (should check)
is_update_cache_fresh() {
    local component="$1"
    local cache_file="$UPDATE_CHECK_CACHE"
    
    [[ -f "$cache_file" ]] || return 1
    
    local entry cache_time now
    entry=$(grep "^${component}|" "$cache_file" 2>/dev/null) || return 1
    cache_time=$(echo "$entry" | cut -d'|' -f3)
    now=$(date +%s)
    
    [[ -n "$cache_time" ]] && (( now - cache_time < UPDATE_CHECK_MAX_AGE ))
}

# Get cached status for a component
# Usage: status=$(get_update_cache "llama.cpp")
# Returns: status string or empty
get_update_cache() {
    local component="$1"
    [[ -f "$UPDATE_CHECK_CACHE" ]] || return
    grep "^${component}|" "$UPDATE_CHECK_CACHE" 2>/dev/null | cut -d'|' -f2
}

# Save status to cache
# Usage: set_update_cache "llama.cpp" "5 commits behind"
set_update_cache() {
    local component="$1"
    local status="$2"
    local cache_file="$UPDATE_CHECK_CACHE"
    
    # Ensure cache directory exists
    mkdir -p "$(dirname "$cache_file")" 2>/dev/null || return
    
    # Remove old entry for this component
    if [[ -f "$cache_file" ]]; then
        grep -v "^${component}|" "$cache_file" > "${cache_file}.tmp" 2>/dev/null || true
        mv "${cache_file}.tmp" "$cache_file" 2>/dev/null || true
    fi
    
    # Add new entry: component|status|timestamp
    echo "${component}|${status}|$(date +%s)" >> "$cache_file" 2>/dev/null || true
}

# -----------------------------------------------------------------------------
# llama.cpp Update Check
# -----------------------------------------------------------------------------

# Check for llama.cpp updates (git commits behind upstream)
# Usage: update_msg=$(check_llama_cpp_updates "/path/to/llama.cpp")
# Returns: message string if updates available, empty if current or error
check_llama_cpp_updates() {
    local llama_dir="$1"
    
    # Use cache if fresh
    if is_update_cache_fresh "llama.cpp"; then
        local cached
        cached=$(get_update_cache "llama.cpp")
        [[ "$cached" != "current" ]] && echo "$cached"
        return 0
    fi
    
    # Must be a git repo
    [[ -d "$llama_dir/.git" ]] || return
    
    # Check if upstream is configured
    if ! (cd "$llama_dir" && git rev-parse --abbrev-ref "@{u}" &>/dev/null); then
        return  # No upstream configured, skip silently
    fi
    
    # Fetch with timeout (silent on failure)
    if ! (cd "$llama_dir" && timeout 5 git fetch --quiet 2>/dev/null); then
        return  # Network error, skip silently
    fi
    
    # Count commits behind
    local behind
    behind=$(cd "$llama_dir" && git rev-list --count HEAD.."@{u}" 2>/dev/null) || return
    
    if [[ "$behind" -gt 0 ]]; then
        set_update_cache "llama.cpp" "$behind commits behind"
        echo "$behind commits behind"
    else
        set_update_cache "llama.cpp" "current"
    fi
}

# -----------------------------------------------------------------------------
# Update Notification Display (with Gum UI)
# -----------------------------------------------------------------------------

# Show update notification with gum styling (or ASCII fallback)
# Usage: show_update_notification "llama.cpp" "5 commits behind" "./setup.sh --update"
show_update_notification() {
    local component="$1"
    local info="$2"
    local update_cmd="$3"
    
    echo
    
    if [[ "$HAS_GUM" == true ]]; then
        gum style \
            --border rounded \
            --border-foreground 220 \
            --padding "0 1" \
            --margin "0" \
            "$(gum style --foreground 220 --bold '📦 Update Available')" \
            "" \
            "$(gum style --bold "$component:") $info" \
            "$(gum style --faint "Run: $update_cmd")"
    else
        echo -e "${YELLOW}┌─ Update Available ─────────────────────────┐${NC}"
        echo -e "${YELLOW}│${NC} ${BOLD}$component:${NC} $info"
        echo -e "${YELLOW}│${NC} Run: ${DIM}$update_cmd${NC}"
        echo -e "${YELLOW}└─────────────────────────────────────────────┘${NC}"
    fi
}

# -----------------------------------------------------------------------------
# Vision Model Support
# -----------------------------------------------------------------------------

# Check if a model is a vision model (requires mmproj)
# Usage: is_vision_model <gguf_path_or_basename>
# Returns: 0 if vision model, 1 otherwise
is_vision_model() {
    local gguf_path="$1"
    local model_basename
    model_basename=$(basename "$gguf_path")
    
    # Check models.conf for category
    if [[ -f "$MODELS_CONF" ]]; then
        while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
            [[ "$category" =~ ^[[:space:]]*# ]] && continue
            [[ "$category" =~ ^ALIAS: ]] && continue
            [[ -z "$category" ]] && continue
            
            # Trim
            gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
            gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
            category="${category#"${category%%[![:space:]]*}"}"
            category="${category%"${category##*[![:space:]]}"}"
            
            if [[ "$gguf_file" == "$model_basename" && "$category" == "vision" ]]; then
                return 0
            fi
        done < "$MODELS_CONF"
    fi
    
    # Also detect by filename pattern (e.g., Qwen3VL, llava, etc.)
    if [[ "$model_basename" =~ [Vv][Ll][-_]?[0-9] ]] || \
       [[ "$model_basename" =~ [Ll]lava ]] || \
       [[ "$model_basename" =~ [Mm]iniCPM-V ]] || \
       [[ "$model_basename" =~ [Pp]hi-3.*[Vv]ision ]]; then
        return 0
    fi
    
    return 1
}

# Detect mmproj file for a vision model
# Usage: detect_mmproj <gguf_path> <models_dir>
# Returns: path to mmproj file, or empty string if not found
detect_mmproj() {
    local gguf_path="$1"
    local models_dir="$2"
    local model_basename
    model_basename=$(basename "$gguf_path")
    
    # Extract model name pattern from the main model file
    # e.g., "Qwen3VL-8B-Instruct-Q8_0.gguf" -> "Qwen3VL-8B-Instruct"
    local model_base="${model_basename%.gguf}"
    # Remove quantization suffix (Q4_K_M, Q8_0, etc.)
    model_base=$(echo "$model_base" | sed -E 's/[-_]Q[0-9]+[_A-Za-z0-9]*$//')
    
    # Look for mmproj files (prefer F16 over Q8_0 for quality)
    local mmproj_patterns=(
        "mmproj-${model_base}-F16.gguf"
        "mmproj-${model_base}-f16.gguf"
        "mmproj-${model_base}-Q8_0.gguf"
        "mmproj-${model_base}-q8_0.gguf"
        "mmproj-${model_base}.gguf"
    )
    
    for pattern in "${mmproj_patterns[@]}"; do
        if [[ -f "$models_dir/$pattern" ]]; then
            echo "$models_dir/$pattern"
            return 0
        fi
    done
    
    # Try glob pattern as fallback (any mmproj with similar name)
    local found
    found=$(find "$models_dir" -maxdepth 1 -name "mmproj-*${model_base}*" -type f 2>/dev/null | head -1)
    if [[ -n "$found" ]]; then
        echo "$found"
        return 0
    fi
    
    return 1
}

# Get mmproj files from a HuggingFace API response
# Usage: get_mmproj_files <json_response>
# Returns: pipe-separated list of "filename|size" for mmproj files
get_mmproj_files() {
    local response="$1"
    echo "$response" | jq -r '.[] | select(.path | startswith("mmproj-")) | "\(.path)|\(.size)"'
}

# Download mmproj files for a vision model
# Usage: download_mmproj_files <repo> <models_dir> <mmproj_files_list> [non_interactive]
# non_interactive: "true" = auto-download F16, "false" = prompt user, "skip" = don't download
download_mmproj_files() {
    local repo="$1"
    local models_dir="$2"
    local mmproj_list="$3"
    local non_interactive="${4:-false}"
    
    local mmproj_array=()
    local mmproj_sizes=()
    local mmproj_display=()
    
    while IFS='|' read -r filename size; do
        [[ -z "$filename" ]] && continue
        mmproj_array+=("$filename")
        mmproj_sizes+=("$size")
        
        local size_formatted
        if [[ $size -ge 1073741824 ]]; then
            size_formatted="$(echo "scale=1; $size / 1073741824" | bc)GB"
        elif [[ $size -ge 1048576 ]]; then
            size_formatted="$(( size / 1048576 ))MB"
        else
            size_formatted="${size}B"
        fi
        
        # Mark F16 as recommended (higher quality)
        if [[ "$filename" == *"F16"* || "$filename" == *"f16"* ]]; then
            mmproj_display+=("$filename ($size_formatted) ← recommended")
        else
            mmproj_display+=("$filename ($size_formatted)")
        fi
    done <<< "$mmproj_list"
    
    if [[ ${#mmproj_array[@]} -eq 0 ]]; then
        return 0
    fi
    
    local selected_mmproj=()
    
    # Non-interactive mode: skip or auto-select
    if [[ "$non_interactive" == "skip" ]]; then
        print_status "Skipping mmproj download (--no-mmproj)"
        return 0
    fi
    
    if [[ "$non_interactive" == "true" ]]; then
        # Auto-select F16 version (recommended) or first available
        local auto_select=""
        for i in "${!mmproj_array[@]}"; do
            if [[ "${mmproj_array[$i]}" == *"F16"* || "${mmproj_array[$i]}" == *"f16"* ]]; then
                auto_select="${mmproj_array[$i]}"
                break
            fi
        done
        [[ -z "$auto_select" ]] && auto_select="${mmproj_array[0]}"
        
        echo
        print_status "Vision model detected - auto-downloading mmproj: $auto_select"
        selected_mmproj=("$auto_select")
    else
        # Interactive mode
        echo
        echo -e "${CYAN}${BOLD}Vision Model Detected - mmproj Files Available${NC}"
        echo
        echo "  Vision models require multimodal projector (mmproj) files for image processing."
        echo "  F16 = higher quality | Q8_0 = smaller size"
        echo
        
        if [[ "$HAS_GUM" == true ]]; then
            echo -e "  ${DIM}Use Space to toggle, Enter to confirm${NC}"
            echo
            
            # Pre-select F16 version if available
            local preselect=""
            for opt in "${mmproj_display[@]}"; do
                if [[ "$opt" == *"F16"* ]]; then
                    preselect="$opt"
                    break
                fi
            done
            
            local gum_selected gum_exit
            if [[ -n "$preselect" ]]; then
                gum_selected=$(gum choose --no-limit \
                    --cursor-prefix="$GUM_CURSOR_PREFIX" \
                    --selected-prefix="$GUM_SELECTED_PREFIX" \
                    --unselected-prefix="$GUM_UNSELECTED_PREFIX" \
                    --cursor.foreground="212" \
                    --selected.foreground="212" \
                    --height=10 \
                    --selected="$preselect" \
                    "${mmproj_display[@]}") && gum_exit=0 || gum_exit=$?
                check_user_interrupt $gum_exit
            else
                gum_selected=$(gum choose --no-limit \
                    --cursor-prefix="$GUM_CURSOR_PREFIX" \
                    --selected-prefix="$GUM_SELECTED_PREFIX" \
                    --unselected-prefix="$GUM_UNSELECTED_PREFIX" \
                    --cursor.foreground="212" \
                    --selected.foreground="212" \
                    --height=10 \
                    "${mmproj_display[@]}") && gum_exit=0 || gum_exit=$?
                check_user_interrupt $gum_exit
            fi
            
            if [[ -n "$gum_selected" ]]; then
                while IFS= read -r line; do
                    local selected_name="${line%% (*}"
                    for i in "${!mmproj_array[@]}"; do
                        if [[ "${mmproj_array[$i]}" == "$selected_name" ]]; then
                            selected_mmproj+=("${mmproj_array[$i]}")
                            break
                        fi
                    done
                done <<< "$gum_selected"
            fi
        else
            echo "  Available mmproj files:"
            local i=1
            for opt in "${mmproj_display[@]}"; do
                echo "    $i) $opt"
                ((i++))
            done
            echo "    $i) Skip (no mmproj)"
            echo
            read -r -p "Select mmproj to download [1-${#mmproj_array[@]}, or $i to skip]: " selection
            
            if [[ "$selection" =~ ^[0-9]+$ ]] && [[ $selection -ge 1 ]] && [[ $selection -le ${#mmproj_array[@]} ]]; then
                selected_mmproj+=("${mmproj_array[$((selection-1))]}")
            fi
        fi
    fi
    
    # Download selected mmproj files
    for mmproj_file in "${selected_mmproj[@]}"; do
        local output_path="$models_dir/$mmproj_file"
        
        if [[ -f "$output_path" ]]; then
            local actual_size
            actual_size=$(du -h "$output_path" | cut -f1)
            print_status "mmproj already exists: $mmproj_file ($actual_size)"
            continue
        fi
        
        echo
        echo -e "${BOLD}Downloading mmproj: $mmproj_file${NC}"
        
        if command -v huggingface-cli &>/dev/null; then
            # Get file size for spinner
            local mmproj_size=""
            for i in "${!mmproj_array[@]}"; do
                if [[ "${mmproj_array[$i]}" == "$mmproj_file" ]]; then
                    mmproj_size="${mmproj_sizes[$i]}"
                    break
                fi
            done
            
            start_download_spinner "Downloading mmproj" "$output_path" "$mmproj_size"
            huggingface-cli download "$repo" "$mmproj_file" \
                --local-dir "$models_dir" \
                --local-dir-use-symlinks False \
                --quiet 2>/dev/null
            local dl_status=$?
            stop_spinner
            
            if [[ $dl_status -ne 0 ]]; then
                print_error "Failed to download mmproj: $mmproj_file"
            else
                print_success "Downloaded: $mmproj_file"
            fi
        else
            local dl_url="https://huggingface.co/$repo/resolve/main/$mmproj_file"
            start_download_spinner "Downloading mmproj" "$output_path" ""
            curl -fL --connect-timeout 30 --retry 3 -C - -o "$output_path" "$dl_url" 2>/dev/null
            local dl_status=$?
            stop_spinner
            
            if [[ $dl_status -ne 0 ]]; then
                print_error "Failed to download mmproj: $mmproj_file"
                rm -f "$output_path"
            else
                print_success "Downloaded: $mmproj_file"
            fi
        fi
    done
}

# Fetch and offer mmproj download for a vision model
# Usage: handle_vision_model_mmproj <hf_repo> <models_dir> [non_interactive]
# Convenience wrapper that fetches HF file listing and calls download_mmproj_files
handle_vision_model_mmproj() {
    local hf_repo="$1"
    local models_dir="$2"
    local non_interactive="${3:-false}"
    
    # Check if jq is available (required for parsing HF API response)
    if ! command -v jq &>/dev/null; then
        print_warning "jq not installed - cannot fetch mmproj files"
        return 1
    fi
    
    local hf_response
    hf_response=$(curl -sf --connect-timeout 15 --max-time 30 "https://huggingface.co/api/models/$hf_repo/tree/main" 2>/dev/null)
    if [[ -z "$hf_response" ]]; then
        print_warning "Could not fetch mmproj files from HuggingFace"
        return 1
    fi
    
    local mmproj_files
    mmproj_files=$(get_mmproj_files "$hf_response")
    if [[ -z "$mmproj_files" ]]; then
        return 0  # No mmproj files available - not an error
    fi
    
    download_mmproj_files "$hf_repo" "$models_dir" "$mmproj_files" "$non_interactive"
}
