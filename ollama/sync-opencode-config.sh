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
#   ./sync-opencode-config.sh              # Full sync (replaces config with installed models)
#   ./sync-opencode-config.sh --merge      # Only add new models, keep existing entries
#   ./sync-opencode-config.sh --restore    # List and restore from a backup
#   ./sync-opencode-config.sh --restore-latest  # Restore most recent backup
#   ./sync-opencode-config.sh --docker     # Force Docker mode (Linux)
#   ./sync-opencode-config.sh --native     # Force native mode (macOS)
#   ./sync-opencode-config.sh --dry-run    # Show config without writing
#   ./sync-opencode-config.sh --help       # Show help
#
# =============================================================================

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Colors and Output Helpers
# -----------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
OPENCODE_CONFIG="$HOME/.config/opencode/opencode.json"
OLLAMA_MODE=""
DRY_RUN=false
MERGE_MODE=false
RESTORE_MODE=false
RESTORE_LATEST=false

# Default metadata for unknown models
DEFAULT_CONTEXT=32768
DEFAULT_OUTPUT=8192

# -----------------------------------------------------------------------------
# Parse Arguments
# -----------------------------------------------------------------------------

for arg in "$@"; do
    case $arg in
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
            echo "Usage: ./sync-opencode-config.sh [OPTIONS]"
            echo ""
            echo "Syncs OpenCode configuration with currently installed Ollama models."
            echo ""
            echo "Options:"
            echo "  --merge           Only add new models, keep existing config entries"
            echo "                    (use this if you have manually added models)"
            echo "  --restore         List available backups and select one to restore"
            echo "  --restore-latest  Restore the most recent backup automatically"
            echo "  --docker          Force Docker mode (Linux with Docker)"
            echo "  --native          Force native mode (macOS or native Linux install)"
            echo "  --dry-run         Print generated config without writing to file"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "By default, the script performs a full sync - replacing the config"
            echo "with only the currently installed models. Use --merge to preserve"
            echo "manually added entries."
            echo ""
            echo "Backups are created automatically before each sync. Use --restore"
            echo "to revert to a previous configuration if needed."
            echo ""
            echo "The script auto-detects whether Ollama is running in Docker or natively."
            echo ""
            echo "Config file: $OPENCODE_CONFIG"
            echo "Metadata file: $METADATA_CONF"
            exit 0
            ;;
        *)
            print_error "Unknown option: $arg"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Load Model Metadata
# -----------------------------------------------------------------------------

declare -A MODEL_DISPLAY_NAME
declare -A MODEL_CONTEXT_LIMIT
declare -A MODEL_OUTPUT_LIMIT

