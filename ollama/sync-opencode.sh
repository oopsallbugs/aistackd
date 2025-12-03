#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Sync OpenCode Configuration with Installed Ollama Models
# =============================================================================
#
# This script queries Ollama for installed models and syncs the OpenCode
# configuration file with proper model metadata.
#
# Usage:
#   ./sync-opencode.sh                  # Sync both models and agents
#   ./sync-opencode.sh --models         # Sync only model config
#   ./sync-opencode.sh --agents         # Sync only agent files
#   ./sync-opencode.sh --reset-agents   # Force reset agent files to defaults
#   ./sync-opencode.sh --merge          # Only add new models, keep existing entries
#   ./sync-opencode.sh --restore        # List and restore from a backup
#   ./sync-opencode.sh --restore-latest # Restore most recent backup
#   ./sync-opencode.sh --docker         # Force Docker mode (Linux)
#   ./sync-opencode.sh --native         # Force native mode (macOS)
#   ./sync-opencode.sh --dry-run        # Show config without writing
#   ./sync-opencode.sh --help           # Show help
#
# =============================================================================

# -----------------------------------------------------------------------------
# Bash Version Check - Requires Bash 4+ for associative arrays
# -----------------------------------------------------------------------------

if [[ "${BASH_VERSION%%.*}" -lt 4 ]]; then
    echo ""
    echo "ERROR: This script requires Bash 4.0 or later."
    echo "       Current version: $BASH_VERSION"
    echo ""
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "macOS ships with Bash 3.2 due to licensing restrictions."
        echo ""
        echo "To fix this, install Bash via Homebrew:"
        echo "  brew install bash"
        echo ""
        echo "Then run this script with the new Bash:"
        echo "  /opt/homebrew/bin/bash $0 $*"
    else
        echo "Please upgrade your Bash installation."
    fi
    echo ""
    exit 1
fi

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source common library (from parent directory)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
OPENCODE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
OPENCODE_CONFIG_DIR="$(dirname "$OPENCODE_CONFIG")"
AGENT_SOURCE_DIR="$SCRIPT_DIR/../agent"
OLLAMA_MODE=""
DRY_RUN=false
MERGE_MODE=false
RESTORE_MODE=false
RESTORE_LATEST=false
SYNC_MODELS=false
SYNC_AGENTS=false
RESET_AGENTS=false

# Default metadata for unknown models
DEFAULT_CONTEXT=32768
DEFAULT_OUTPUT=8192

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
        --docker)
            OLLAMA_MODE="docker"
            ;;
        --native)
            OLLAMA_MODE="native"
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
            echo "Syncs OpenCode configuration with installed Ollama models and agent files."
            echo
            echo "What to sync:"
            echo "  (default)         Sync both models and agents"
            echo "  --models          Sync only model config (opencode.json)"
            echo "  --agents          Sync only agent files (AGENTS.md, agents/*.md)"
            echo "  --reset-agents    Force reset agent files to defaults"
            echo
            echo "Model options:"
            echo "  --merge           Only add new models, keep existing config entries"
            echo "  --restore         List available config backups and restore one"
            echo "  --restore-latest  Restore the most recent config backup"
            echo
            echo "Ollama mode:"
            echo "  --docker          Force Docker mode (Linux with Docker)"
            echo "  --native          Force native mode (macOS or native Linux install)"
            echo
            echo "General options:"
            echo "  --dry-run         Show what would be synced without writing"
            echo "  --help, -h        Show this help message"
            echo
            echo "The script auto-detects whether Ollama is running in Docker or natively."
            echo
            echo "Files:"
            echo "  Config:  $OPENCODE_CONFIG"
            echo "  Agents:  $OPENCODE_CONFIG_DIR/AGENTS.md"
            echo "           $OPENCODE_CONFIG_DIR/agents/*.md"
            echo "  Metadata: $METADATA_CONF"
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
# Load Model Metadata
# -----------------------------------------------------------------------------

# Uses load_metadata_conf from common.sh - just need to set METADATA_CONF first
# Associative arrays MODEL_DISPLAY_NAME, MODEL_CONTEXT_LIMIT, MODEL_OUTPUT_LIMIT 
# are already defined in common.sh

