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

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

# -----------------------------------------------------------------------------
# Spinner for Long Operations
# -----------------------------------------------------------------------------

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
    print_status "Setup cancelled by user (Ctrl+C)"
    echo
    echo -e "${DIM}You can resume setup anytime by running ./setup.sh again${NC}"
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

declare -A MODEL_DISPLAY_NAME
declare -A MODEL_CONTEXT_LIMIT
declare -A MODEL_OUTPUT_LIMIT

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
    
    for model in "${MODEL_ORDER[@]}"; do
        IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
        
        # Check if model already downloaded
        local downloaded_prefix=""
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            downloaded_prefix="* "
        fi
        
        local label="${downloaded_prefix}$model (~$size) - $description"
        options+=("$label")
    done
    
    echo
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo -e "${CYAN}${BOLD}  Select GGUF Models to Download${NC}"
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo
    echo -e "${DIM}* = already downloaded${NC}"
    echo -e "${DIM}Use Space to toggle, Enter to confirm${NC}"
    echo
    
    # Build preselected list
    local preselected_labels=()
    for model in "${MODEL_ORDER[@]}"; do
        if [[ "${MODEL_SELECTED[$model]}" == "1" ]]; then
            IFS='|' read -r category hf_repo gguf_file size description <<< "${MODEL_INFO[$model]}"
            local downloaded_prefix=""
            if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
                downloaded_prefix="* "
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
            --cursor-prefix="[ ] " \
            --selected-prefix="[x] " \
            --unselected-prefix="[ ] " \
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
            --cursor-prefix="[ ] " \
            --selected-prefix="[x] " \
            --unselected-prefix="[ ] " \
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
        line="${line#\* }"  # Strip star prefix
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
        
        local cleanup_choice=""
        if [[ "$HAS_GUM" == true ]]; then
            cleanup_choice=$(gum choose --cursor-prefix="[ ] " --selected-prefix="[x] " \
                --cursor.foreground="212" \
                "Run cleanup now" \
                "Skip for now") || cleanup_choice="Skip for now"
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
