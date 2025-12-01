#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Sync OpenCode Configuration with Downloaded llama.cpp Models
# =============================================================================
#
# This script scans the models directory for downloaded GGUF files and syncs
# the OpenCode configuration with proper model metadata.
#
# Usage:
#   ./sync-opencode-config.sh              # Full sync (replaces llama.cpp models in config)
#   ./sync-opencode-config.sh --merge      # Only add new models, keep existing entries
#   ./sync-opencode-config.sh --restore    # List and restore from a backup
#   ./sync-opencode-config.sh --restore-latest  # Restore most recent backup
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

# Colors - only use if terminal supports them
if [[ -t 1 ]] && [[ "${TERM:-dumb}" != "dumb" ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    BOLD=''
    NC=''
fi

# Check for gum
HAS_GUM=false
if command -v gum &>/dev/null; then
    HAS_GUM=true
fi

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MODELS_CONF="$SCRIPT_DIR/models.conf"
METADATA_CONF="$SCRIPT_DIR/models-metadata.conf"
MODELS_DIR="$SCRIPT_DIR/models"
OPENCODE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
DRY_RUN=false
MERGE_MODE=false
RESTORE_MODE=false
RESTORE_LATEST=false

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
            echo
            echo "Syncs OpenCode configuration with downloaded llama.cpp GGUF models."
            echo
            echo "Options:"
            echo "  --merge           Only add new models, keep existing config entries"
            echo "                    (preserves other providers like Ollama)"
            echo "  --restore         List available backups and select one to restore"
            echo "  --restore-latest  Restore the most recent backup automatically"
            echo "  --dry-run         Print generated config without writing to file"
            echo "  --help, -h        Show this help message"
            echo
            echo "By default, the script performs a full sync - updating the llama.cpp"
            echo "provider section with currently downloaded models while preserving"
            echo "other providers."
            echo
            echo "Backups are created automatically before each sync."
            echo
            echo "Config file: $OPENCODE_CONFIG"
            echo "Models conf: $MODELS_CONF"
            echo "Models dir:  $MODELS_DIR"
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
# Load Model Metadata from models.conf
# -----------------------------------------------------------------------------

declare -A MODEL_ID_BY_FILE
declare -A MODEL_CATEGORY
declare -A MODEL_DESCRIPTION
declare -A MODEL_SIZE

# Metadata from models-metadata.conf
declare -A MODEL_DISPLAY_NAME
declare -A MODEL_CONTEXT_LIMIT
declare -A MODEL_OUTPUT_LIMIT

load_models_conf() {
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_warning "models.conf not found: $MODELS_CONF"
        return 1
    fi
    
    while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
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
# Restore Functions
# -----------------------------------------------------------------------------

list_backups() {
    local backup_dir
    backup_dir="$(dirname "$OPENCODE_CONFIG")"
    local backup_pattern="opencode.json.backup.*"
    
    # Find all backups sorted by date (newest first)
    # Output one file per line for safe handling
    find "$backup_dir" -maxdepth 1 -name "$backup_pattern" -print 2>/dev/null | sort -r
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
    
    echo
    echo -e "${CYAN}${BOLD}Restore OpenCode Configuration${NC}"
    echo
    
    # Get list of backups into array (one per line)
    local -a backups=()
    while IFS= read -r file; do
        [[ -n "$file" ]] && backups+=("$file")
    done < <(list_backups)
    
    if [[ ${#backups[@]} -eq 0 ]]; then
        print_warning "No backup files found in: $backup_dir"
        exit 0
    fi
    
    # If --restore-latest, use the first (newest) backup
    if [[ "$RESTORE_LATEST" == true ]]; then
        local latest="${backups[0]}"
        print_status "Restoring latest backup..."
        restore_backup "$latest"
        exit 0
    fi
    
    # Interactive mode - list backups and let user choose
    print_status "Available backups (newest first):"
    echo
    
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
    
    echo
    echo "  0) Cancel"
    echo
    
    local choice=""
    if [[ "$HAS_GUM" == true ]]; then
        # Build options for gum
        local gum_options=()
        local gum_backup gum_basename gum_timestamp gum_formatted
        for gum_backup in "${backups[@]}"; do
            gum_basename=$(basename "$gum_backup")
            gum_timestamp="${gum_basename#opencode.json.backup.}"
            if [[ "$gum_timestamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
                gum_formatted="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
            else
                gum_formatted="$gum_timestamp"
            fi
            gum_options+=("$gum_formatted")
        done
        gum_options+=("Cancel")
        
        local selected
        selected=$(gum choose --cursor-prefix="○ " --selected-prefix="◉ " \
            --cursor.foreground="212" \
            "${gum_options[@]}") || {
            print_status "Restore cancelled"
            exit 0
        }
        
        if [[ "$selected" == "Cancel" ]]; then
            print_status "Restore cancelled"
            exit 0
        fi
        
        # Find matching backup
        local idx
        for idx in "${!backups[@]}"; do
            gum_basename=$(basename "${backups[$idx]}")
            gum_timestamp="${gum_basename#opencode.json.backup.}"
            if [[ "$gum_timestamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
                gum_formatted="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
            else
                gum_formatted="$gum_timestamp"
            fi
            if [[ "$selected" == "$gum_formatted" ]]; then
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
    echo
    restore_backup "$selected_backup"
}

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
            # Use larger limits for coding models
            if [[ "$category" == "coding" ]]; then
                context_limit=$CODING_CONTEXT
                output_limit=$CODING_OUTPUT
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
        print_error "jq is required for config merging. Install it with: sudo pacman -S jq"
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
        print_status "  ./sync-opencode-config.sh --restore"
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
# Main
# -----------------------------------------------------------------------------

# Handle restore mode first
if [[ "$RESTORE_MODE" == true ]]; then
    handle_restore
    exit 0
fi

echo
if [[ "$MERGE_MODE" == true ]]; then
    echo -e "${CYAN}${BOLD}Sync OpenCode Configuration - llama.cpp (merge mode)${NC}"
else
    echo -e "${CYAN}${BOLD}Sync OpenCode Configuration - llama.cpp${NC}"
fi
echo

# Load model metadata
load_models_conf
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
    exit 0
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
    print_status "Generated configuration (dry-run):"
    echo
    if command -v jq &>/dev/null; then
        echo "$CONFIG_JSON" | jq .
    else
        echo "$CONFIG_JSON"
    fi
    echo
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
if command -v jq &>/dev/null; then
    echo "$CONFIG_JSON" | jq . > "$OPENCODE_CONFIG"
else
    echo "$CONFIG_JSON" > "$OPENCODE_CONFIG"
fi

print_success "OpenCode config synced: $OPENCODE_CONFIG"
echo
echo "Models added to llama.cpp provider:"
for model_id in "${MODEL_ARRAY[@]}"; do
    echo "    - $model_id"
done
echo
echo "Start the server with:"
echo "    ./start-server.sh ${MODEL_ARRAY[0]}"
echo
