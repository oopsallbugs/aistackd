#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp Server Start Script
# Cross-platform script to start llama-server with proper GPU settings
# Supports: Linux (ROCm/HIP) and macOS (Metal)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
source "$SCRIPT_DIR/lib/common.sh"

# Load configuration
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Defaults
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$SCRIPT_DIR/llama.cpp}"
MODELS_DIR="${MODELS_DIR:-$SCRIPT_DIR/models}"
MODELS_CONF="${MODELS_CONF:-$SCRIPT_DIR/models.conf}"
MODELS_METADATA="${MODELS_METADATA:-$SCRIPT_DIR/models-metadata.conf}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_CONTEXT="${LLAMA_CONTEXT:-32768}"
LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
GPU_LAYERS="${GPU_LAYERS:-99}"
LOG_FILE=""  # Optional log file

# Escape special regex characters for use in grep/sed patterns
# Usage: escape_regex "string"
escape_regex() {
    printf '%s' "$1" | sed 's/[.[\*^$()+?{|\\]/\\&/g'
}

# =============================================================================
# Model Metadata Configuration
# =============================================================================

# Get context limit for a model from metadata
# Usage: get_model_context <model_id> [default_value]
get_model_context() {
    local model_id="$1"
    local default="${2:-32768}"
    
    if [[ ! -f "$MODELS_METADATA" ]]; then
        echo "$default"
        return
    fi
    
    # Format: model_id|display_name|context_limit|output_limit
    local context escaped_id
    escaped_id=$(escape_regex "$model_id")
    context=$(grep "^${escaped_id}|" "$MODELS_METADATA" 2>/dev/null | head -1 | cut -d'|' -f3)
    
    if [[ -n "$context" && "$context" =~ ^[0-9]+$ ]]; then
        echo "$context"
    else
        echo "$default"
    fi
}

# Update context limit for a model in metadata
# Usage: set_model_context <model_id> <context_limit>
set_model_context() {
    local model_id="$1"
    local context="$2"
    
    if [[ ! -f "$MODELS_METADATA" ]]; then
        return 1
    fi
    
    local escaped_id
    escaped_id=$(escape_regex "$model_id")
    
    # Check if model exists in metadata
    if grep -q "^${escaped_id}|" "$MODELS_METADATA" 2>/dev/null; then
        # Update existing entry - replace the context field (3rd field)
        # Format: model_id|display_name|context_limit|output_limit
        # Use # as sed delimiter since | is in the data
        sed -i "s#^\(${escaped_id}|[^|]*|\)[^|]*|\(.*\)\$#\1${context}|\2#" "$MODELS_METADATA"
        return 0
    else
        # Model not in metadata - we could add it, but for now just skip
        return 1
    fi
}

# Get HSA override version based on GPU architecture (Linux/ROCm only)
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

show_help() {
    echo
    echo -e "${CYAN}${BOLD}llama.cpp Server Launcher${NC}"
    echo
    echo "Usage: ./start-server.sh [OPTIONS] <model-id>"
    echo
    echo "Arguments:"
    echo "  model-id          Model ID from models.conf (e.g., qwen3-8b-q4km)"
    echo "                    Or an alias (e.g., qwen3, fast, coder)"
    echo "                    Or path to a .gguf file"
    echo
    echo "Options:"
    echo "  -p, --port PORT       Server port (default: $LLAMA_PORT)"
    echo "  -c, --context SIZE    Context window size (default: $LLAMA_CONTEXT)"
    echo "  --host HOST           Host to bind to (default: $LLAMA_HOST)"
    echo "  -n, --ngl LAYERS      GPU layers to offload (default: $GPU_LAYERS, -1 for all)"
    echo "  -b, --batch SIZE      Batch size for prompt processing (default: 512)"
    echo "  -t, --threads N       Number of CPU threads"
    echo "  --parallel N          Number of parallel request slots"
    echo "  --flash-attn          Enable flash attention (faster)"
    echo "  --no-flash-attn       Disable flash attention"
    echo "  --gpu GPU_ID          Select GPU by ID for multi-GPU systems (default: 0)"
    echo "  --log FILE            Write server output to log file"
    echo "  --watchdog            Auto-restart server on crash"
    echo "  --no-vram-check       Skip VRAM analysis and auto-context recommendation"
    echo "  --context-menu        Interactive context size selector (shows VRAM fit)"
    echo "  --benchmark           Run quick benchmark after server starts"
    echo "  --list                List available models"
    echo "  --health              Check if server is running and healthy"
    echo "  --cleanup             Kill existing llama processes and free VRAM"
    echo "  --status              Show GPU/VRAM status"
    echo "  --help                Show this help message"
    echo
    echo "Aliases (defined in models.conf):"
    # Dynamically read aliases from models.conf
    if [[ -f "$SCRIPT_DIR/models.conf" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^ALIAS:([^=]+)=(.+)$ ]]; then
                local alias_name="${BASH_REMATCH[1]}"
                local target="${BASH_REMATCH[2]}"
                printf "  %-16s -> %s\n" "$alias_name" "$target"
            fi
        done < "$SCRIPT_DIR/models.conf"
    else
        echo "  (models.conf not found)"
    fi
    echo
    echo "Examples:"
    echo "  ./start-server.sh qwen3          # Use alias"
    echo "  ./start-server.sh qwen3-8b-q4km  # Use full name"
    echo "  ./start-server.sh -p 8081 -c 65536 qwen3-8b-q4km"
    echo "  ./start-server.sh --benchmark fast"
    echo "  ./start-server.sh --watchdog --log server.log qwen3"
    echo "  ./start-server.sh --gpu 1 qwen3  # Use second GPU"
    echo "  ./start-server.sh --context-menu qwen3  # Choose context interactively"
    echo "  ./start-server.sh /path/to/model.gguf"
    echo
}