# -----------------------------------------------------------------------------
# Load Existing Config Models (for merge mode)
# -----------------------------------------------------------------------------

declare -A EXISTING_MODELS=()

load_existing_config() {
    if [[ ! -f "$OPENCODE_CONFIG" ]]; then
        return
    fi
    
    # Check if jq is available
    if ! command -v jq &>/dev/null; then
        print_warning "jq not installed - cannot read existing config for merge"
        return
    fi
    
    # Extract model keys from existing config
    local models
    models=$(jq -r '.provider.ollama.models // {} | keys[]' "$OPENCODE_CONFIG" 2>/dev/null) || return
    
    # Store each model's full config
    for model in $models; do
        local config
        config=$(jq -c ".provider.ollama.models[\"$model\"]" "$OPENCODE_CONFIG" 2>/dev/null) || continue
        EXISTING_MODELS["$model"]="$config"
    done
}

# -----------------------------------------------------------------------------
# Detect Ollama Mode
# -----------------------------------------------------------------------------

detect_ollama_mode() {
    if [[ -n "$OLLAMA_MODE" ]]; then
        return
    fi
    
    # Check Docker first (Linux default)
    if command -v docker &>/dev/null && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
        OLLAMA_MODE="docker"
        return
    fi
    
    # Check native Ollama
    if command -v ollama &>/dev/null && curl -sf http://localhost:11434/api/tags &>/dev/null; then
        OLLAMA_MODE="native"
        return
    fi
    
    # Neither found
    print_error "Ollama is not running"
    echo ""
    echo "Please start Ollama first:"
    echo "  Docker:  docker compose up -d"
    echo "  Native:  ollama serve"
    exit 1
}

# -----------------------------------------------------------------------------
# Get Installed Models
# -----------------------------------------------------------------------------

get_installed_models() {
    local models=""
    
    if [[ "$OLLAMA_MODE" == "docker" ]]; then
        models=$(docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
    else
        models=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
    fi
    
    echo "$models"
}

# -----------------------------------------------------------------------------
# Generate Display Name for Unknown Models
# -----------------------------------------------------------------------------

# generate_display_name() is now in lib/common.sh

# -----------------------------------------------------------------------------
# Generate OpenCode Config
# -----------------------------------------------------------------------------

generate_config() {
    local -a installed_models=("$@")
    local config=""
    local first=true
    
    # Track which models we've added (to avoid duplicates in merge mode)
    declare -A added_models
    
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
    
    # Add installed models first
    for model in "${installed_models[@]}"; do
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
        
        added_models["$model"]=1
    done
    
    # In merge mode, add existing models that aren't in the installed list
    if [[ "$MERGE_MODE" == "true" ]]; then
        for model in "${!EXISTING_MODELS[@]}"; do
            # Skip if already added
            [[ -n "${added_models[$model]:-}" ]] && continue
            
            local existing_config="${EXISTING_MODELS[$model]}"
            local display_name context_limit output_limit
            
            # Extract values from existing config
            display_name=$(echo "$existing_config" | jq -r '.name // empty' 2>/dev/null)
            context_limit=$(echo "$existing_config" | jq -r '.limit.context // empty' 2>/dev/null)
            output_limit=$(echo "$existing_config" | jq -r '.limit.output // empty' 2>/dev/null)
            
            # Use defaults if extraction failed
            [[ -z "$display_name" ]] && display_name=$(generate_display_name "$model")
            [[ -z "$context_limit" ]] && context_limit=$DEFAULT_CONTEXT
            [[ -z "$output_limit" ]] && output_limit=$DEFAULT_OUTPUT
            
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
            
            added_models["$model"]=1
        done
    fi
    
    # JSON footer
    config+='
      }
    }
  }
}'
    
    echo "$config"
}

