#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp Server Start Script
# Cross-platform script to start llama-server with proper GPU settings
# Supports: Linux (ROCm/HIP) and macOS (Metal)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

# MODELS_CONF is not in .env (always relative to script)
MODELS_CONF="$SCRIPT_DIR/models.conf"

# Load configuration (required, unless just showing help)
if ! has_help_arg "$@"; then
    if [[ -f "$SCRIPT_DIR/.env" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/.env"
        set +a
    else
        echo "Error: .env file not found. Run ./setup.sh first." >&2
        exit 1
    fi

    # Validate required .env variables
    missing_vars=()
    [[ -z "${LLAMA_CPP_DIR:-}" ]] && missing_vars+=("LLAMA_CPP_DIR")
    [[ -z "${MODELS_DIR:-}" ]] && missing_vars+=("MODELS_DIR")
    [[ -z "${LLAMA_PORT:-}" ]] && missing_vars+=("LLAMA_PORT")
    [[ -z "${GPU_LAYERS:-}" ]] && missing_vars+=("GPU_LAYERS")

    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo "Error: Missing required variables in .env: ${missing_vars[*]}" >&2
        echo "Run ./setup.sh to regenerate .env" >&2
        exit 1
    fi
fi

# =============================================================================
# Model Metadata Configuration
# =============================================================================

# Get context limit for a model from models.conf
# Format: category|model_id|huggingface_repo|gguf_filename|size|description|context_limit|output_limit
# Usage: get_model_context <model_id> [default_value]
get_model_context() {
    local model_id="$1"
    local default="${2:-32768}"
    
    if [[ ! -f "$MODELS_CONF" ]]; then
        echo "$default"
        return
    fi
    
    local category
    
    # Parse models.conf to find the model entry
    while IFS='|' read -r cat mid _ _ _ _ ctx _ || [[ -n "$cat" ]]; do
        [[ "$cat" =~ ^[[:space:]]*# ]] && continue
        [[ "$cat" =~ ^ALIAS: ]] && continue
        [[ -z "$cat" ]] && continue
        
        # Trim model_id
        mid="${mid#"${mid%%[![:space:]]*}"}"
        mid="${mid%"${mid##*[![:space:]]}"}"
        
        if [[ "$mid" == "$model_id" ]]; then
            # Trim context
            ctx="${ctx#"${ctx%%[![:space:]]*}"}"
            ctx="${ctx%"${ctx##*[![:space:]]}"}"
            category="${cat#"${cat%%[![:space:]]*}"}"
            category="${category%"${category##*[![:space:]]}"}"
            
            if [[ -n "$ctx" && "$ctx" =~ ^[0-9]+$ ]]; then
                echo "$ctx"
                return
            fi
            
            # No explicit context, use category-based default
            case "$category" in
                coding)  echo "65536" ;;
                vision)  echo "16384" ;;
                *)       echo "$default" ;;
            esac
            return
        fi
    done < "$MODELS_CONF"
    
    echo "$default"
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
    print_banner "llama.cpp Server Launcher"

    echo "Usage: ./start-server.sh [OPTIONS] <model-id>"
    echo
    echo "Arguments:"
    echo "  model-id          Model ID from models.conf (e.g., qwen3-8b-q4km)"
    echo "                    Or an alias (e.g., qwen3, fast, coder)"
    echo "                    Or path to a .gguf file"
    echo
    echo "Options:"
    echo "  --gpu GPU_ID      Override GPU ID for multi-GPU systems"
    echo "  --watchdog        Auto-restart server on crash"
    echo "  --benchmark       Run quick benchmark after server starts"
    echo "  --no-rag          Don't auto-start RAG server"
    echo "  --list            List available models"
    echo "  --health          Check if server is running and healthy"
    echo "  --cleanup         Kill existing llama processes and free VRAM"
    echo "  --status          Show GPU/VRAM status"
    echo "  --no-update-check Skip checking for llama.cpp updates"
    echo "  --help            Show this help message"
    echo
    echo "All settings (port, host, GPU, etc.) are configured in .env"
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
    echo "  ./start-server.sh qwen3              # Use alias"
    echo "  ./start-server.sh qwen3-8b-q4km      # Use full model name"
    echo "  ./start-server.sh --gpu 1 qwen3      # Use second GPU"
    echo "  ./start-server.sh --watchdog qwen3   # Auto-restart on crash"
    echo "  ./start-server.sh --benchmark qwen3  # Run benchmark after start"
    echo
}

list_models() {
    print_banner "Available Models"

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
        print_banner "$model_id" 15 69 "($size) - $description
    
Use this model:
    ${GREEN}${BOLD} ▶ ./start-server.sh $model_id${NC}"
    fi
    done < "$SCRIPT_DIR/models.conf"
    
    echo
    echo "Downloaded models are in: $MODELS_DIR"
    echo
}

# =============================================================================
# Health Check Function
# =============================================================================

check_health() {
    local host="${1:-$LLAMA_HOST}"
    local port="${2:-$LLAMA_PORT}"
    local endpoint="http://$host:$port"
    
    print_banner "Server Health Check"

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
                model_name=$(echo "$props_response" | jq -r '.model_path // .default_generation_settings.model // .model // empty' 2>/dev/null)
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
        while IFS='|' read -r category model_id hf_repo gguf_file size description _ _ || [[ -n "$category" ]]; do
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

# Note: Vision model functions (is_vision_model, detect_mmproj) are in lib/common.sh

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
        line_num=$((line_num + 1))
        
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
            errors=$((errors + 1))
        fi
        
        # Check for commas in description (breaks gum menus)
        if [[ "$line" == *","* ]]; then
            # Only warn if comma is in description field (last field)
            local desc_field
            desc_field=$(echo "$line" | cut -d'|' -f6)
            if [[ "$desc_field" == *","* ]]; then
                print_warning "models.conf line $line_num: comma in description may cause menu issues"
                errors=$((errors + 1))
            fi
        fi
    done < "$conf_file"
    
    return $errors
}

# Parse arguments
MODEL_PATH=""
EXTRA_ARGS=()
RUN_BENCHMARK=false
WATCHDOG_MODE=false
SKIP_UPDATE_CHECK=false
NO_RAG=false
GPU_ID=""
LOG_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu)
            GPU_ID="$2"
            shift 2
            ;;
        --watchdog)
            WATCHDOG_MODE=true
            shift
            ;;
        --no-update-check)
            SKIP_UPDATE_CHECK=true
            shift
            ;;
        --no-rag)
            NO_RAG=true
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
            print_banner "GPU/Memory Status"

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
            print_banner "Llama Server Processes"

            llama_procs=$(pgrep -af "llama-server" 2>/dev/null || true)
            if [[ -n "$llama_procs" ]]; then
                echo "$llama_procs"
            else
                echo "No llama-server processes running"
            fi
            echo
            exit 0
            ;;
        --help|-h)
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
    print_error "No model specified"
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
        print_error "Model '$MODEL_PATH' not found in models.conf"
        echo "Run './start-server.sh --list' to see available models"
        exit 1
    fi
    
    GGUF_PATH="$MODELS_DIR/$GGUF_FILE"
    
    if [[ ! -f "$GGUF_PATH" ]]; then
        print_error "Model file not downloaded: $GGUF_FILE"
        echo "Run './download-model.sh $MODEL_PATH' to download it"
        exit 1
    fi