list_models() {
    echo
    echo -e "${CYAN}${BOLD}Available Models${NC}"
    echo
    
    if [[ ! -f "$SCRIPT_DIR/models.conf" ]]; then
        echo "models.conf not found"
        exit 1
    fi
    
    while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
        gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
        size="${size#"${size%%[![:space:]]*}"}"
        size="${size%"${size##*[![:space:]]}"}"
        description="${description#"${description%%[![:space:]]*}"}"
        description="${description%"${description##*[![:space:]]}"}"
        
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            echo -e "  ${GREEN}✓${NC} $model_id ($size) - $description"
        else
            echo -e "  ${RED}✗${NC} $model_id ($size) - $description ${YELLOW}(not downloaded)${NC}"
        fi
    done < "$SCRIPT_DIR/models.conf"
    
    echo
    echo "Downloaded models are in: $MODELS_DIR"
    echo "Run './download-model.sh <model-id>' to download a model"
    echo
}

# =============================================================================
# Health Check Function
# =============================================================================

check_health() {
    local host="${1:-$LLAMA_HOST}"
    local port="${2:-$LLAMA_PORT}"
    local endpoint="http://$host:$port"
    
    echo
    echo -e "${CYAN}${BOLD}Server Health Check${NC}"
    echo
    echo -e "  ${BOLD}Endpoint:${NC} $endpoint"
    echo
    
    # Check if server is responding
    local health_response
    if health_response=$(curl -sf --max-time 5 "$endpoint/health" 2>/dev/null); then
        print_success "Server is running"
        
        # Parse health response if JSON
        if command -v jq &>/dev/null && echo "$health_response" | jq . &>/dev/null; then
            local status
            status=$(echo "$health_response" | jq -r '.status // "unknown"')
            echo -e "  ${BOLD}Status:${NC} $status"
            
            local slots_idle slots_processing
            slots_idle=$(echo "$health_response" | jq -r '.slots_idle // empty')
            slots_processing=$(echo "$health_response" | jq -r '.slots_processing // empty')
            
            if [[ -n "$slots_idle" || -n "$slots_processing" ]]; then
                echo -e "  ${BOLD}Slots:${NC} ${slots_idle:-0} idle, ${slots_processing:-0} processing"
            fi
        fi
        
        # Try to get model info from /props endpoint
        local props_response
        if props_response=$(curl -sf --max-time 5 "$endpoint/props" 2>/dev/null); then
            if command -v jq &>/dev/null && echo "$props_response" | jq . &>/dev/null; then
                local model_name
                # Try different field names for model
                model_name=$(echo "$props_response" | jq -r '.default_generation_settings.model // .model // empty' 2>/dev/null)
                if [[ -n "$model_name" && "$model_name" != "null" ]]; then
                    echo -e "  ${BOLD}Model:${NC} $(basename "$model_name")"
                fi
            fi
        fi
        
        echo
        return 0
    else
        print_error "Server is not responding"
        echo
        
        # Check if process is running but not responding
        local llama_pids
        llama_pids=$(pgrep -f "llama-server" 2>/dev/null || true)
        if [[ -n "$llama_pids" ]]; then
            echo -e "  ${YELLOW}Note:${NC} llama-server process found (PID: $llama_pids)"
            echo "  Server may still be loading or crashed"
        else
            echo "  No llama-server process found"
            echo "  Start with: ./start-server.sh <model-id>"
        fi
        echo
        return 1
    fi
}

# =============================================================================
# Model Info Display
# =============================================================================

get_model_info() {
    local gguf_path="$1"
    local model_basename
    model_basename=$(basename "$gguf_path")
    
    # Get file size
    local file_size=""
    if [[ -f "$gguf_path" ]]; then
        file_size=$(du -h "$gguf_path" 2>/dev/null | cut -f1)
    fi
    
    # Try to get model metadata from models.conf
    local model_desc=""
    local model_category=""
    
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
            description="${description#"${description%%[![:space:]]*}"}"
            description="${description%"${description##*[![:space:]]}"}"
            
            if [[ "$gguf_file" == "$model_basename" ]]; then
                model_desc="$description"
                model_category="$category"
                break
            fi
        done < "$MODELS_CONF"
    fi
    
    # Return info as pipe-separated string
    echo "$file_size|$model_desc|$model_category"
}

# =============================================================================
# Validate models.conf Syntax
# =============================================================================

validate_models_conf() {
    local conf_file="${1:-$MODELS_CONF}"
    local errors=0
    local line_num=0
    
    if [[ ! -f "$conf_file" ]]; then
        return 0  # Nothing to validate
    fi
    
    while IFS= read -r line || [[ -n "$line" ]]; do
        ((line_num++))
        
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        
        # Skip ALIAS and WHITELIST lines (different format)
        [[ "$line" =~ ^ALIAS: ]] && continue
        [[ "$line" =~ ^WHITELIST: ]] && continue
        
        # Count pipe separators (should be exactly 5 for model entries)
        local pipe_count
        pipe_count=$(echo "$line" | tr -cd '|' | wc -c)
        
        if [[ $pipe_count -ne 5 ]]; then
            print_warning "models.conf line $line_num: expected 5 pipes, found $pipe_count"
            echo -e "  ${DIM}$line${NC}"
            ((errors++))
        fi
        
        # Check for commas in description (breaks gum menus)
        if [[ "$line" == *","* ]]; then
            # Only warn if comma is in description field (last field)
            local desc_field
            desc_field=$(echo "$line" | cut -d'|' -f6)
            if [[ "$desc_field" == *","* ]]; then
                print_warning "models.conf line $line_num: comma in description may cause menu issues"
                ((errors++))
            fi
        fi
    done < "$conf_file"
    
    return $errors
}

# Parse arguments
MODEL_PATH=""
FLASH_ATTN=""  # Default is 'auto', only set if user explicitly requests
EXTRA_ARGS=()
RUN_BENCHMARK=false
BATCH_SIZE=""
THREADS=""
PARALLEL=""
WATCHDOG_MODE=false
GPU_ID=""
SKIP_VRAM_CHECK=false
CONTEXT_MENU=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--port)
            LLAMA_PORT="$2"
            shift 2
            ;;
        -c|--context)
            LLAMA_CONTEXT="$2"
            shift 2
            ;;
        --host)
            LLAMA_HOST="$2"
            shift 2
            ;;
        -n|--ngl)
            GPU_LAYERS="$2"
            shift 2
            ;;
        -b|--batch)
            BATCH_SIZE="$2"
            shift 2
            ;;
        -t|--threads)
            THREADS="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --flash-attn)
            FLASH_ATTN="-fa"
            shift
            ;;
        --no-flash-attn)
            FLASH_ATTN="--no-flash-attn"
            shift
            ;;
        --gpu)
            GPU_ID="$2"
            shift 2
            ;;
        --log)
            LOG_FILE="$2"
            shift 2
            ;;
        --watchdog)
            WATCHDOG_MODE=true
            shift
            ;;
        --no-vram-check)
            SKIP_VRAM_CHECK=true
            shift
            ;;
        --context-menu)
            CONTEXT_MENU=true
            shift
            ;;
        --benchmark)
            RUN_BENCHMARK=true
            shift
            ;;
        --list)
            list_models
            exit 0
            ;;
        --health)
            check_health "$LLAMA_HOST" "$LLAMA_PORT"
            exit $?
            ;;
        --cleanup)
            echo
            echo -e "${CYAN}${BOLD}Cleaning up llama-server processes...${NC}"
            echo
            cleanup_pids=$(pgrep -f "llama-server" 2>/dev/null || true)
            if [[ -n "$cleanup_pids" ]]; then
                echo "Found llama-server processes: $cleanup_pids"
                pkill -f "llama-server" 2>/dev/null || true
                sleep 2
                echo -e "${GREEN}Killed llama-server processes${NC}"
            else
                echo "No llama-server processes found"
            fi
            echo
            # Show VRAM/memory status
            if [[ "$IS_LINUX" == true ]]; then
                if command -v rocm-smi &>/dev/null; then
                    rocm-smi 2>/dev/null | head -10
                elif [[ -x "/opt/rocm/bin/rocm-smi" ]]; then
                    /opt/rocm/bin/rocm-smi 2>/dev/null | head -10
                fi
            elif [[ "$IS_MACOS" == true ]]; then
                echo "Memory status:"
                vm_stat 2>/dev/null | head -5
            fi
            echo
            exit 0
            ;;
        --status)
            echo
            echo -e "${CYAN}${BOLD}GPU/Memory Status${NC}"
            echo
            # Show rocm-smi output (Linux) or system info (macOS)
            if [[ "$IS_LINUX" == true ]]; then
                if command -v rocm-smi &>/dev/null; then
                    rocm-smi 2>/dev/null
                elif [[ -x "/opt/rocm/bin/rocm-smi" ]]; then
                    /opt/rocm/bin/rocm-smi 2>/dev/null
                else
                    echo "rocm-smi not found"
                fi
            elif [[ "$IS_MACOS" == true ]]; then
                echo "Chip: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'Unknown')"
                mem_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))
                echo "Memory: ${mem_gb}GB unified"
                echo
            fi
            echo
            # Show llama-server processes
            echo -e "${CYAN}${BOLD}Llama Server Processes${NC}"
            echo
            llama_procs=$(pgrep -af "llama-server" 2>/dev/null || true)
            if [[ -n "$llama_procs" ]]; then
                echo "$llama_procs"
            else
                echo "No llama-server processes running"
            fi
            echo
            exit 0
            ;;
        --help)
            show_help
            exit 0
            ;;
        -*)
            # Pass unknown flags to llama-server
            EXTRA_ARGS+=("$1")
            shift
            ;;
        *)
            MODEL_PATH="$1"
            shift
            ;;
    esac