load_metadata() {
    if [[ ! -f "$METADATA_CONF" ]]; then
        print_warning "Metadata file not found: $METADATA_CONF"
        print_status "Using default values for all models"
        return
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
# Load Existing Config Models (for merge mode)
# -----------------------------------------------------------------------------

declare -A EXISTING_MODELS

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

generate_display_name() {
    local model="$1"
    local base_name size_tag
    
    # Extract base name and size (e.g., "qwen3:14b" -> "Qwen3" and "14B")
    base_name="${model%%:*}"
    size_tag="${model##*:}"
    
    # Capitalize and format base name
    base_name="${base_name^}"  # Capitalize first letter
    
    # Format size tag (uppercase)
    size_tag="${size_tag^^}"
    
    echo "$base_name $size_tag"
}

# -----------------------------------------------------------------------------
# Restore Functions
# -----------------------------------------------------------------------------

list_backups() {
    local backup_dir
    backup_dir="$(dirname "$OPENCODE_CONFIG")"
    local backup_pattern="opencode.json.backup.*"
    
    # Find all backups sorted by date (newest first)
    local -a backups=()
    while IFS= read -r -d '' file; do
        backups+=("$file")
    done < <(find "$backup_dir" -maxdepth 1 -name "$backup_pattern" -print0 2>/dev/null | sort -rz)
    
    echo "${backups[@]}"
}

restore_backup() {
    local backup_file="$1"
    
    if [[ ! -f "$backup_file" ]]; then
        print_error "Backup file not found: $backup_file"
        exit 1
    fi
    
    # Validate it's valid JSON
    if command -v jq &>/dev/null; then
        if ! jq empty "$backup_file" 2>/dev/null; then
            print_error "Backup file is not valid JSON: $backup_file"
            exit 1
        fi
    fi
    
    # Create a backup of current config before restoring
    if [[ -f "$OPENCODE_CONFIG" ]]; then
        local pre_restore_backup
        pre_restore_backup="$OPENCODE_CONFIG.pre-restore.$(date +%Y%m%d_%H%M%S)"
        cp "$OPENCODE_CONFIG" "$pre_restore_backup"
        print_status "Backed up current config to: $pre_restore_backup"
    fi
    
    # Restore the backup
    cp "$backup_file" "$OPENCODE_CONFIG"
    print_success "Restored config from: $backup_file"
}

handle_restore() {
    local backup_dir
    backup_dir="$(dirname "$OPENCODE_CONFIG")"
    
    echo ""
    echo -e "${CYAN}${BOLD}Restore OpenCode Configuration${NC}"
    echo ""
    
    # Get list of backups
    local backups_str
    backups_str=$(list_backups)
    
    if [[ -z "$backups_str" ]]; then
        print_warning "No backup files found in: $backup_dir"
        exit 0
    fi
    
    # Convert to array
    read -ra backups <<< "$backups_str"
    
    if [[ ${#backups[@]} -eq 0 ]]; then
        print_warning "No backup files found in: $backup_dir"
        exit 0
    fi
    
    # If --restore-latest, use the first (newest) backup
    if [[ "$RESTORE_LATEST" == "true" ]]; then
        local latest="${backups[0]}"
        print_status "Restoring latest backup..."
        restore_backup "$latest"
        exit 0
    fi
    
    # Interactive mode - list backups and let user choose
    print_status "Available backups (newest first):"
    echo ""
    
    local i=1
    for backup in "${backups[@]}"; do
        local basename
        basename=$(basename "$backup")
        # Extract timestamp from filename
        local timestamp="${basename#opencode.json.backup.}"
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
    
    echo ""
    echo "  0) Cancel"
    echo ""
    
    read -rp "Select backup to restore [0-$((${#backups[@]}))]: " choice
    
    # Validate input
    if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
        print_error "Invalid selection"
        exit 1
    fi
    
    if [[ "$choice" -eq 0 ]]; then
        print_status "Restore cancelled"
        exit 0
    fi
    
    if [[ "$choice" -lt 1 || "$choice" -gt ${#backups[@]} ]]; then
        print_error "Invalid selection: $choice"
        exit 1
    fi
    
    # Restore selected backup (array is 0-indexed, selection is 1-indexed)
    local selected_backup="${backups[$((choice-1))]}"
    echo ""
    restore_backup "$selected_backup"
}

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
# Main
# -----------------------------------------------------------------------------

# Handle restore mode first (doesn't need Ollama running)
if [[ "$RESTORE_MODE" == "true" ]]; then
    handle_restore
    exit 0
fi

echo ""
if [[ "$MERGE_MODE" == "true" ]]; then
    echo -e "${CYAN}${BOLD}Sync OpenCode Configuration (merge mode)${NC}"
else
    echo -e "${CYAN}${BOLD}Sync OpenCode Configuration${NC}"
fi
echo ""

# Load metadata
load_metadata

# Load existing config if in merge mode
if [[ "$MERGE_MODE" == "true" ]]; then
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
    if [[ "$MERGE_MODE" == "true" && ${#EXISTING_MODELS[@]} -gt 0 ]]; then
        print_status "Keeping existing config (merge mode)"
        exit 0
    fi
    echo ""
    echo "Install models first with:"
    if [[ "$OLLAMA_MODE" == "docker" ]]; then
        echo "  docker exec ollama ollama pull <model:tag>"
    else
        echo "  ollama pull <model:tag>"
    fi
    exit 0
fi

# Convert to array
readarray -t MODEL_ARRAY <<< "$INSTALLED_MODELS"

echo ""
print_status "Found ${#MODEL_ARRAY[@]} installed model(s):"
for model in "${MODEL_ARRAY[@]}"; do
    if [[ -n "${MODEL_DISPLAY_NAME[$model]:-}" ]]; then
        echo "    - $model (${MODEL_DISPLAY_NAME[$model]})"
    else
        echo "    - $model (using defaults)"
    fi
done

# Show preserved models in merge mode
if [[ "$MERGE_MODE" == "true" && ${#EXISTING_MODELS[@]} -gt 0 ]]; then
    preserved_count=0
    for model in "${!EXISTING_MODELS[@]}"; do
        # Check if this model is NOT in installed list
        found=false
        for installed in "${MODEL_ARRAY[@]}"; do
            [[ "$installed" == "$model" ]] && found=true && break
        done
        [[ "$found" == "false" ]] && ((preserved_count++))
    done
    if [[ $preserved_count -gt 0 ]]; then
        echo ""
        print_status "Preserving $preserved_count model(s) not in Ollama:"
        for model in "${!EXISTING_MODELS[@]}"; do
            found=false
            for installed in "${MODEL_ARRAY[@]}"; do
                [[ "$installed" == "$model" ]] && found=true && break
            done
            [[ "$found" == "false" ]] && echo "    - $model (from existing config)"
        done
    fi
fi

echo ""

# Generate config
CONFIG_JSON=$(generate_config "${MODEL_ARRAY[@]}")

if [[ "$DRY_RUN" == "true" ]]; then
    print_status "Generated configuration (dry-run):"
    echo ""
    echo "$CONFIG_JSON"
    echo ""
    exit 0
fi

# Backup existing config if present
if [[ -f "$OPENCODE_CONFIG" ]]; then
    BACKUP_FILE="$OPENCODE_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$OPENCODE_CONFIG" "$BACKUP_FILE"
    print_status "Backed up existing config to: $BACKUP_FILE"
fi

# Write config
mkdir -p "$(dirname "$OPENCODE_CONFIG")"
echo "$CONFIG_JSON" > "$OPENCODE_CONFIG"

print_success "OpenCode config synced: $OPENCODE_CONFIG"
