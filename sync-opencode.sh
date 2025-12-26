#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Sync OpenCode Configuration
# =============================================================================
#
# Syncs downloaded models and agent files to OpenCode configuration.
#
# Usage:
#   ./sync-opencode.sh                  # Sync both models and agents
#   ./sync-opencode.sh --models         # Sync only model config (opencode.json)
#   ./sync-opencode.sh --agents         # Sync only agent files
#   ./sync-opencode.sh --restore        # Restore config from backup
#   ./sync-opencode.sh --dry-run        # Show what would be synced
#   ./sync-opencode.sh --help           # Show help
#
# =============================================================================

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source common library
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MODELS_CONF="$SCRIPT_DIR/models.conf"
# shellcheck disable=SC2034  # Used by load_metadata_conf() from common.sh
METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
MODELS_DIR="$SCRIPT_DIR/models"
OPENCODE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
OPENCODE_CONFIG_DIR="$(dirname "$OPENCODE_CONFIG")"

# Modes
SYNC_MODELS=false
SYNC_AGENTS=false
DRY_RUN=false
MERGE_MODE=false
RESTORE_MODE=false
RESTORE_LATEST=false
RESET_AGENTS=false

# Load .env for port config
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi

LLAMA_PORT="${LLAMA_PORT:-8080}"

# Default limits
DEFAULT_CONTEXT=32768
DEFAULT_OUTPUT=8192
CODING_CONTEXT=65536
CODING_OUTPUT=16384

# -----------------------------------------------------------------------------
# Parse Arguments
# -----------------------------------------------------------------------------

for arg in "$@"; do
    case $arg in
        --models)
            SYNC_MODELS=true
            ;;
        --agents)
            SYNC_AGENTS=true
            ;;
        --reset-agents)
            SYNC_AGENTS=true
            RESET_AGENTS=true
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        --merge)
            MERGE_MODE=true
            ;;
        --restore)
            RESTORE_MODE=true
            ;;
        --restore-latest)
            RESTORE_MODE=true
            RESTORE_LATEST=true
            ;;
        --help|-h)
            echo "Usage: ./sync-opencode.sh [OPTIONS]"
            echo
            echo "Syncs downloaded models and agent files to OpenCode configuration."
            echo
            echo "What to sync:"
            echo "  (default)         Sync both models and agents"
            echo "  --models          Sync only model config (opencode.json)"
            echo "  --agents          Sync only agent files (AGENTS.md, agent/*.md)"
            echo "  --reset-agents    Force reset agent files to defaults"
            echo
            echo "Model options:"
            echo "  --merge           Only add new models, keep existing config entries"
            echo "  --restore         List available config backups and restore one"
            echo "  --restore-latest  Restore the most recent config backup"
            echo
            echo "General options:"
            echo "  --dry-run         Show what would be synced without writing"
            echo "  --help, -h        Show this help message"
            echo
            echo "Files:"
            echo "  Config:  $OPENCODE_CONFIG"
            echo "  Agents:  $OPENCODE_CONFIG_DIR/AGENTS.md"
            echo "           $OPENCODE_CONFIG_DIR/agent/*.md"
            echo "  Models:  $MODELS_DIR/*.gguf"
            exit 0
            ;;
        *)
            print_error "Unknown option: $arg"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Default: sync both if neither specified
if [[ "$SYNC_MODELS" == false && "$SYNC_AGENTS" == false && "$RESTORE_MODE" == false ]]; then
    SYNC_MODELS=true
    SYNC_AGENTS=true
fi

# -----------------------------------------------------------------------------
# Load Model Metadata from models.conf
# -----------------------------------------------------------------------------

declare -A MODEL_ID_BY_FILE
declare -A MODEL_CATEGORY
declare -A MODEL_DESCRIPTION
declare -A MODEL_SIZE

# Metadata arrays (MODEL_DISPLAY_NAME, MODEL_CONTEXT_LIMIT, MODEL_OUTPUT_LIMIT)
# are declared in lib/common.sh