done

# Validate model
if [[ -z "$MODEL_PATH" ]]; then
    echo -e "${RED}Error: No model specified${NC}"
    echo
    echo "Usage: ./start-server.sh <model-id>"
    echo "Run './start-server.sh --list' to see available models"
    exit 1
fi

# Resolve alias to model ID
resolve_alias() {
    local input="$1"
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^ALIAS:([^=]+)=(.+)$ ]]; then
            local alias_name="${BASH_REMATCH[1]}"
            local target="${BASH_REMATCH[2]}"
            if [[ "$input" == "$alias_name" ]]; then
                echo "$target"
                return 0
            fi
        fi
    done < "$SCRIPT_DIR/models.conf"
    echo "$input"
}

# Check if MODEL_PATH is an alias
RESOLVED_MODEL=$(resolve_alias "$MODEL_PATH")
if [[ "$RESOLVED_MODEL" != "$MODEL_PATH" ]]; then
    echo -e "${CYAN}Alias '$MODEL_PATH' -> '$RESOLVED_MODEL'${NC}"
    MODEL_PATH="$RESOLVED_MODEL"
fi

# Resolve model path and track model ID
MODEL_ID=""
if [[ -f "$MODEL_PATH" ]]; then
    # Direct path to gguf file
    GGUF_PATH="$MODEL_PATH"
    # Try to find model ID from gguf filename
    gguf_basename=$(basename "$MODEL_PATH")
    while IFS='|' read -r category mid hf_repo gguf_file size description || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
        gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
        mid="${mid#"${mid%%[![:space:]]*}"}"
        mid="${mid%"${mid##*[![:space:]]}"}"
        if [[ "$gguf_file" == "$gguf_basename" ]]; then
            MODEL_ID="$mid"
            break
        fi
    done < "$SCRIPT_DIR/models.conf"
elif [[ -f "$MODELS_DIR/$MODEL_PATH" ]]; then
    # Filename in models dir
    GGUF_PATH="$MODELS_DIR/$MODEL_PATH"
else
    # Look up model ID in models.conf
    GGUF_FILE=""
    while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim all fields
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        hf_repo="${hf_repo#"${hf_repo%%[![:space:]]*}"}"
        hf_repo="${hf_repo%"${hf_repo##*[![:space:]]}"}"
        gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
        gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
        size="${size#"${size%%[![:space:]]*}"}"
        size="${size%"${size##*[![:space:]]}"}"
        
        if [[ "$model_id" == "$MODEL_PATH" ]]; then
            # Validate entry before using it
            if ! validate_model_entry "$category" "$model_id" "$hf_repo" "$gguf_file" "$size"; then
                print_error "Model entry for '$MODEL_PATH' is invalid in models.conf"
                exit 1
            fi
            GGUF_FILE="$gguf_file"
            MODEL_ID="$model_id"
            break
        fi
    done < "$SCRIPT_DIR/models.conf"
    
    if [[ -z "$GGUF_FILE" ]]; then
        echo -e "${RED}Error: Model '$MODEL_PATH' not found in models.conf${NC}"
        echo "Run './start-server.sh --list' to see available models"
        exit 1
    fi
    
    GGUF_PATH="$MODELS_DIR/$GGUF_FILE"
    
    if [[ ! -f "$GGUF_PATH" ]]; then
        echo -e "${RED}Error: Model file not downloaded: $GGUF_FILE${NC}"
        echo "Run './download-model.sh $MODEL_PATH' to download it"
        exit 1
    fi
fi

# Load saved context size from metadata (if not overridden by -c flag)
if [[ -n "$MODEL_ID" && "$LLAMA_CONTEXT" == "32768" ]]; then
    SAVED_CONTEXT=$(get_model_context "$MODEL_ID" "")
    if [[ -n "$SAVED_CONTEXT" ]]; then
        LLAMA_CONTEXT="$SAVED_CONTEXT"
    fi
fi

# Check llama-server exists
LLAMA_SERVER="$LLAMA_CPP_DIR/build/bin/llama-server"
if [[ ! -f "$LLAMA_SERVER" ]]; then
    echo -e "${RED}Error: llama-server not found at $LLAMA_SERVER${NC}"
    echo "Run './setup.sh' to build llama.cpp"
    exit 1
fi

# Export GPU settings (Linux/ROCm only)
# macOS Metal doesn't need HSA settings
if [[ "$IS_LINUX" == true ]]; then
    # Use HSA version from .env, or derive from GPU_TARGET, or default to RDNA3
    if [[ -z "${HSA_OVERRIDE_GFX_VERSION:-}" ]]; then
        if [[ -n "${GPU_TARGET:-}" ]]; then
            HSA_OVERRIDE_GFX_VERSION=$(get_hsa_version "$GPU_TARGET")
        else
            HSA_OVERRIDE_GFX_VERSION="11.0.0"
        fi
    fi
    export HSA_OVERRIDE_GFX_VERSION
fi

# =============================================================================
# VRAM and Process Checks
# =============================================================================

# Check for existing llama-server processes
check_existing_processes() {
    local existing_pids
    existing_pids=$(pgrep -f "llama-server" 2>/dev/null || true)
    
    if [[ -n "$existing_pids" ]]; then
        echo
        echo -e "${YELLOW}Warning: llama-server is already running${NC}"
        echo -e "  PIDs: $existing_pids"
        echo
        echo "This may cause port conflicts or VRAM issues."
        echo
        
        local choice=""
        if [[ "$HAS_GUM" == true ]]; then
            if gum confirm "Kill existing server(s) and continue?"; then
                choice="y"
            else
                choice="n"
            fi
        else
            read -p "Kill existing server(s) and continue? [Y/n]: " choice
        fi
        
        case "$choice" in
            [Nn]*)
                echo "Cancelled. Use a different port with -p or stop existing servers manually."
                exit 0
                ;;
            *)
                echo "Stopping existing llama-server processes..."
                pkill -f "llama-server" 2>/dev/null || true
                sleep 2
                echo -e "${GREEN}Done${NC}"
                ;;
        esac
    fi
}

# Get VRAM info from rocm-smi (Linux only)
# On macOS, unified memory is used - no separate VRAM
get_vram_info() {
    # macOS uses unified memory, skip VRAM check
    if [[ "$IS_MACOS" == true ]]; then
        return 1
    fi
    
    local rocm_smi=""
    if command -v rocm-smi &>/dev/null; then
        rocm_smi="rocm-smi"
    elif [[ -x "/opt/rocm/bin/rocm-smi" ]]; then
        rocm_smi="/opt/rocm/bin/rocm-smi"
    else
        return 1
    fi
    
    # Get VRAM usage percentage and total
    local vram_info
    vram_info=$($rocm_smi 2>/dev/null | grep -E "^0" | head -1)
    
    if [[ -n "$vram_info" ]]; then
        # Extract VRAM% (second to last column typically)
        local vram_pct
        vram_pct=$(echo "$vram_info" | awk '{print $(NF-1)}' | tr -d '%')
        echo "$vram_pct"
    else
        return 1
    fi
}

# Get detailed VRAM info (total and used in bytes)
# Linux: from rocm-smi
# macOS: from system memory (unified memory architecture)
get_vram_details() {
    local gpu_id="${1:-0}"
    
    if [[ "$IS_MACOS" == true ]]; then
        # macOS uses unified memory - report system RAM
        local total_bytes used_bytes avail_bytes
        total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
        
        # Get memory pressure info from vm_stat
        local page_size pages_free pages_inactive
        page_size=$(vm_stat 2>/dev/null | grep "page size" | grep -oE '[0-9]+' || echo 4096)
        pages_free=$(vm_stat 2>/dev/null | grep "Pages free" | grep -oE '[0-9]+' || echo 0)
        pages_inactive=$(vm_stat 2>/dev/null | grep "Pages inactive" | grep -oE '[0-9]+' || echo 0)
        
        avail_bytes=$(( (pages_free + pages_inactive) * page_size ))
        used_bytes=$((total_bytes - avail_bytes))
        
        local total_mb=$((total_bytes / 1024 / 1024))
        local used_mb=$((used_bytes / 1024 / 1024))
        local avail_mb=$((avail_bytes / 1024 / 1024))
        
        echo "$total_mb|$used_mb|$avail_mb"
        return 0
    fi
    
    # Linux: use rocm-smi
    local rocm_smi=""
    if command -v rocm-smi &>/dev/null; then
        rocm_smi="rocm-smi"
    elif [[ -x "/opt/rocm/bin/rocm-smi" ]]; then
        rocm_smi="/opt/rocm/bin/rocm-smi"
    else
        return 1
    fi
    
    local vram_output
    vram_output=$($rocm_smi --showmeminfo vram 2>/dev/null)
    
    if [[ -z "$vram_output" ]]; then
        return 1
    fi
    
    # Parse total and used VRAM for the specified GPU
    local total_bytes used_bytes
    total_bytes=$(echo "$vram_output" | grep "GPU\[$gpu_id\]" | grep "Total Memory" | grep -oE '[0-9]+$')
    used_bytes=$(echo "$vram_output" | grep "GPU\[$gpu_id\]" | grep "Used Memory" | grep -oE '[0-9]+$')
    
    if [[ -n "$total_bytes" && -n "$used_bytes" ]]; then
        # Return as pipe-separated: total|used|available (all in MB)
        local total_mb=$((total_bytes / 1024 / 1024))
        local used_mb=$((used_bytes / 1024 / 1024))
        local avail_mb=$((total_mb - used_mb))
        echo "$total_mb|$used_mb|$avail_mb"
        return 0
    fi
    
    return 1
}

# Estimate VRAM needed for model + KV cache
# Returns recommended context size that fits in available VRAM/memory
estimate_context_for_vram() {
    local model_path="$1"
    local available_vram_mb="$2"
    local requested_context="$3"
    
    # Get model file size in MB (cross-platform)
    local model_size_bytes model_size_mb
    model_size_bytes=$(get_file_size "$model_path")
    if [[ -z "$model_size_bytes" ]]; then
        return 1
    fi
    model_size_mb=$((model_size_bytes / 1024 / 1024))
    
    # Model VRAM ≈ file size * 1.02 (small overhead for buffers)
    # The model loads almost exactly at file size
    local model_vram_mb=$((model_size_mb * 102 / 100))
    
    # KV cache estimation - this is the tricky part
    # Empirical observation from Qwen3-32B (32.76B params):
    #   - 32K context = 8192 MB KV cache
    #   - That's 256 MB per 1K context for a 32B model
    #   - Or approximately 8 MB per 1K context per 1B params
    #
    # More accurate formula based on model architecture:
    # KV cache ≈ 2 * n_layer * n_kv_heads * head_dim * context * 2 bytes (FP16)
    # For typical models: n_kv_heads ≈ n_heads/8, head_dim = 128
    # Simplified: ~0.5 MB per 1K context per 1B params (with GQA)
    #
    # But llama.cpp allocates full context upfront, and there's overhead
    # Using conservative estimate: 8 MB per 1K context per 1B params
    
    # Estimate params from file size: Q4_K_M ≈ 0.56 bytes/param (4.82 BPW / 8)
    local estimated_params_b=$((model_size_bytes * 100 / 56 / 1000000000))
    if [[ $estimated_params_b -lt 1 ]]; then
        estimated_params_b=1
    fi
    
    # KV cache per 1K context (MB) - empirical formula
    # Based on observed: 32B model, 32K context = 8GB KV cache
    # = 8000 MB / 32 / 32 = ~7.8 MB per 1K per 1B params
    # Use 8 MB for safety margin
    local kv_per_1k_per_b=8
    local kv_per_1k_mb=$((estimated_params_b * kv_per_1k_per_b))
    
    # Minimum 64 MB per 1K context (for small models)
    if [[ $kv_per_1k_mb -lt 64 ]]; then
        kv_per_1k_mb=64
    fi
    
    # Available VRAM for KV cache (leave 800MB headroom for compute buffers)
    local headroom_mb=800
    local vram_for_kv=$((available_vram_mb - model_vram_mb - headroom_mb))
    
    if [[ $vram_for_kv -le 0 ]]; then
        # Model itself won't fit
        echo "0|$model_vram_mb|0|$estimated_params_b|$kv_per_1k_mb"
        return 0
    fi
    
    # Calculate max context that fits
    local max_context_k=$((vram_for_kv / kv_per_1k_mb))
    local max_context=$((max_context_k * 1024))
    
    # Round down to common context sizes
    if [[ $max_context -ge 131072 ]]; then
        max_context=131072
    elif [[ $max_context -ge 65536 ]]; then
        max_context=65536
    elif [[ $max_context -ge 32768 ]]; then
        max_context=32768
    elif [[ $max_context -ge 16384 ]]; then
        max_context=16384
    elif [[ $max_context -ge 8192 ]]; then
        max_context=8192
    elif [[ $max_context -ge 4096 ]]; then
        max_context=4096
    elif [[ $max_context -ge 2048 ]]; then
        max_context=2048
    else
        max_context=1024
    fi
    
    # Calculate KV cache for requested context
    local requested_kv_mb=$(( (requested_context / 1024) * kv_per_1k_mb ))
    local total_requested_mb=$((model_vram_mb + requested_kv_mb + headroom_mb))
    
    # Return: max_context|model_vram_mb|requested_total_mb|estimated_params_b|kv_per_1k_mb
    echo "$max_context|$model_vram_mb|$total_requested_mb|$estimated_params_b|$kv_per_1k_mb"
}

# Check VRAM availability
check_vram() {
    local vram_pct
    vram_pct=$(get_vram_info 2>/dev/null) || return 0  # Skip check if rocm-smi unavailable
    
    # Warn if more than 20% VRAM is already in use
    if [[ "$vram_pct" =~ ^[0-9]+$ ]] && [[ "$vram_pct" -gt 20 ]]; then
        echo
        echo -e "${YELLOW}Warning: ${vram_pct}% of VRAM is already in use${NC}"
        echo
        echo "This may cause the model to fail to load."
        echo "Common causes: previous llama-server, gaming, desktop compositing"
        echo
        
        # Check if llama-server processes are using it
        local llama_pids
        llama_pids=$(pgrep -f "llama-server" 2>/dev/null || true)
        
        if [[ -n "$llama_pids" ]]; then
            echo -e "Found llama-server processes: ${BOLD}$llama_pids${NC}"
            
            local choice=""
            if [[ "$HAS_GUM" == true ]]; then
                if gum confirm "Kill these processes to free VRAM?"; then
                    choice="y"
                else
                    choice="n"
                fi
            else
                read -p "Kill these processes to free VRAM? [Y/n]: " choice
            fi
            
            case "$choice" in
                [Nn]*)
                    echo "Continuing anyway..."
                    ;;
                *)
                    echo "Killing llama-server processes..."
                    pkill -f "llama-server" 2>/dev/null || true
                    sleep 2
                    echo -e "${GREEN}Done${NC}"
                    # Re-check
                    local new_pct
                    new_pct=$(get_vram_info 2>/dev/null) || true
                    if [[ -n "$new_pct" ]]; then
                        echo -e "VRAM usage now: ${GREEN}${new_pct}%${NC}"
                    fi
                    ;;
            esac
        else
            echo "No llama-server processes found. Other applications may be using VRAM."
            
            local choice=""
            if [[ "$HAS_GUM" == true ]]; then
                if gum confirm "Continue anyway?"; then
                    choice="y"
                else
                    choice="n"
                fi
            else
                read -p "Continue anyway? [Y/n]: " choice
            fi
            
            case "$choice" in
                [Nn]*)
                    echo "Cancelled. Free up VRAM and try again."
                    exit 1
                    ;;
            esac
        fi
        echo
    fi
}

