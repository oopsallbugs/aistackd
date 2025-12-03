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

cleanup_spinner() {
    if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
    fi
    SPINNER_PID=""
    printf "\r\033[K"
}

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
# Configuration Paths
# -----------------------------------------------------------------------------

# These can be overridden by the sourcing script before calling init_paths
init_paths() {
    local script_dir="$1"
    
    LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$script_dir/llama.cpp}"
    MODELS_DIR="${MODELS_DIR:-$script_dir/models}"
    MODELS_CONF="${MODELS_CONF:-$script_dir/models.conf}"
    METADATA_CONF="${METADATA_CONF:-$script_dir/models-metadata.conf}"
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

# Ensure models-metadata.conf exists, creating from example if needed
# Usage: ensure_metadata_conf <script_dir> <non_interactive>
#
# script_dir: Directory containing models-metadata.conf.example
# non_interactive: "true" to skip prompts, "false" for interactive mode
#
# If models-metadata.conf doesn't exist, copies from .example
# If it exists but differs from .example, offers to update (interactive)
#
# Returns: Always 0 (success) - skipping is not an error
ensure_metadata_conf() {
    local script_dir="$1"
    local non_interactive="${2:-false}"
    
    local metadata_file="$script_dir/models-metadata.conf"
    local example_file="$script_dir/models-metadata.conf.example"
    
    # Check if example exists
    if [[ ! -f "$example_file" ]]; then
        # No example file, nothing to do
        return 0
    fi
    
    # If metadata file doesn't exist, copy from example
    if [[ ! -f "$metadata_file" ]]; then
        cp "$example_file" "$metadata_file"
        print_status "Created models-metadata.conf from example"
        return 0
    fi
    
    # File exists - check if it differs from example
    if diff -q "$metadata_file" "$example_file" &>/dev/null 2>&1; then
        # Files are identical, nothing to do
        return 0
    fi
    
    # Files differ - prompt user in interactive mode
    if [[ "$non_interactive" == "false" && "$HAS_GUM" == true ]]; then
        print_warning "models-metadata.conf differs from example"
        echo
        print_status "How would you like to handle the metadata config?"
        echo
        
        local choice gum_exit
        choice=$(gum choose \
            "Skip - Keep existing file unchanged" \
            "Overwrite - Replace with example (backup created)" \
            "View diff - Show differences") && gum_exit=0 || gum_exit=$?
        check_user_interrupt $gum_exit
        [[ -z "$choice" ]] && choice="Skip"
        
        case "$choice" in
            "View diff"*)
                echo
                echo -e "${CYAN}${BOLD}Differences (your file vs example):${NC}"
                echo
                diff --color=auto "$metadata_file" "$example_file" || true
                echo
                
                # Ask again after showing diff
                local choice2 gum_exit2
                choice2=$(gum choose \
                    "Skip - Keep existing file unchanged" \
                    "Overwrite - Replace with example (backup created)") && gum_exit2=0 || gum_exit2=$?
                check_user_interrupt $gum_exit2
                [[ -z "$choice2" ]] && choice2="Skip"
                
                if [[ "$choice2" == "Overwrite"* ]]; then
                    local backup_file
                    backup_file="$metadata_file.backup.$(date +%Y%m%d_%H%M%S)"
                    cp "$metadata_file" "$backup_file"
                    print_status "Backed up to: $backup_file"
                    cp "$example_file" "$metadata_file"
                    print_success "Updated models-metadata.conf from example"
                fi
                # Skip is not an error, return success
                return 0
                ;;
            "Overwrite"*)
                local backup_file
                backup_file="$metadata_file.backup.$(date +%Y%m%d_%H%M%S)"
                cp "$metadata_file" "$backup_file"
                print_status "Backed up to: $backup_file"
                cp "$example_file" "$metadata_file"
                print_success "Updated models-metadata.conf from example"
                return 0
                ;;
            "Skip"*|"")
                print_status "Keeping existing models-metadata.conf"
                return 0
                ;;
        esac
    else
        # Non-interactive mode or no gum - keep existing
        return 0
    fi
}

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
# Hardware Status Functions
# -----------------------------------------------------------------------------