fi

# Load context size from models.conf
if [[ -n "$MODEL_ID" ]]; then
    LLAMA_CONTEXT=$(get_model_context "$MODEL_ID" "32768")
else
    # Direct .gguf path - use default context
    LLAMA_CONTEXT=32768
fi

# =============================================================================
# Vision Model / mmproj Auto-Detection
# =============================================================================

# Auto-detect mmproj for vision models (if not manually specified)
if [[ -z "${MMPROJ_PATH:-}" ]] && is_vision_model "$GGUF_PATH"; then
    detected_mmproj=$(detect_mmproj "$GGUF_PATH" "$MODELS_DIR")
    if [[ -n "$detected_mmproj" ]]; then
        MMPROJ_PATH="$detected_mmproj"
        echo -e "${GREEN}Auto-detected mmproj:${NC} $(basename "$MMPROJ_PATH")"
    else
        echo
        print_warning "Vision model detected but no mmproj file found"
        echo
        echo "  Vision models require a multimodal projector (mmproj) file."
        echo "  The model will load but image processing won't work."
        echo
        echo "  To download mmproj files:"
        echo "    ./download-model.sh --add $(basename "$(dirname "$GGUF_PATH")")"
        echo
        echo "  Or manually specify with: --mmproj <path>"
        echo
    fi
fi

# Validate mmproj path if specified
if [[ -n "${MMPROJ_PATH:-}" && ! -f "$MMPROJ_PATH" ]]; then
    print_error "mmproj file not found: $MMPROJ_PATH"
    exit 1
fi

# Check llama-server exists
LLAMA_SERVER="$LLAMA_CPP_DIR/build/bin/llama-server"
if [[ ! -f "$LLAMA_SERVER" ]]; then
    print_error "llama-server not found at $LLAMA_SERVER"
    echo "Run './setup.sh' to build llama.cpp"
    exit 1
fi