# Run checks
check_existing_processes
check_vram

# =============================================================================
# Auto-Context Size Recommendation
# =============================================================================

# Get fit status for a context size
# Returns: ok|borderline|no
get_context_fit_status() {
    local total_needed_mb="$1"
    local available_mb="$2"
    
    # Calculate percentage of available VRAM needed
    local pct=$((total_needed_mb * 100 / available_mb))
    
    if [[ $pct -le 90 ]]; then
        echo "ok"
    elif [[ $pct -le 100 ]]; then
        echo "borderline"
    else
        echo "no"
    fi
}

# Format context option with fit status
format_context_option() {
    local ctx="$1"
    local model_vram_mb="$2"
    local kv_per_1k="$3"
    local avail_mb="$4"
    local headroom_mb="$5"
    
    local ctx_k=$((ctx / 1024))
    local kv_mb=$((ctx_k * kv_per_1k))
    local total_mb=$((model_vram_mb + kv_mb + headroom_mb))
    # Show decimal GB for more precision (e.g., 21.5GB instead of 21GB)
    local total_gb_int=$((total_mb / 1024))
    local total_gb_frac=$(( (total_mb % 1024) * 10 / 1024 ))
    local total_gb_display="${total_gb_int}.${total_gb_frac}"
    local status
    status=$(get_context_fit_status "$total_mb" "$avail_mb")
    
    local status_icon status_color
    case "$status" in
        ok)
            status_icon="✓"
            status_color="${GREEN}"
            ;;
        borderline)
            status_icon="⚠"
            status_color="${YELLOW}"
            ;;
        no)
            status_icon="✗"
            status_color="${RED}"
            ;;
    esac
    
    # Return: display_string|status|total_mb
    printf "%s %6d tokens (%3dK) - ~%sGB|%s|%d" "$status_icon" "$ctx" "$ctx_k" "$total_gb_display" "$status" "$total_mb"
}