load_models_conf_local() {
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_warning "models.conf not found: $MODELS_CONF"
        return 1
    fi
    
    while IFS='|' read -r category model_id _hf_repo gguf_file size description || [[ -n "$category" ]]; do
        # Skip comments, empty lines, and aliases
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim whitespace
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
        gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
        size="${size#"${size%%[![:space:]]*}"}"
        size="${size%"${size##*[![:space:]]}"}"
        description="${description#"${description%%[![:space:]]*}"}"
        description="${description%"${description##*[![:space:]]}"}"
        
        MODEL_ID_BY_FILE["$gguf_file"]="$model_id"
        MODEL_CATEGORY["$model_id"]="$category"
        MODEL_DESCRIPTION["$model_id"]="$description"
        MODEL_SIZE["$model_id"]="$size"
    done < "$MODELS_CONF"
}

# load_metadata_conf() is now in lib/common.sh

# -----------------------------------------------------------------------------
# Get Downloaded Models
# -----------------------------------------------------------------------------

get_downloaded_models() {
    local -a models=()
    
    if [[ ! -d "$MODELS_DIR" ]]; then
        return
    fi
    
    for gguf_file in "$MODELS_DIR"/*.gguf; do
        [[ -f "$gguf_file" ]] || continue
        
        local filename
        filename=$(basename "$gguf_file")
        
        # Look up model ID from filename
        local model_id="${MODEL_ID_BY_FILE[$filename]:-}"
        
        if [[ -n "$model_id" ]]; then
            models+=("$model_id")
        else
            # Unknown model - use filename without extension as ID
            model_id="${filename%.gguf}"
            model_id="${model_id,,}"  # lowercase
            models+=("$model_id")
            # Store metadata for unknown models
            MODEL_CATEGORY["$model_id"]="unknown"
            MODEL_DESCRIPTION["$model_id"]="$filename"
            local fsize
            fsize=$(du -h "$gguf_file" | cut -f1)
            MODEL_SIZE["$model_id"]="$fsize"
        fi
    done
    
    echo "${models[@]}"
}

# -----------------------------------------------------------------------------
# Generate OpenCode Config
# -----------------------------------------------------------------------------

generate_llama_cpp_provider() {
    local -a models=("$@")
    local config=""
    local first=true
    
    config='"llama.cpp": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "llama.cpp (local)",
      "options": {
        "baseURL": "http://127.0.0.1:'"$LLAMA_PORT"'/v1"
      },
      "models": {'
    
    for model_id in "${models[@]}"; do
        [[ -z "$model_id" ]] && continue
        
        local display_name context_limit output_limit
        local category="${MODEL_CATEGORY[$model_id]:-general}"
        
        # Check if we have metadata for this model
        if [[ -n "${MODEL_DISPLAY_NAME[$model_id]:-}" ]]; then
            display_name="${MODEL_DISPLAY_NAME[$model_id]}"
            context_limit="${MODEL_CONTEXT_LIMIT[$model_id]}"
            output_limit="${MODEL_OUTPUT_LIMIT[$model_id]}"
        else
            # Fall back to description from models.conf and category-based limits
            display_name="${MODEL_DESCRIPTION[$model_id]:-$model_id}"
            context_limit=$DEFAULT_CONTEXT
            output_limit=$DEFAULT_OUTPUT
            # Use larger limits for coding models, smaller for vision
            if [[ "$category" == "coding" ]]; then
                context_limit=$CODING_CONTEXT
                output_limit=$CODING_OUTPUT
            elif [[ "$category" == "vision" ]]; then
                context_limit=16384
                output_limit=4096
            fi
        fi
        
        if [[ "$first" == true ]]; then
            first=false
        else
            config+=","
        fi
        
        config+="
        \"$model_id\": {
          \"name\": \"$display_name\",
          \"tools\": true,
          \"limit\": { \"context\": $context_limit, \"output\": $output_limit }
        }"
    done
    
    config+='
      }
    }'
    
    echo "$config"
}

merge_config() {
    local llama_provider="$1"
    
    # Check if jq is available
    if ! command -v jq &>/dev/null; then
        print_error "jq is required for config merging. Install it with your package manager."
        exit 1
    fi
    
    if [[ ! -f "$OPENCODE_CONFIG" ]]; then
        # No existing config - create new one
        echo '{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    '"$llama_provider"'
  }
}'
        return
    fi
    
    # Read existing config and merge
    local existing_config
    existing_config=$(<"$OPENCODE_CONFIG")
    
    # Validate existing config is valid JSON
    if ! echo "$existing_config" | jq empty 2>/dev/null; then
        print_error "Existing config is not valid JSON: $OPENCODE_CONFIG"
        print_status "Please fix the config manually or restore from backup:"
        print_status "  ./sync-opencode.sh --restore"
        exit 1
    fi
    
    # Remove existing llama.cpp provider if present, then add new one
    local updated_config
    if ! updated_config=$(echo "$existing_config" | jq --argjson llama "{$llama_provider}" '
        .provider["llama.cpp"] = $llama["llama.cpp"]
    ' 2>&1); then
        print_error "Failed to merge config with jq"
        echo -e "${DIM}jq error: $updated_config${NC}"
        exit 1
    fi
    
    echo "$updated_config"
}

# -----------------------------------------------------------------------------
# Sync Models
# -----------------------------------------------------------------------------

sync_models_config() {
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${CYAN}${BOLD}[dry-run] Would sync models to opencode.json${NC}"
        echo
    else
        if [[ "$MERGE_MODE" == true ]]; then
            echo -e "${CYAN}${BOLD}Syncing models (merge mode)${NC}"
        else
            echo -e "${CYAN}${BOLD}Syncing models${NC}"
        fi
        echo
    fi
    
    # Load model metadata
    load_models_conf_local
    load_metadata_conf
    
    # Get downloaded models
    print_status "Scanning for downloaded models in: $MODELS_DIR"
    DOWNLOADED_MODELS=$(get_downloaded_models)
    
    if [[ -z "$DOWNLOADED_MODELS" ]]; then
        print_warning "No GGUF models found in: $MODELS_DIR"
        echo
        echo "Download models first with:"
        echo "  ./download-model.sh --list"
        echo "  ./download-model.sh <model-id>"
        return 1
    fi
    
    # Convert to array
    read -ra MODEL_ARRAY <<< "$DOWNLOADED_MODELS"
    
    echo
    print_status "Found ${#MODEL_ARRAY[@]} downloaded model(s):"
    for model_id in "${MODEL_ARRAY[@]}"; do
        category="${MODEL_CATEGORY[$model_id]:-unknown}"
        size="${MODEL_SIZE[$model_id]:-?}"
        desc="${MODEL_DESCRIPTION[$model_id]:-}"
        echo "    - $model_id ($size) [$category] $desc"
    done
    echo
    
    # Generate llama.cpp provider config
    LLAMA_PROVIDER=$(generate_llama_cpp_provider "${MODEL_ARRAY[@]}")
    
    # Merge with existing config
    CONFIG_JSON=$(merge_config "$LLAMA_PROVIDER")
    
    if [[ "$DRY_RUN" == true ]]; then
        print_status "Generated configuration:"
        echo
        if command -v jq &>/dev/null; then
            echo "$CONFIG_JSON" | jq .
        else
            echo "$CONFIG_JSON"
        fi
        echo
        return 0
    fi
    
    # Backup existing config if present
    backup_config "$OPENCODE_CONFIG"
    
    # Write config
    mkdir -p "$(dirname "$OPENCODE_CONFIG")"
    if command -v jq &>/dev/null; then
        echo "$CONFIG_JSON" | jq . > "$OPENCODE_CONFIG"
    else
        echo "$CONFIG_JSON" > "$OPENCODE_CONFIG"
    fi
    
    print_success "Models synced to: $OPENCODE_CONFIG"
    echo
}

# -----------------------------------------------------------------------------
# Sync Agents
# -----------------------------------------------------------------------------

sync_agents_config() {
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${CYAN}${BOLD}[dry-run] Would sync agent files${NC}"
        echo
        print_status "Source: $SCRIPT_DIR/agent/"
        print_status "Target: $OPENCODE_CONFIG_DIR/"
        echo
        print_status "Files:"
        echo "    AGENTS.md -> $OPENCODE_CONFIG_DIR/AGENTS.md"
        echo "    plan.md   -> $OPENCODE_CONFIG_DIR/agent/plan.md"
        echo "    review.md -> $OPENCODE_CONFIG_DIR/agent/review.md"
        echo "    debug.md  -> $OPENCODE_CONFIG_DIR/agent/debug.md"
        echo
        return 0
    fi
    
    if [[ "$RESET_AGENTS" == true ]]; then
        echo -e "${CYAN}${BOLD}Resetting agent files${NC}"
        echo
        sync_agents "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "true" "true"
    else
        echo -e "${CYAN}${BOLD}Syncing agent files${NC}"
        echo
        sync_agents "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "false" "false"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Handle restore mode first
if [[ "$RESTORE_MODE" == true ]]; then
    if [[ "$RESTORE_LATEST" == true ]]; then
        handle_config_restore "$OPENCODE_CONFIG" "--latest"
    else
        handle_config_restore "$OPENCODE_CONFIG"
    fi
    exit 0
fi

# Ensure models-metadata.conf exists before syncing
ensure_metadata_conf "$SCRIPT_DIR" "true"  # Non-interactive for sync script

echo

# Sync models if requested
if [[ "$SYNC_MODELS" == true ]]; then
    sync_models_config
fi

# Sync agents if requested
if [[ "$SYNC_AGENTS" == true ]]; then
    sync_agents_config
fi

if [[ "$DRY_RUN" == false ]]; then
    print_success "Sync complete"
fi