# Set library path for shared libraries (llama.cpp now uses .so files)
export LD_LIBRARY_PATH="$LLAMA_CPP_DIR/build/bin:${LD_LIBRARY_PATH:-}"

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
    # Use pgrep -x for exact match on process name, avoiding self-match
    existing_pids=$(pgrep -x "llama-server" 2>/dev/null || true)
    
    if [[ -n "$existing_pids" ]]; then
        echo
        echo -e "${YELLOW}Warning: llama-server is already running${NC}"
        echo -e "  PIDs: $existing_pids"
        echo
        echo "This may cause port conflicts or VRAM issues."
        echo
        
        # In non-interactive mode, exit rather than prompting
        if [[ ! -t 0 ]]; then
            echo "Cancelled. Use a different port with -p or stop existing servers manually."
            exit 1
        fi
        
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
            
            # In non-interactive mode, skip this prompt
            if [[ ! -t 0 ]]; then
                echo "Continuing anyway (non-interactive mode)..."
            else
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
            fi
        else
            echo "No llama-server processes found. Other applications may be using VRAM."
            
            # In non-interactive mode, continue anyway
            if [[ ! -t 0 ]]; then
                echo "Continuing anyway (non-interactive mode)..."
            else
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
        fi
        echo
    fi
}

# Run checks
check_existing_processes
check_vram

# =============================================================================
# RAG Server
# =============================================================================

start_rag_services() {
    local rag_port="${RAG_PORT:-8081}"
    local rag_dir="$SCRIPT_DIR/rag"
    
    # Check if RAG is set up
    if [[ ! -d "$rag_dir/.venv" ]]; then
        print_warning "RAG not set up. Run './setup-rag.sh' to enable RAG support."
        return 0
    fi
    
    # Always check SearXNG first (whether RAG server is running or not)
    # Start SearXNG if Docker is available and container isn't running
    if command -v docker &>/dev/null && docker info &>/dev/null; then
        if ! docker ps --format '{{.Names}}' | grep -q '^searxng$'; then
            start_spinner "  Starting SearXNG Docker container... "
            # Remove any stopped container with the same name
            docker rm searxng &>/dev/null || true
            # Export UID/GID for docker-compose to run as current user
            export UID
            GID=$(id -g)
            export GID
            if docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d searxng &>/dev/null; then
                stop_spinner true "SearXNG Docker container started."
            else
                stop_spinner true "SearXNG Docker container skipped. Web search not available."
            fi
        else
            echo -e "  ${GREEN}✓${NC} SearXNG already running"
        fi
    fi
    
    # Check if RAG server is already running
    if curl -sf "http://127.0.0.1:$rag_port/health" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} RAG server already running on port $rag_port"
        return 0
    fi
    # Ensure data directory exists
    mkdir -p "$rag_dir/data"

    # Set HuggingFace cache to persist models
    export TRANSFORMERS_CACHE="$rag_dir/data/huggingface_cache"
    mkdir -p "$TRANSFORMERS_CACHE"

    echo -e "  ${CYAN}Starting RAG server...${NC}"
    echo -e "  ${DIM}Embedding model cache: $TRANSFORMERS_CACHE${NC}"
    
    # Run from SCRIPT_DIR so 'import rag' works
    # Use setsid to fully detach the process from this script
    pushd "$SCRIPT_DIR" > /dev/null
    setsid "$rag_dir/.venv/bin/python" -m uvicorn rag.server:app \
        --host 127.0.0.1 \
        --port "$rag_port" \
        --log-level warning \
        > "$rag_dir/data/server.log" 2>&1 &
    popd > /dev/null
    
    # Wait for RAG server to be ready (up to 60s for model downloading on first run and startup)
    start_spinner "Waiting for RAG server to be ready (http://127.0.0.1:$rag_port)..."
    local waited=0
    local max_wait=60

    while [[ $waited -lt $max_wait ]]; do
        if curl -sf "http://127.0.0.1:$rag_port/health" &>/dev/null; then
            stop_spinner true "RAG server started on port: $rag_port."
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    
    stop_spinner false "RAG server failed to start within ${max_wait}s. Check $rag_dir/data/server.log"
    echo -e "${DIM}Check logs: ${yellow}$rag_dir/data/server.log${NC}"
    echo -e "${DIM}View with: ${yellow}tail -f $rag_dir/data/server.log${NC}"
    echo -e "${DIM}Common issues: model download taking time, port $rag_port already in use, missing dependencies${NC}"
    
    # Show last few lines of log for debugging
    if [[ -f "$rag_dir/data/server.log" ]]; then
        echo -e "\n${YELLOW}Last 5 lines of RAG server log:${NC}"
        tail -5 "$rag_dir/data/server.log"
    fi
    
    return 1
}

# Determine if we should start RAG check
SHOULD_START_RAG=false 

if [[ "$NO_RAG" != true ]]; then
    # Check AUTO_START_RAG_SERVER env var (default: true if not set)
    if [[ "${AUTO_START_RAG_SERVER:-true}" == "true" ]]; then
        SHOULD_START_RAG=true
    fi