# Interactive context selector
# Note: All display output goes to stderr, only the result goes to stdout
select_context_size() {
    local model_path="$1"
    local current_context="$2"
    local gpu_id="${3:-0}"
    local model_id="${4:-}"  # Optional model ID for saving to metadata
    
    # Get VRAM details
    local vram_details
    vram_details=$(get_vram_details "$gpu_id" 2>/dev/null)
    if [[ -z "$vram_details" ]]; then
        print_error "Could not detect VRAM. Is rocm-smi available?" >&2
        return 1
    fi
    
    IFS='|' read -r total_mb used_mb avail_mb <<< "$vram_details"
    
    # Get model info (cross-platform)
    local model_size_bytes model_size_mb model_vram_mb estimated_params_b kv_per_1k_mb
    model_size_bytes=$(get_file_size "$model_path")
    if [[ -z "$model_size_bytes" ]]; then
        print_error "Could not get model file size" >&2
        return 1
    fi
    
    model_size_mb=$((model_size_bytes / 1024 / 1024))
    model_vram_mb=$((model_size_mb * 102 / 100))
    estimated_params_b=$((model_size_bytes * 100 / 56 / 1000000000))
    if [[ $estimated_params_b -lt 1 ]]; then estimated_params_b=1; fi
    kv_per_1k_mb=$((estimated_params_b * 8))
    if [[ $kv_per_1k_mb -lt 64 ]]; then kv_per_1k_mb=64; fi
    
    local headroom_mb=800
    
    echo >&2
    echo -e "${CYAN}${BOLD}Context Size Selection${NC}" >&2
    echo >&2
    echo -e "  ${BOLD}Model:${NC}      $(basename "$model_path")" >&2
    echo -e "  ${BOLD}GPU VRAM:${NC}   $((total_mb / 1024))GB total, $((avail_mb / 1024))GB available" >&2
    echo -e "  ${BOLD}Model:${NC}      ~$((model_vram_mb / 1024))GB (est. ${estimated_params_b}B params)" >&2
    echo >&2
    echo -e "  ${GREEN}✓${NC} = fits    ${YELLOW}⚠${NC} = borderline    ${RED}✗${NC} = won't fit" >&2
    echo >&2
    
    # Common context sizes
    # Use total VRAM for fit calculation (user expectation based on card specs)
    local context_sizes=(2048 4096 8192 16384 32768 65536 131072)
    local options=()
    local statuses=()
    
    for ctx in "${context_sizes[@]}"; do
        local formatted
        # Use total_mb (not avail_mb) for fit status - matches user expectation based on card specs
        formatted=$(format_context_option "$ctx" "$model_vram_mb" "$kv_per_1k_mb" "$total_mb" "$headroom_mb")
        local display status _total
        IFS='|' read -r display status _total <<< "$formatted"
        options+=("$display")
        statuses+=("$status")
    done
    
    # Add custom option
    options+=("  Custom context size...")
    
    local selected_idx
    if [[ "$HAS_GUM" == true ]]; then
        local selected
        selected=$(printf '%s\n' "${options[@]}" | gum choose --header "Select context size:")
        # Find index
        for i in "${!options[@]}"; do
            if [[ "${options[$i]}" == "$selected" ]]; then
                selected_idx=$i
                break
            fi
        done
    else
        echo "Context sizes:" >&2
        for i in "${!options[@]}"; do
            local marker=""
            if [[ $i -lt ${#context_sizes[@]} && ${context_sizes[$i]} -eq $current_context ]]; then
                marker=" (current)"
            fi
            echo "  $((i + 1))) ${options[$i]}${marker}" >&2
        done
        echo >&2
        read -p "Select [1-${#options[@]}]: " selected_idx </dev/tty
        selected_idx=$((selected_idx - 1))
    fi
    
    # Handle selection
    if [[ $selected_idx -ge 0 && $selected_idx -lt ${#context_sizes[@]} ]]; then
        local chosen_ctx="${context_sizes[$selected_idx]}"
        local chosen_status="${statuses[$selected_idx]}"
        
        if [[ "$chosen_status" == "no" ]]; then
            echo >&2
            echo -e "${YELLOW}Warning: ${chosen_ctx} context likely won't fit in VRAM${NC}" >&2
            local confirm=""
            if [[ "$HAS_GUM" == true ]]; then
                if gum confirm "Use anyway?"; then
                    confirm="y"
                fi
            else
                read -p "Use anyway? [y/N]: " confirm </dev/tty
            fi
            if [[ ! "$confirm" =~ ^[Yy] ]]; then
                echo "Cancelled." >&2
                return 1
            fi
        fi
        
        # Save the choice for future runs (if model_id is known)
        if [[ -n "$model_id" ]]; then
            if set_model_context "$model_id" "$chosen_ctx"; then
                echo -e "${DIM}Saved context preference to models-metadata.conf${NC}" >&2
            fi
        fi
        
        echo "$chosen_ctx"
        return 0
    elif [[ $selected_idx -eq ${#context_sizes[@]} ]]; then
        # Custom
        local custom_ctx
        if [[ "$HAS_GUM" == true ]]; then
            custom_ctx=$(gum input --placeholder "Enter context size (e.g., 8192)")
        else
            read -p "Enter context size: " custom_ctx </dev/tty
        fi
        if [[ "$custom_ctx" =~ ^[0-9]+$ ]]; then
            # Save the choice for future runs (if model_id is known)
            if [[ -n "$model_id" ]]; then
                if set_model_context "$model_id" "$custom_ctx"; then
                    echo -e "${DIM}Saved context preference to models-metadata.conf${NC}" >&2
                fi
            fi
            
            echo "$custom_ctx"
            return 0
        else
            print_error "Invalid context size" >&2
            return 1
        fi
    fi
    
    return 1
}

check_and_recommend_context() {
    local model_path="$1"
    local requested_context="$2"
    local model_id="${3:-}"  # Optional model ID for saving to metadata
    
    # Get VRAM details
    local gpu_for_check="${GPU_ID:-0}"
    local vram_details
    vram_details=$(get_vram_details "$gpu_for_check" 2>/dev/null) || return 0
    
    IFS='|' read -r total_mb used_mb avail_mb <<< "$vram_details"
    
    if [[ -z "$total_mb" || "$total_mb" -le 0 ]]; then
        return 0  # Skip if can't determine VRAM
    fi
    
    # Get context estimation - use total VRAM (matches card specs / user expectation)
    local estimate
    estimate=$(estimate_context_for_vram "$model_path" "$total_mb" "$requested_context" 2>/dev/null) || return 0
    
    IFS='|' read -r max_context model_vram_mb total_requested_mb estimated_params kv_per_1k <<< "$estimate"
    
    if [[ -z "$max_context" || -z "$kv_per_1k" || "$kv_per_1k" -le 0 ]]; then
        return 0
    fi
    
    # Calculate KV cache size for display
    local requested_kv_mb=$(( (requested_context / 1024) * kv_per_1k ))
    local headroom_mb=800
    
    # Get fit status - use total VRAM (matches card specs / user expectation)
    local fit_status
    fit_status=$(get_context_fit_status "$total_requested_mb" "$total_mb")
    
    local status_icon status_color status_text
    case "$fit_status" in
        ok)
            status_icon="✓"
            status_color="${GREEN}"
            status_text="fits"
            ;;
        borderline)
            status_icon="⚠"
            status_color="${YELLOW}"
            status_text="borderline"
            ;;
        no)
            status_icon="✗"
            status_color="${RED}"
            status_text="won't fit"
            ;;
    esac
    
    # Display VRAM analysis
    echo -e "${CYAN}${BOLD}VRAM Analysis${NC}"
    echo
    echo -e "  ${BOLD}GPU VRAM:${NC}      $((total_mb / 1024))GB total, $((avail_mb / 1024))GB available"
    echo -e "  ${BOLD}Model size:${NC}    ~$((model_vram_mb / 1024))GB (est. ${estimated_params}B params)"
    echo -e "  ${BOLD}KV cache:${NC}      ~$((requested_kv_mb / 1024))GB for ${requested_context} context"
    echo -e "  ${BOLD}Total needed:${NC}  ~$((total_requested_mb / 1024))GB"
    echo -e "  ${BOLD}Status:${NC}        ${status_color}${status_icon} ${status_text}${NC}"
    echo
    
    # Check if model won't fit at all
    if [[ "$max_context" -eq 0 ]]; then
        echo -e "${RED}${BOLD}ERROR: Model too large for available VRAM${NC}"
        echo
        echo "  Model needs ~$((model_vram_mb / 1024))GB but only $((total_mb / 1024))GB total."
        echo
        echo "Options:"
        echo "  1. Use a smaller quantization (e.g., Q3_K_S instead of Q4_K_M)"
        echo "  2. Use a smaller model (e.g., 8B instead of 32B)"
        echo "  3. Free up VRAM: ./start-server.sh --cleanup"
        echo
        exit 1
    fi
    
    # If fits or borderline, continue (with warning for borderline)
    if [[ "$fit_status" == "ok" ]]; then
        return 0
    fi
    
    if [[ "$fit_status" == "borderline" ]]; then
        echo -e "${YELLOW}Note: This is close to your VRAM limit. May fail under heavy load.${NC}"
        echo
        
        local choice=""
        if [[ "$HAS_GUM" == true ]]; then
            choice=$(gum choose \
                "Continue with ${requested_context}" \
                "Select different context size" \
                "Cancel")
        else
            echo "Options:"
            echo "  1) Continue with ${requested_context} context"
            echo "  2) Select different context size"
            echo "  3) Cancel"
            echo
            read -p "Choice [1]: " choice
            case "$choice" in
                2) choice="Select different context size" ;;
                3) choice="Cancel" ;;
                *) choice="Continue with ${requested_context}" ;;
            esac
        fi
        
        case "$choice" in
            "Continue"*)
                return 0
                ;;
            "Select"*)
                local new_ctx
                new_ctx=$(select_context_size "$model_path" "$requested_context" "$gpu_for_check" "$model_id")
                if [[ -n "$new_ctx" ]]; then
                    LLAMA_CONTEXT="$new_ctx"
                    echo -e "${GREEN}Using context size: ${new_ctx}${NC}"
                fi
                ;;
            "Cancel")
                echo "Cancelled."
                exit 0
                ;;
        esac
        echo
        return 0
    fi
    
    # Won't fit - must choose different context
    echo -e "${RED}${BOLD}Requested context won't fit in VRAM${NC}"
    echo
    echo "  Requested: ${requested_context} tokens (~$((total_requested_mb / 1024))GB)"
    echo "  GPU VRAM:  $((total_mb / 1024))GB"
    echo "  Safe max:  ${max_context} tokens"
    echo
    
    local choice=""
    if [[ "$HAS_GUM" == true ]]; then
        choice=$(gum choose \
            "Select context size (recommended)" \
            "Try ${requested_context} anyway (will likely fail)" \
            "Cancel")
    else
        echo "Options:"
        echo "  1) Select context size (recommended)"
        echo "  2) Try ${requested_context} anyway (will likely fail)"
        echo "  3) Cancel"
        echo
        read -p "Choice [1]: " choice
        case "$choice" in
            2) choice="Try ${requested_context} anyway" ;;
            3) choice="Cancel" ;;
            *) choice="Select context size" ;;
        esac
    fi
    
    case "$choice" in
        "Select"*)
            local new_ctx
            new_ctx=$(select_context_size "$model_path" "$requested_context" "$gpu_for_check" "$model_id")
            if [[ -n "$new_ctx" ]]; then
                LLAMA_CONTEXT="$new_ctx"
                echo -e "${GREEN}Using context size: ${new_ctx}${NC}"
            else
                exit 1
            fi
            ;;
        "Try"*)
            echo -e "${YELLOW}Keeping requested context: ${requested_context}${NC}"
            echo "Note: Server will likely fail with out-of-memory error"
            ;;
        "Cancel")
            echo "Cancelled."
            exit 0
            ;;
    esac
    echo
}

