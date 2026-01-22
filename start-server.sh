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
EXTRA_ARGS=()
RUN_BENCHMARK=false
WATCHDOG_MODE=false
SKIP_UPDATE_CHECK=false

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
if [[ -z "$MMPROJ_PATH" ]] && is_vision_model "$GGUF_PATH"; then
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
if [[ -n "$MMPROJ_PATH" && ! -f "$MMPROJ_PATH" ]]; then
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

if [[ -n "$MMPROJ_PATH" ]]; then
    CMD+=(--mmproj "$MMPROJ_PATH")
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

# Check for llama.cpp updates (uses cache, no network delay if checked recently)
if [[ "$SKIP_UPDATE_CHECK" != true ]]; then
    update_msg=$(check_llama_cpp_updates "$LLAMA_CPP_DIR" 2>/dev/null)
    if [[ -n "$update_msg" ]]; then
        show_update_notification "llama.cpp" "$update_msg" "./setup.sh --update"
    fi
fi

# Print startup info
print_banner "llama-server"

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
[[ -n "$MMPROJ_PATH" ]] && echo -e "  ${BOLD}mmproj:${NC}   $(basename "$MMPROJ_PATH")"
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