# Extract numeric GB value from size string (e.g., "4.5GB" -> "4")
get_model_size_gb() {
    local size_str="$1"
    local size_num
    size_num=$(echo "$size_str" | grep -oE '[0-9]+\.?[0-9]*' | head -1)
    echo "${size_num%.*}"
}

# Determine if model fits in available memory/VRAM
# Returns: "recommended", "may_struggle", "wont_fit", or empty
get_model_hardware_status() {
    local model_size_str="$1"
    local vram="$2"
    
    if [[ "$vram" == "0" || -z "$vram" ]]; then
        echo
        return
    fi
    
    local model_size
    model_size=$(get_model_size_gb "$model_size_str")
    [[ -z "$model_size" || "$model_size" == "0" ]] && model_size=1
    
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

# Format hardware status as colored tag for display
format_hardware_tag() {
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

# Check dependency with version display
# Usage: check_dependency_version "name" "command" "version_cmd" [required]
check_dependency_version() {
    local name="$1"
    local cmd="$2"
    local version_cmd="$3"
    local required="${4:-false}"
    
    local padded_name
    padded_name=$(printf "%-18s" "$name")
    
    if command -v "$cmd" &>/dev/null; then
        local version
        version=$(eval "$version_cmd" 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)
        if [[ -n "$version" ]]; then
            echo -e "  $CHECKMARK $padded_name installed ($version)"
        else
            echo -e "  $CHECKMARK $padded_name installed"
        fi
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
# Dependency Notice for Uninstall Scripts
# -----------------------------------------------------------------------------

# Detect and show dependencies that were installed but won't be removed
# Usage: show_dependency_notice [setup_type]
#   setup_type: "llama" for llama.cpp, "ollama" for Ollama (auto-detects if not specified)
#
# This function detects common dependencies and shows a notice explaining
# they are kept because other applications may use them.
show_dependency_notice() {
    local setup_type="${1:-auto}"
    local -a installed_deps=()
    
    # Auto-detect setup type based on platform and available files if not specified
    if [[ "$setup_type" == "auto" ]]; then
        if [[ "$IS_LINUX" == true ]]; then
            # Check if Docker-based (Ollama) or native (llama.cpp)
            if command -v docker &>/dev/null && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
                setup_type="ollama"
            else
                setup_type="llama"
            fi
        elif [[ "$IS_MACOS" == true ]]; then
            # On macOS, check for Ollama via Homebrew
            if command -v brew &>/dev/null && brew list ollama &>/dev/null 2>&1; then
                setup_type="ollama"
            else
                setup_type="llama"
            fi
        fi
    fi
    
    # Detect dependencies based on platform and setup type
    if [[ "$IS_LINUX" == true ]]; then
        if [[ "$setup_type" == "ollama" ]]; then
            # Ollama Linux dependencies
            command -v docker &>/dev/null && installed_deps+=("Docker")
            command -v gum &>/dev/null && installed_deps+=("gum")
            command -v bc &>/dev/null && installed_deps+=("bc")
            command -v curl &>/dev/null && installed_deps+=("curl")
        else
            # llama.cpp Linux (ROCm) dependencies
            command -v hipcc &>/dev/null && installed_deps+=("ROCm/HIP")
            command -v cmake &>/dev/null && installed_deps+=("cmake")
            command -v make &>/dev/null && installed_deps+=("make")
            command -v git &>/dev/null && installed_deps+=("git")
            command -v gum &>/dev/null && installed_deps+=("gum")
            command -v curl &>/dev/null && installed_deps+=("curl")
            command -v jq &>/dev/null && installed_deps+=("jq")
        fi
    fi
    
    if [[ "$IS_MACOS" == true ]]; then
        if [[ "$setup_type" == "ollama" ]]; then
            # Ollama macOS dependencies
            command -v brew &>/dev/null && installed_deps+=("Homebrew")
            command -v gum &>/dev/null && installed_deps+=("gum")
            [[ -x "/opt/homebrew/bin/bash" ]] && installed_deps+=("Bash 4+ (Homebrew)")
        else
            # llama.cpp macOS (Metal) dependencies
            command -v brew &>/dev/null && installed_deps+=("Homebrew")
            xcode-select -p &>/dev/null && installed_deps+=("Xcode Command Line Tools")
            command -v cmake &>/dev/null && installed_deps+=("cmake")
            command -v git &>/dev/null && installed_deps+=("git")
            command -v gum &>/dev/null && installed_deps+=("gum")
            command -v curl &>/dev/null && installed_deps+=("curl")
            command -v jq &>/dev/null && installed_deps+=("jq")
        fi
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
        if [[ "$setup_type" == "ollama" ]]; then
            echo -e "${DIM}  sudo pacman -R docker gum bc  # Arch${NC}"
            echo -e "${DIM}  sudo apt remove docker.io gum bc  # Ubuntu${NC}"
        else
            echo -e "${DIM}  # ROCm: Follow AMD's uninstall guide${NC}"
            echo -e "${DIM}  sudo pacman -R cmake make gum jq  # Arch${NC}"
            echo -e "${DIM}  sudo apt remove cmake make gum jq  # Ubuntu${NC}"
        fi
    fi
    
    if [[ "$IS_MACOS" == true ]]; then
        echo -e "${DIM}  brew uninstall gum cmake jq${NC}"
        echo -e "${DIM}  # Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)\"${NC}"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Whitespace Trimming
# -----------------------------------------------------------------------------

# Trim leading and trailing whitespace from a variable
# Usage: trimmed=$(trim "  hello world  ")
trim() {
    local var="$1"
    var="${var#"${var%%[![:space:]]*}"}"
    var="${var%"${var##*[![:space:]]}"}"
    echo "$var"
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
#   agent/plan.md   -> ~/.config/opencode/agents/plan.md
#   agent/review.md -> ~/.config/opencode/agents/review.md
#   agent/debug.md  -> ~/.config/opencode/agents/debug.md
#
# Returns: 0 if files were created/updated, 1 if skipped
sync_agents() {
    local script_dir="$1"
    local target_dir="$2"
    local non_interactive="$3"
    local reset_mode="${4:-false}"
    
    local source_dir="$script_dir/agent"
    local agents_target_dir="$target_dir/agents"
    
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
        
        # Sync agent files to agents/ subdirectory
        for file in "${agent_files[@]}"; do
            local src="$source_dir/$file"
            local dst="$agents_target_dir/$file"
            if [[ -f "$src" ]]; then
                if [[ -f "$dst" ]]; then
                    cp "$dst" "$dst.backup.$backup_timestamp"
                    print_status "Backed up agents/$file"
                fi
                mkdir -p "$agents_target_dir"
                cp "$src" "$dst"
            fi
        done
        
        print_success "Agent files reset to defaults"
        print_status "  AGENTS.md -> $target_dir/AGENTS.md"
        print_status "  agents/   -> $agents_target_dir/"
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
        local dst="$agents_target_dir/$file"
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
                        local dst="$agents_target_dir/$file"
                        if [[ -f "$dst" ]] && ! diff -q "$src" "$dst" &>/dev/null 2>&1; then
                            echo -e "${BOLD}=== agents/$file ===${NC}"
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
        
        # Sync agent files to agents/ subdirectory
        for file in "${agent_files[@]}"; do
            local src="$source_dir/$file"
            if [[ -f "$src" ]]; then
                mkdir -p "$agents_target_dir"
                cp "$src" "$agents_target_dir/$file"
            fi
        done
        
        print_success "Agent files created:"
        print_status "  AGENTS.md -> $target_dir/AGENTS.md"
        print_status "  agents/   -> $agents_target_dir/"
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