# Handle --context-menu flag (interactive context selector)
if [[ "$CONTEXT_MENU" == true ]]; then
    selected_ctx=$(select_context_size "$GGUF_PATH" "$LLAMA_CONTEXT" "${GPU_ID:-0}" "$MODEL_ID")
    if [[ -n "$selected_ctx" ]]; then
        LLAMA_CONTEXT="$selected_ctx"
        echo
        echo -e "${GREEN}Selected context: ${LLAMA_CONTEXT}${NC}"
        echo
        # Skip the normal VRAM check since we just did the interactive selection
        SKIP_VRAM_CHECK=true
    else
        exit 1
    fi
fi

# Check context size fits in VRAM
if [[ "$SKIP_VRAM_CHECK" != true ]]; then
    check_and_recommend_context "$GGUF_PATH" "$LLAMA_CONTEXT" "$MODEL_ID"
fi

# Set up GPU selection for multi-GPU systems
if [[ -n "$GPU_ID" ]]; then
    if [[ "$IS_LINUX" == true ]]; then
        export HIP_VISIBLE_DEVICES="$GPU_ID"
    fi
    export CUDA_VISIBLE_DEVICES="$GPU_ID"
fi

# Build command
CMD=(
    "$LLAMA_SERVER"
    -m "$GGUF_PATH"
    --host "$LLAMA_HOST"
    --port "$LLAMA_PORT"
    -c "$LLAMA_CONTEXT"
    -ngl "$GPU_LAYERS"
)