# -----------------------------------------------------------------------------
# Sync Models to Config
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
    
    # Load metadata
    load_metadata_conf
    
    # Load existing config if in merge mode
    if [[ "$MERGE_MODE" == true ]]; then
        load_existing_config
        if [[ ${#EXISTING_MODELS[@]} -gt 0 ]]; then
            print_status "Found ${#EXISTING_MODELS[@]} existing model(s) in config (will preserve)"
        fi
    fi
    
    # Detect Ollama mode
    detect_ollama_mode
    print_status "Detected Ollama mode: $OLLAMA_MODE"
    
    # Get installed models
    print_status "Querying installed models..."
    INSTALLED_MODELS=$(get_installed_models)
    
    if [[ -z "$INSTALLED_MODELS" ]]; then
        print_warning "No models installed in Ollama"
        if [[ "$MERGE_MODE" == true && ${#EXISTING_MODELS[@]} -gt 0 ]]; then
            print_status "Keeping existing config (merge mode)"
            return 0
        fi
        echo
        echo "Install models first with:"
        if [[ "$OLLAMA_MODE" == "docker" ]]; then
            echo "  docker exec ollama ollama pull <model:tag>"
        else
            echo "  ollama pull <model:tag>"
        fi
        return 1
    fi
    
    # Convert to array
    readarray -t MODEL_ARRAY <<< "$INSTALLED_MODELS"
    
    echo
    print_status "Found ${#MODEL_ARRAY[@]} installed model(s):"
    for model in "${MODEL_ARRAY[@]}"; do
        if [[ -n "${MODEL_DISPLAY_NAME[$model]:-}" ]]; then
            echo "    - $model (${MODEL_DISPLAY_NAME[$model]})"
        else
            echo "    - $model (using defaults)"
        fi
    done
    
    # Show preserved models in merge mode
    if [[ "$MERGE_MODE" == true && ${#EXISTING_MODELS[@]} -gt 0 ]]; then
        preserved_count=0
        for model in "${!EXISTING_MODELS[@]}"; do
            # Check if this model is NOT in installed list
            found=false
            for installed in "${MODEL_ARRAY[@]}"; do
                [[ "$installed" == "$model" ]] && found=true && break
            done
            [[ "$found" == false ]] && ((preserved_count++))
        done
        if [[ $preserved_count -gt 0 ]]; then
            echo
            print_status "Preserving $preserved_count model(s) not in Ollama:"
            for model in "${!EXISTING_MODELS[@]}"; do
                found=false
                for installed in "${MODEL_ARRAY[@]}"; do
                    [[ "$installed" == "$model" ]] && found=true && break
                done
                [[ "$found" == false ]] && echo "    - $model (from existing config)"
            done
        fi
    fi
    
    echo
    
    # Generate config
    CONFIG_JSON=$(generate_config "${MODEL_ARRAY[@]}")
    
    if [[ "$DRY_RUN" == true ]]; then
        print_status "Generated configuration:"
        echo
        echo "$CONFIG_JSON"
        echo
        return 0
    fi
    
    # Backup existing config if present
    backup_config "$OPENCODE_CONFIG"
    
    # Write config
    mkdir -p "$(dirname "$OPENCODE_CONFIG")"
    echo "$CONFIG_JSON" > "$OPENCODE_CONFIG"
    
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
        print_status "Source: $AGENT_SOURCE_DIR/"
        print_status "Target: $OPENCODE_CONFIG_DIR/"
        echo
        print_status "Files:"
        echo "    AGENTS.md -> $OPENCODE_CONFIG_DIR/AGENTS.md"
        echo "    plan.md   -> $OPENCODE_CONFIG_DIR/agents/plan.md"
        echo "    review.md -> $OPENCODE_CONFIG_DIR/agents/review.md"
        echo "    debug.md  -> $OPENCODE_CONFIG_DIR/agents/debug.md"
        echo
        return 0
    fi
    
    if [[ "$RESET_AGENTS" == true ]]; then
        echo -e "${CYAN}${BOLD}Resetting agent files${NC}"
        echo
        sync_agents "$AGENT_SOURCE_DIR" "$OPENCODE_CONFIG_DIR" "true" "true"
    else
        echo -e "${CYAN}${BOLD}Syncing agent files${NC}"
        echo
        sync_agents "$AGENT_SOURCE_DIR" "$OPENCODE_CONFIG_DIR" "false" "false"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Handle restore mode first (doesn't need Ollama running)
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