fi

if [[ "$SHOULD_START_RAG" == true ]]; then
    print_banner "Starting RAG Services"
    start_rag_services
fi

# -----------------------------------------------------------------------------
# Cleanup on Exit
# -----------------------------------------------------------------------------

# Track the llama-server PID for cleanup
LLAMA_SERVER_PID=""
# Track if cleanup has been done
cleanup_done=false

cleanup_on_exit() {
    if $cleanup_done; then
        return
    fi
    cleanup_done=true

    echo "" >&2  # newline after ^C
    print_banner "Cleaning up llama-server processes"

    # If we have the main server PID, kill it immediately
    if [[ -n "$LLAMA_SERVER_PID" ]]; then
        start_spinner "Stopping llama-server (PID: $LLAMA_SERVER_PID)..."
        
        # Send SIGTERM first (graceful shutdown)
        kill "$LLAMA_SERVER_PID" 2>/dev/null || true
        
        # Wait up to 3 seconds for graceful exit
        local timeout=3
        while kill -0 "$LLAMA_SERVER_PID" 2>/dev/null && (( timeout > 0 )); do
            sleep 0.5
            ((timeout--))
        done
        
        # If still running, force kill
        if kill -0 "$LLAMA_SERVER_PID" 2>/dev/null; then
            kill -9 "$LLAMA_SERVER_PID" 2>/dev/null || true
            sleep 0.5
        fi
        
        stop_spinner true "llama-server stopped."
    fi

    # Also kill any llama-server on our port (fallback)
    local llama_pid
    llama_pid=$(lsof -ti:"${LLAMA_PORT:-8080}" 2>/dev/null || true)
    if [[ -n "$llama_pid" ]]; then
        start_spinner "Stopping llama-server (fallback)..."
        kill "$llama_pid" 2>/dev/null || true
        sleep 0.5
        kill -9 "$llama_pid" 2>/dev/null || true
        stop_spinner true "llama-server (fallback) stopped."
    fi

    # Stop RAG server
    local rag_port="${RAG_PORT:-8081}"
    local rag_pid
    rag_pid=$(lsof -ti:"$rag_port" 2>/dev/null || true)
    if [[ -n "$rag_pid" ]]; then
        start_spinner "Stopping RAG server..."
        kill "$rag_pid" 2>/dev/null || true
        stop_spinner true "RAG server stopped."
    fi

    # Stop SearXNG container
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^searxng$'; then
        start_spinner "Stopping SearXNG..."
        docker stop searxng &>/dev/null || true
        stop_spinner true "SearXNG stopped."
    fi
    
    # Clean up temporary log file if it exists
    if [[ -n "${TEMP_LOG:-}" && -f "$TEMP_LOG" ]]; then
        rm -f "$TEMP_LOG"
    fi
    
    # Exit the script
    exit 0
}

trap cleanup_on_exit INT TERM

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

if [[ -n "${MMPROJ_PATH:-}" ]]; then
    CMD+=(--mmproj "$MMPROJ_PATH")
fi

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi

