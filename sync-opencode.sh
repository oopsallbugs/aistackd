#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Sync OpenCode Configuration
# =============================================================================
#
# Syncs downloaded models, agent files, and tools to OpenCode configuration.
#
# Usage:
#   ./sync-opencode.sh                  # Sync all (models, agents, tools)
#   ./sync-opencode.sh --models         # Sync only model config (opencode.json)
#   ./sync-opencode.sh --agents         # Sync only agent files
#   ./sync-opencode.sh --tools          # Sync only tool files (black/whitelist opencode-tools.yaml)     
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

OPENCODE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
OPENCODE_CONFIG_DIR="$(dirname "$OPENCODE_CONFIG")"
GLOBAL_TOOLS_DIR="$OPENCODE_CONFIG_DIR/tools"
TOOLS_CONFIG_FILE="$SCRIPT_DIR/opencode-tools.yaml"

# Modes
SYNC_MODELS=false
SYNC_AGENTS=false
SYNC_TOOLS=false
DRY_RUN=false
MERGE_MODE=false
RESTORE_MODE=false
RESTORE_LATEST=false
RESET_AGENTS=false

# MODELS_CONF is not in .env (always relative to script)
MODELS_CONF="$SCRIPT_DIR/models.conf"

# Load .env (required, unless just showing help)
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
    [[ -z "${MODELS_DIR:-}" ]] && missing_vars+=("MODELS_DIR")
    [[ -z "${LLAMA_PORT:-}" ]] && missing_vars+=("LLAMA_PORT")

    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo "Error: Missing required variables in .env: ${missing_vars[*]}" >&2
        echo "Run ./setup.sh to regenerate .env" >&2
        exit 1
    fi
fi

# Default limits (for models without explicit limits in models.conf)
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
        --tools)
            SYNC_TOOLS=true
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
            echo "  Config:  ~/.config/opencode/opencode.json"
            echo "  Agents:  ~/.config/opencode/AGENTS.md"
            echo "           ~/.config/opencode/agent/*.md"
            echo "  Models:  <models-dir>/*.gguf (from .env)"
            exit 0
            ;;
        *)
            print_error "Unknown option: $arg"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Default: sync all if no flags specified
if [[ "$SYNC_MODELS" == false && "$SYNC_AGENTS" == false && "$SYNC_TOOLS" == false && "$RESTORE_MODE" == false ]]; then
    SYNC_MODELS=true
    SYNC_AGENTS=true
    SYNC_TOOLS=true
fi

# -----------------------------------------------------------------------------
# Load Model Metadata from models.conf
# -----------------------------------------------------------------------------

declare -A MODEL_ID_BY_FILE
declare -A MODEL_CATEGORY
declare -A MODEL_DESCRIPTION
declare -A MODEL_SIZE

# Metadata arrays (MODEL_DISPLAY_NAME, MODEL_CONTEXT_LIMIT, MODEL_OUTPUT_LIMIT)
# are populated by load_metadata_conf() from common.sh, reading from models.conf

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
# Sync Tools
# -----------------------------------------------------------------------------