if [[ -n "$FLASH_ATTN" ]]; then
    CMD+=("$FLASH_ATTN")
fi

if [[ -n "$BATCH_SIZE" ]]; then
    CMD+=(-b "$BATCH_SIZE")
fi

if [[ -n "$THREADS" ]]; then
    CMD+=(-t "$THREADS")
fi

if [[ -n "$PARALLEL" ]]; then
    CMD+=(--parallel "$PARALLEL")
fi

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi

# Benchmark function
run_benchmark() {
    local endpoint="http://$LLAMA_HOST:$LLAMA_PORT"
    
    echo
    echo -e "${CYAN}${BOLD}Running Quick Benchmark...${NC}"
    echo
    
    # Wait for server to be ready
    local max_wait=60
    local waited=0
    echo -n "Waiting for server to be ready..."
    while ! curl -sf "$endpoint/health" &>/dev/null; do
        sleep 1
        ((waited++))
        if [[ $waited -ge $max_wait ]]; then
            echo
            echo -e "${RED}Server didn't start within ${max_wait}s${NC}"
            return 1
        fi
        echo -n "."
    done
    echo -e " ${GREEN}Ready!${NC}"
    echo
    
    # Simple generation benchmark
    local prompt="Write a short haiku about programming."
    local start_time end_time duration
    
    echo "Prompt: \"$prompt\""
    echo
    
    start_time=$(date +%s.%N)
    
    local response
    response=$(curl -sf "$endpoint/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "test",
            "messages": [{"role": "user", "content": "'"$prompt"'"}],
            "max_tokens": 100,
            "temperature": 0.7
        }' 2>/dev/null)
    
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc)
    
    if [[ -n "$response" ]]; then
        local content
        content=$(echo "$response" | jq -r '.choices[0].message.content // empty' 2>/dev/null)
        local tokens
        tokens=$(echo "$response" | jq -r '.usage.completion_tokens // 0' 2>/dev/null)
        
        if [[ -n "$content" ]]; then
            echo -e "${GREEN}Response:${NC}"
            echo "$content"
            echo
            echo -e "${CYAN}Stats:${NC}"
            echo "  Time: ${duration}s"
            if [[ "$tokens" != "0" && "$tokens" != "null" ]]; then
                local tps
                tps=$(echo "scale=2; $tokens / $duration" | bc 2>/dev/null || echo "?")
                echo "  Tokens: $tokens"
                echo "  Speed: ~${tps} tokens/sec"
            fi
        else
            echo -e "${YELLOW}Got response but couldn't parse content${NC}"
        fi
    else
        echo -e "${RED}Benchmark failed - no response${NC}"
    fi
    
    echo
}