# Benchmark function
run_benchmark() {
    local endpoint="http://$LLAMA_HOST:$LLAMA_PORT"
    local server_pid="${1:-}"
    
    echo -e "${CYAN}${BOLD}Running Quick Benchmark...${NC}"
    echo
    
    # Wait for server to be ready
    local max_wait=60  
    local waited=0
    local health_checked=false
    
    echo -n "Waiting for server to be ready"
    
    while [[ $waited -lt $max_wait ]]; do
        # Try to connect to health endpoint
        if curl -sf --max-time 2 "$endpoint/health" &>/dev/null; then
            health_checked=true
            echo -e " ${GREEN}Ready!${NC}"
            echo
            break
        fi
        
        # Also check if the process is still running
        if [[ -n "$server_pid" ]] && ! kill -0 "$server_pid" 2>/dev/null; then
            echo -e " ${RED}Server process died!${NC}"
            echo "Check server logs for details."
            return 1
        fi
        
        # Show progress
        if [[ $waited -eq 0 ]]; then
            echo -n " (this can take up to ${max_wait}s)"
        fi
        
        echo -n "."
        sleep 1
        waited=$((waited + 1))
    done
    
    if [[ "$health_checked" != true ]]; then
        echo -e " ${RED}Server didn't respond within ${max_wait}s${NC}"
        
        # Check if process is still running
        if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
            echo -e "${YELLOW}Server is running but not responding to health checks${NC}"
            echo "This could mean:"
            echo "  1. The server is still loading the model"
            echo "  2. There's a configuration issue"
            echo "  3. The health endpoint is not enabled"
            echo
            
            # Try alternative endpoints
            echo -e "${YELLOW}Trying alternative endpoints...${NC}"
            if curl -sf --max-time 2 "$endpoint/" &>/dev/null; then
                echo -e "${GREEN}✓ Root endpoint responds${NC}"
            fi
            
            if curl -sf --max-time 2 "$endpoint/v1/models" &>/dev/null; then
                echo -e "${GREEN}✓ Models endpoint responds${NC}"
            fi

            # Show log tail to help debug
            if [[ -f "$BENCHMARK_LOG" ]]; then
                echo -e "\n${YELLOW}Last 5 lines of server log:${NC}"
                tail -5 "$BENCHMARK_LOG"
            fi
        fi
        
        return 1
    fi
    
    # Simple generation benchmark
    local prompt="Write a short haiku about programming."
    local start_time end_time duration
    
    echo "Prompt: \"$prompt\""
    echo
    
    # Try multiple endpoints - some servers use different APIs
    local response=""
    local endpoint_to_try=""
    
    # Try different endpoints in order
    for ep in "/v1/chat/completions" "/completion" "/api/generate"; do
        if curl -sf --max-time 30 "$endpoint$ep" \
            -H "Content-Type: application/json" \
            -d '{
                "model": "test",
                "messages": [{"role": "user", "content": "'"$prompt"'"}],
                "max_tokens": 100,
                "temperature": 0.7
            }' 2>/dev/null | head -c 10 &>/dev/null; then
            endpoint_to_try="$ep"
            break
        fi
    done
    
    if [[ -z "$endpoint_to_try" ]]; then
        echo -e "${YELLOW}No known API endpoint responded. Trying root completion...${NC}"
        endpoint_to_try="/completion"
    fi
    
    start_time=$(date +%s.%N)
    
    response=$(curl -sS --max-time 30 "$endpoint$endpoint_to_try" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -d '{
            "model": "test",
            "messages": [{"role": "user", "content": "'"$prompt"'"}],
            "max_tokens": 100,
            "temperature": 0.7
        }' 2>/dev/null || echo "{}")
    
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "?")
    
    # Try to parse response with jq if available
    if command -v jq &>/dev/null; then
        local content
        content=$(echo "$response" | jq -r '.choices[0].message.content // .content // .response // .text // empty' 2>/dev/null)
        local tokens
        tokens=$(echo "$response" | jq -r '.usage.completion_tokens // .tokens_generated // .tokens // 0' 2>/dev/null)
        
        if [[ -n "$content" && "$content" != "null" ]]; then
            echo -e "${GREEN}Response:${NC}"
            echo "$content" | fold -w 80
            echo
            echo -e "${CYAN}Stats:${NC}"
            echo "  Time: ${duration}s"
            if [[ "$tokens" != "0" && "$tokens" != "null" ]]; then
                local tps
                tps=$(echo "scale=2; $tokens / $duration" | bc 2>/dev/null || echo "?")
                echo "  Tokens: $tokens"
                echo "  Speed: ~${tps} tokens/sec"
            fi
            echo "  Endpoint: $endpoint_to_try"
        else
            echo -e "${YELLOW}Couldn't parse response content${NC}"
            echo -e "${DIM}Raw response preview:${NC}"
            echo "$response" | head -c 200
            echo "..."
            echo "  Time: ${duration}s"
        fi
    else
        # jq not available, show raw response
        echo -e "${YELLOW}Note: jq not available for JSON parsing${NC}"
        echo -e "${DIM}Raw response (first 500 chars):${NC}"
        echo "$response" | head -c 500
        echo "..."
        echo
        echo -e "${CYAN}Stats:${NC}"
        echo "  Time: ${duration}s"
    fi
    
    echo
    return 0
}

# Check for llama.cpp updates (uses cache, no network delay if checked recently)
if [[ "$SKIP_UPDATE_CHECK" != true ]]; then
    update_msg=$(check_llama_cpp_updates "$LLAMA_CPP_DIR" 2>/dev/null)
    if [[ -n "$update_msg" ]]; then
        show_update_notification "llama.cpp" "$update_msg" "./setup.sh --update"
        
        # Prompt user to update (only if running interactively)
        if [[ -t 0 ]]; then
            echo
            if [[ "$HAS_GUM" == true ]]; then
                if gum confirm "Update llama.cpp now?"; then
                    exec ./setup.sh --update
                fi
            else
                read -p "Update llama.cpp now? [y/N] " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    exec ./setup.sh --update
                fi
            fi
            
            # User declined - show warning
            echo
            print_warning "Continuing with outdated llama.cpp"
            echo -e "  ${YELLOW}Note:${NC} This may cause silent failures or unexpected behavior."
            echo -e "  ${YELLOW}      ${NC}If something breaks, try: ./setup.sh --update"
            echo
        fi
    fi