sync_tools_config() {
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${CYAN}${BOLD}[dry-run] Would sync tools${NC}"
        echo
        print_status "Source: $SCRIPT_DIR/tools/"
        print_status "Target: $GLOBAL_TOOLS_DIR/"
        
        if [[ -f "$TOOLS_CONFIG_FILE" ]]; then
            print_status "Using config: $TOOLS_CONFIG_FILE"
        else
            print_status "No config file - would sync all tools"
        fi
        echo
        return 0
    fi
    
    echo -e "${CYAN}${BOLD}Syncing OpenCode tools (global)${NC}"
    echo
    
    # Create tools directory if it doesn't exist
    mkdir -p "$SCRIPT_DIR/tools"
    
    # Check if we have any tools
    if [[ ! -d "$SCRIPT_DIR/tools" ]] || [[ -z "$(ls -A "$SCRIPT_DIR/tools"/*.ts 2>/dev/null)" ]]; then
        print_warning "No custom tools found in: $SCRIPT_DIR/tools/"
        echo
        echo "Create tools in $SCRIPT_DIR/tools/ with .ts extension"
        echo "Example: tools/websearch.ts for SearXNG integration"
        return 1
    fi
    
    # Clean target directory
    rm -rf "$GLOBAL_TOOLS_DIR"
    mkdir -p "$GLOBAL_TOOLS_DIR"
    
    local TOOLS_SOURCE="$SCRIPT_DIR/tools"
    local copied_count=0
    local skipped_count=0
    
    # Check for config file
    if [[ -f "$TOOLS_CONFIG_FILE" ]]; then
        print_status "Using configuration: $TOOLS_CONFIG_FILE"
        echo
        
        # Parse YAML for exclude list (simple approach)
        local exclude_list=()
        if grep -q "^exclude:" "$TOOLS_CONFIG_FILE"; then
            exclude_list=($(awk '/^exclude:/{flag=1; next} /^[^[:space:]]/{flag=0} flag && /^[[:space:]]*-[[:space:]]*/ {gsub(/^[[:space:]]*-[[:space:]]*|\"/, "", $0); print $0}' "$TOOLS_CONFIG_FILE"))
        fi
        
        # Parse include list if present (overrides exclude)
        local include_list=()
        if grep -q "^include:" "$TOOLS_CONFIG_FILE"; then
            include_list=($(awk '/^include:/{flag=1; next} /^[^[:space:]]/{flag=0} flag && /^[[:space:]]*-[[:space:]]*/ {gsub(/^[[:space:]]*-[[:space:]]*|\"/, "", $0); print $0}' "$TOOLS_CONFIG_FILE"))
        fi
        
        # Sync based on config
        if [[ ${#include_list[@]} -gt 0 ]]; then
            # WHITELIST mode: Only copy included tools
            print_status "Using include list (whitelist mode)"
            echo
            
            for tool_name in "${include_list[@]}"; do
                tool_name=$(echo "$tool_name" | xargs)  # Trim whitespace
                local tool_file="$TOOLS_SOURCE/$tool_name"
                
                # Ensure .ts extension
                [[ "$tool_file" != *.ts ]] && tool_file="${tool_file}.ts"
                
                if [[ -f "$tool_file" ]]; then
                    cp "$tool_file" "$GLOBAL_TOOLS_DIR/"
                    ((copied_count++))
                    echo -e "  ${GREEN}✓ $tool_name${NC}"
                else
                    echo -e "  ${RED}⚠ Not found: $tool_name${NC}"
                fi
            done
            
        else
            # BLACKLIST mode: Copy all except excluded
            if [[ ${#exclude_list[@]} -gt 0 ]]; then
                print_status "Using exclude list (blacklist mode)"
                echo -e "  Excluding: ${YELLOW}${exclude_list[*]}${NC}"
                echo
            else
                print_status "No exclude list - copying all tools"
                echo
            fi
            
            # Copy all .ts files except excluded ones
            for tool_file in "$TOOLS_SOURCE"/*.ts; do
                [[ -f "$tool_file" ]] || continue
                local filename=$(basename "$tool_file")
                local filename_no_ext="${filename%.ts}"
                
                local should_copy=true
                for pattern in "${exclude_list[@]}"; do
                    pattern=$(echo "$pattern" | xargs)
                    # Handle wildcard patterns
                    if [[ "$pattern" == *"*" ]]; then
                        local prefix="${pattern%\*}"
                        if [[ "$filename_no_ext" == "$prefix"* ]]; then
                            should_copy=false
                            break
                        fi
                    elif [[ "$filename_no_ext" == "$pattern" ]]; then
                        should_copy=false
                        break
                    fi
                done
                
                if [[ "$should_copy" == true ]]; then
                    cp "$tool_file" "$GLOBAL_TOOLS_DIR/"
                    ((copied_count++))
                    echo -e "  ${GREEN}✓ $filename${NC}"
                else
                    ((skipped_count++))
                    echo -e "  ${YELLOW}✗ Skipping (excluded): $filename${NC}"
                fi
            done
        fi
        
    else
        # No config file - sync all tools
        print_status "No config file - syncing all tools"
        echo
        
        cp -r "$TOOLS_SOURCE/"*.ts "$GLOBAL_TOOLS_DIR/" 2>/dev/null || true
        copied_count=$(ls -1 "$GLOBAL_TOOLS_DIR"/*.ts 2>/dev/null | wc -l)
        
        for tool_file in "$TOOLS_SOURCE"/*.ts; do
            [[ -f "$tool_file" ]] || continue
            echo -e "  ${GREEN}✓ $(basename "$tool_file")${NC}"
        done
    fi
    
    echo
    if [[ $copied_count -gt 0 ]]; then
        print_success "Tools synced: $copied_count tool(s) copied to $GLOBAL_TOOLS_DIR"
        
        # Show usage instructions
        echo
        echo -e "${DIM}Usage in OpenCode:${NC}"
        echo -e "  ${DIM}\"Search the web for current news. Use websearch tool.\"${NC}"
        
        # List available tools
        if [[ $copied_count -le 10 ]]; then
            echo -e "${DIM}Available tools:${NC}"
            for tool in "$GLOBAL_TOOLS_DIR"/*.ts; do
                [[ -f "$tool" ]] || continue
                tool_name=$(basename "$tool" .ts)
                echo -e "  ${DIM}- $tool_name${NC}"
            done
        fi
    else
        print_warning "No tools were synced"
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