# Print startup info
echo
echo -e "${CYAN}${BOLD}════════════════════════════════════════════${NC}"
echo -e "${CYAN}${BOLD}  llama-server${NC}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════════${NC}"
echo

# Get and display model info
MODEL_INFO=$(get_model_info "$GGUF_PATH")
IFS='|' read -r MODEL_SIZE MODEL_DESC MODEL_CATEGORY <<< "$MODEL_INFO"

echo -e "  ${BOLD}Model:${NC}    ${GREEN}$(basename "$GGUF_PATH")${NC}"
[[ -n "$MODEL_SIZE" ]] && echo -e "  ${BOLD}Size:${NC}     $MODEL_SIZE"
[[ -n "$MODEL_DESC" ]] && echo -e "  ${BOLD}Type:${NC}     $MODEL_DESC"
[[ -n "$MODEL_CATEGORY" ]] && echo -e "  ${BOLD}Category:${NC} $MODEL_CATEGORY"
echo
echo -e "  ${BOLD}Endpoint:${NC} ${GREEN}http://$LLAMA_HOST:$LLAMA_PORT${NC}"
echo -e "  ${BOLD}Context:${NC}  $LLAMA_CONTEXT tokens"
echo -e "  ${BOLD}GPU:${NC}      $GPU_LAYERS layers"
[[ -n "$GPU_ID" ]] && echo -e "  ${BOLD}GPU ID:${NC}   $GPU_ID"
[[ "$IS_LINUX" == true && -n "${HSA_OVERRIDE_GFX_VERSION:-}" ]] && echo -e "  ${BOLD}HSA:${NC}      $HSA_OVERRIDE_GFX_VERSION"
[[ -n "$BATCH_SIZE" ]] && echo -e "  ${BOLD}Batch:${NC}    $BATCH_SIZE"
[[ -n "$THREADS" ]] && echo -e "  ${BOLD}Threads:${NC}  $THREADS"
[[ -n "$PARALLEL" ]] && echo -e "  ${BOLD}Parallel:${NC} $PARALLEL"
[[ -n "$LOG_FILE" ]] && echo -e "  ${BOLD}Log:${NC}      $LOG_FILE"
[[ "$WATCHDOG_MODE" == true ]] && echo -e "  ${BOLD}Watchdog:${NC} ${GREEN}enabled${NC}"
echo

if [[ "$RUN_BENCHMARK" == true ]]; then
    # Run server in background, then benchmark
    echo -e "${YELLOW}Starting server for benchmark...${NC}"
    if [[ -n "$LOG_FILE" ]]; then
        "${CMD[@]}" >> "$LOG_FILE" 2>&1 &
    else
        "${CMD[@]}" &
    fi
    SERVER_PID=$!
    
    # Give server time to initialize
    sleep 3
    
    # Run benchmark
    run_benchmark
    
    echo -e "${YELLOW}Benchmark complete. Server running (PID: $SERVER_PID)${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
    echo
    
    # Wait for server
    wait $SERVER_PID
elif [[ "$WATCHDOG_MODE" == true ]]; then
    # Watchdog mode - auto-restart on crash
    echo -e "${YELLOW}Watchdog mode enabled - server will auto-restart on crash${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo
    
    RESTART_COUNT=0
    MAX_RESTARTS=10
    RESTART_DELAY=5
    
    while true; do
        # Start server
        if [[ -n "$LOG_FILE" ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting server (restart #$RESTART_COUNT)" >> "$LOG_FILE"
            "${CMD[@]}" >> "$LOG_FILE" 2>&1 &
        else
            "${CMD[@]}" &
        fi
        SERVER_PID=$!
        
        # Wait for server to exit
        wait $SERVER_PID
        EXIT_CODE=$?
        
        # Check if it was a normal exit (user Ctrl+C)
        if [[ $EXIT_CODE -eq 0 || $EXIT_CODE -eq 130 ]]; then
            echo
            print_status "Server stopped normally"
            break
        fi
        
        # Server crashed
        ((RESTART_COUNT++))
        
        if [[ $RESTART_COUNT -ge $MAX_RESTARTS ]]; then
            echo
            print_error "Server crashed $RESTART_COUNT times. Giving up."
            [[ -n "$LOG_FILE" ]] && echo "[$(date '+%Y-%m-%d %H:%M:%S')] Giving up after $RESTART_COUNT crashes" >> "$LOG_FILE"
            exit 1
        fi
        
        echo
        print_warning "Server crashed (exit code: $EXIT_CODE). Restarting in ${RESTART_DELAY}s... (attempt $RESTART_COUNT/$MAX_RESTARTS)"
        [[ -n "$LOG_FILE" ]] && echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server crashed with exit code $EXIT_CODE" >> "$LOG_FILE"
        
        sleep $RESTART_DELAY
    done
else
    echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
    echo -e "${YELLOW}Server ready when you see: \"server is listening\"${NC}"
    echo
    
    # Run server with optional logging
    if [[ -n "$LOG_FILE" ]]; then
        echo -e "${DIM}Logging to: $LOG_FILE${NC}"
        echo
        # Run in foreground but tee to log file
        exec "${CMD[@]}" 2>&1 | tee -a "$LOG_FILE"
    else
        # Run server (exec replaces this process)
        exec "${CMD[@]}"
    fi
fi