fi

# Show RAG status
if [[ "$SHOULD_START_RAG" == true ]]; then
    rag_port="${RAG_PORT:-8081}"
    if curl -sf "http://127.0.0.1:$rag_port/health" &>/dev/null; then
        RAG_STATUS="${GREEN}http://127.0.0.1:$rag_port${NC}"
    else
        RAG_STATUS="${YELLOW}not running${NC}"
    fi
else
    RAG_STATUS="${DIM}disabled${NC}"
fi

echo

if [[ "$RUN_BENCHMARK" == true ]]; then
    # Check if port is already in use BEFORE starting server
    if lsof -ti:"$LLAMA_PORT" &>/dev/null; then
        echo -e "${RED}Port $LLAMA_PORT is already in use!${NC}"
        echo "This could be from a previous run. Please free the port or use a different one."
        echo "You can use: ./start-server.sh --cleanup"
        exit 1
    fi

    # Create a log file for benchmark mode
    BENCHMARK_LOG=$(mktemp /tmp/llama-server-benchmark-XXXXXX.log)

    # Function to cleanup benchmark server
    cleanup_benchmark_server() {
        # If we have a server PID, kill it
        if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
            echo -e "${YELLOW}Killing benchmark server (PID: $SERVER_PID)...${NC}"
            kill "$SERVER_PID" 2>/dev/null || true
            sleep 1
            kill -9 "$SERVER_PID" 2>/dev/null || true
        fi
        
        # Also call the main cleanup for RAG and SearXNG
        if [[ "$cleanup_done" != true ]]; then
            cleanup_on_exit
        fi
    }
    
    # Trap for cleanup on script exit
    trap cleanup_benchmark_server EXIT

    # Run server in background, redirecting output to BENCHMARK_LOG file
    start_spinner "Starting llama-server in benchmark mode... "
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting server for benchmark" >> "$BENCHMARK_LOG"
    "${CMD[@]}" >> "$BENCHMARK_LOG" 2>&1 &
    SERVER_PID=$!
    LLAMA_SERVER_PID=$SERVER_PID  # Set for main cleanup function
    
    # Give server time to initialize
    sleep 3
    if kill -0 $SERVER_PID 2>/dev/null; then
        stop_spinner true "llama-server started (PID: $SERVER_PID)"
    else
        stop_spinner false "llama-server failed to start"
        echo "Last 10 lines of log:"
        tail -10 "$BENCHMARK_LOG"
        echo
        echo -e "${YELLOW}Full log at: $BENCHMARK_LOG${NC}"
        cleanup_benchmark_server
        exit 1
    fi

    # Show model info after server starts
    print_banner "llama-server (benchmark mode)"
    
    # Get and display model info
    MODEL_INFO=$(get_model_info "$GGUF_PATH")
    IFS='|' read -r MODEL_SIZE MODEL_DESC MODEL_CATEGORY <<< "$MODEL_INFO"
    
    echo -e "  ${BOLD}Model:${NC}    ${GREEN}$(basename "$GGUF_PATH")${NC}"
    [[ -n "$MODEL_SIZE" ]] && echo -e "  ${BOLD}Size:${NC}    ~$MODEL_SIZE"
    [[ -n "$MODEL_DESC" ]] && echo -e "  ${BOLD}Desc:${NC}     $MODEL_DESC"
    [[ -n "$MODEL_CATEGORY" ]] && echo -e "  ${BOLD}Category:${NC} $MODEL_CATEGORY"
    echo
    echo -e "  ${BOLD}Context:${NC}  $LLAMA_CONTEXT tokens"
    echo -e "  ${BOLD}GPU:${NC}      $GPU_LAYERS layers"
    [[ -n "$GPU_ID" ]] && echo -e "  ${BOLD}GPU ID:${NC}   $GPU_ID"
    [[ "$IS_LINUX" == true && -n "${HSA_OVERRIDE_GFX_VERSION:-}" ]] && echo -e "  ${BOLD}HSA:${NC}      $HSA_OVERRIDE_GFX_VERSION"
    [[ -n "${MMPROJ_PATH:-}" ]] && echo -e "  ${BOLD}mmproj:${NC}   $(basename "$MMPROJ_PATH")"
    echo -e "  ${BOLD}RAG:${NC}      $RAG_STATUS"
    echo -e "  ${BOLD}Endpoint:${NC} ${GREEN}http://$LLAMA_HOST:$LLAMA_PORT${NC}"
    echo

    # Run benchmark
    if [[ "$SHOULD_START_RAG" == true ]]; then
        # Wait a bit longer for RAG if it was just started
        echo -e "${CYAN}Waiting for RAG server to stabilize...${NC}"
        sleep 5
    fi

    if run_benchmark "$SERVER_PID"; then
        echo -e "${GREEN}✓ Benchmark completed successfully${NC}"
    else
        echo -e "${RED}✗ Benchmark failed${NC}"
        # Cleanup before exiting to ensure server & services are stopped
        cleanup_benchmark_server
        exit 1
    fi
    
    echo
    echo -e "${DIM}Server logs available at: ${YELLOW}$BENCHMARK_LOG${NC}"
    echo -e "${DIM}View with: ${YELLOW}tail -f \"$BENCHMARK_LOG\"${NC}"
    echo
    echo -e "${YELLOW}Benchmark complete. Server running (PID: $SERVER_PID)${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
    echo

    # Wait for server
    wait $SERVER_PID

    # Clean up after normal exit
    cleanup_benchmark_server
    exit 0
elif [[ "$WATCHDOG_MODE" == true ]]; then
    # Create a log file for watchdog mode
    WATCHDOG_LOG=$(mktemp /tmp/llama-server-watchdog-XXXXXX.log)
    
    RESTART_COUNT=0
    MAX_RESTARTS=10
    RESTART_DELAY=5

    while true; do
        # Start server with output to watchdog log file
        start_spinner "Starting llama-server in watchdog mode... "
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting server (restart #$RESTART_COUNT)" >> "$WATCHDOG_LOG"
        "${CMD[@]}" >> "$WATCHDOG_LOG" 2>&1 &
        SERVER_PID=$!
        
        # Wait a bit to see if server starts successfully
        sleep 5

        if kill -0 $SERVER_PID 2>/dev/null; then
            stop_spinner true "llama-server started (PID: $SERVER_PID)"
            
            # Show model info after server starts
            print_banner "llama-server (watchdog mode)"
            
            # Get and display model info
            MODEL_INFO=$(get_model_info "$GGUF_PATH")
            IFS='|' read -r MODEL_SIZE MODEL_DESC MODEL_CATEGORY <<< "$MODEL_INFO"
            
            echo -e "  ${BOLD}Model:${NC}    ${GREEN}$(basename "$GGUF_PATH")${NC}"
            [[ -n "$MODEL_SIZE" ]] && echo -e "  ${BOLD}Size:${NC}    ~$MODEL_SIZE"
            [[ -n "$MODEL_DESC" ]] && echo -e "  ${BOLD}Desc:${NC}     $MODEL_DESC"
            [[ -n "$MODEL_CATEGORY" ]] && echo -e "  ${BOLD}Category:${NC} $MODEL_CATEGORY"
            echo
            echo -e "  ${BOLD}Context:${NC}  $LLAMA_CONTEXT tokens"
            echo -e "  ${BOLD}GPU:${NC}      $GPU_LAYERS layers"
            [[ -n "$GPU_ID" ]] && echo -e "  ${BOLD}GPU ID:${NC}   $GPU_ID"
            [[ "$IS_LINUX" == true && -n "${HSA_OVERRIDE_GFX_VERSION:-}" ]] && echo -e "  ${BOLD}HSA:${NC}      $HSA_OVERRIDE_GFX_VERSION"
            [[ -n "${MMPROJ_PATH:-}" ]] && echo -e "  ${BOLD}mmproj:${NC}   $(basename "$MMPROJ_PATH")"
            echo -e "  ${BOLD}RAG:${NC}      $RAG_STATUS"
            echo -e "  ${BOLD}Endpoint:${NC} ${GREEN}http://$LLAMA_HOST:$LLAMA_PORT${NC}"
            echo
            # Show log location
            echo -e "${DIM}Server logs: ${YELLOW}$WATCHDOG_LOG${NC}"
            echo -e "${DIM}View with: ${YELLOW}tail -f \"$WATCHDOG_LOG\"${NC}"
            echo
            # Watchdog mode - auto-restart on crash
            echo -e "${YELLOW}Watchdog mode enabled - server will auto-restart on crash${NC}"
            echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
            echo

            # Wait for server to exit
            wait $SERVER_PID
            EXIT_CODE=$?
        else
                stop_spinner false "llama-server failed to start"
                # Show last few lines of log
                echo -e "${DIM}Last 10 lines of log:${NC}"
                tail -10 "$WATCHDOG_LOG"
                EXIT_CODE=1
        fi
        
        # Server crashed
        RESTART_COUNT=$((RESTART_COUNT + 1))
        
       # When max restarts reached
        if [[ $RESTART_COUNT -ge $MAX_RESTARTS ]]; then
            echo
            print_error "Server crashed $RESTART_COUNT times. Giving up."
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Giving up after $RESTART_COUNT crashes" >> "$WATCHDOG_LOG"
            echo -e "${YELLOW}Debug log preserved: $WATCHDOG_LOG${NC}"
            echo -e "${YELLOW}Check for error patterns: grep -i error \"$WATCHDOG_LOG\"${NC}"
            echo
        exit 1
        fi
        
        echo
        print_warning "Server crashed (exit code: $EXIT_CODE). Restarting in ${RESTART_DELAY}s... (attempt $RESTART_COUNT/$MAX_RESTARTS)"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server crashed with exit code $EXIT_CODE" >> "$WATCHDOG_LOG"
        
        sleep $RESTART_DELAY
    done
else
    # Final check for port availability before starting server
    if lsof -ti:"$LLAMA_PORT" &>/dev/null; then
        echo -e "${RED}Port $LLAMA_PORT is already in use!${NC}"
        echo "This could be from a previous run. Please free the port or use a different one."
        echo "You can use: ./start-server.sh --cleanup"
        exit 1
    fi

    print_banner "Starting llama-server"
    # Create a temporary log file 
    if [[ -z "$LOG_FILE" ]]; then
        TEMP_LOG="/tmp/llama-server-$(date +%s).log"
    fi
    
    # Run server in background, capture PID, and check if it started successfully
    start_spinner "Starting llama-server... "
    if [[ -n "$LOG_FILE" ]]; then
        # Start the process and capture its PID directly
        exec 3>&1  # Save stdout
        "${CMD[@]}" > "$LOG_FILE" 2>&1 &
        LLAMA_SERVER_PID=$!
        exec 3>&-  # Close the file descriptor
    else
        "${CMD[@]}" > "$TEMP_LOG" 2>&1 &
        LLAMA_SERVER_PID=$!
    fi

    # Give it a moment to start, then check if it's running
    sleep 2

    if kill -0 $LLAMA_SERVER_PID 2>/dev/null; then
        stop_spinner true "llama-server started (PID: $LLAMA_SERVER_PID)"
        echo -e "${DIM}Server output in: ${YELLOW}${LOG_FILE:-$TEMP_LOG}${NC}"
        echo -e "${DIM}View with: ${YELLOW}tail -f \"${LOG_FILE:-$TEMP_LOG}\"${NC}"
        echo
        
        print_banner "llama-server info"
        
        # Get and display model info
        MODEL_INFO=$(get_model_info "$GGUF_PATH")
        IFS='|' read -r MODEL_SIZE MODEL_DESC MODEL_CATEGORY <<< "$MODEL_INFO"
        
        echo -e "  ${BOLD}Model:${NC}    ${GREEN}$(basename "$GGUF_PATH")${NC}"
        [[ -n "$MODEL_SIZE" ]] && echo -e "  ${BOLD}Size:${NC}    ~$MODEL_SIZE"
        [[ -n "$MODEL_DESC" ]] && echo -e "  ${BOLD}Desc:${NC}     $MODEL_DESC"
        [[ -n "$MODEL_CATEGORY" ]] && echo -e "  ${BOLD}Category:${NC} $MODEL_CATEGORY"
        echo
        echo -e "  ${BOLD}Context:${NC}  $LLAMA_CONTEXT tokens"
        echo -e "  ${BOLD}GPU:${NC}      $GPU_LAYERS layers"
        [[ -n "$GPU_ID" ]] && echo -e "  ${BOLD}GPU ID:${NC}   $GPU_ID"
        [[ "$IS_LINUX" == true && -n "${HSA_OVERRIDE_GFX_VERSION:-}" ]] && echo -e "  ${BOLD}HSA:${NC}      $HSA_OVERRIDE_GFX_VERSION"
        [[ -n "${MMPROJ_PATH:-}" ]] && echo -e "  ${BOLD}mmproj:${NC}   $(basename "$MMPROJ_PATH")"
        echo -e "  ${BOLD}RAG:${NC}      $RAG_STATUS"
        echo -e "  ${BOLD}Endpoint:${NC} ${GREEN}http://$LLAMA_HOST:$LLAMA_PORT${NC}"
        echo
    else
        stop_spinner false "llama-server failed to start"
        # Show the log to help debug
        if [[ -f "${LOG_FILE:-$TEMP_LOG}" ]]; then
            echo "Last 10 lines of log:"
            tail -10 "${LOG_FILE:-$TEMP_LOG}"
            echo
            echo -e "${YELLOW}Full log at: ${LOG_FILE:-$TEMP_LOG}${NC}"
        fi
        exit 1
    fi

      
    echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
    echo -e "${YELLOW}Server is listening on http://$LLAMA_HOST:$LLAMA_PORT${NC}"
    echo
    
    # Wait for server to exit
    while kill -0 $LLAMA_SERVER_PID 2>/dev/null; do
        wait $LLAMA_SERVER_PID 2>/dev/null || true
        sleep 1
    done
fi