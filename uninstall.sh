#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp ROCm Uninstall Script
# Clean removal with gum-based interactive selection
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source common library
source "$SCRIPT_DIR/lib/common.sh"

trap cleanup_spinner EXIT INT TERM PIPE

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

LLAMA_CPP_DIR="$SCRIPT_DIR/llama.cpp"
MODELS_DIR="$SCRIPT_DIR/models"
LOCAL_ENV="$SCRIPT_DIR/.env"
OPENCODE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"

# Parse command line arguments
REMOVE_ALL=false
REMOVE_BUILD=false
REMOVE_MODELS=false
REMOVE_CONFIG=false
REMOVE_OPENCODE=false
DRY_RUN=false
NON_INTERACTIVE=false

for arg in "$@"; do
    case $arg in
        --all)
            REMOVE_ALL=true
            REMOVE_BUILD=true
            REMOVE_MODELS=true
            REMOVE_CONFIG=true
            REMOVE_OPENCODE=true
            ;;
        --build) REMOVE_BUILD=true ;;
        --models) REMOVE_MODELS=true ;;
        --config) REMOVE_CONFIG=true ;;
        --opencode) REMOVE_OPENCODE=true ;;
        --dry-run) DRY_RUN=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --help|-h)
            echo
            echo -e "${CYAN}${BOLD}llama.cpp Uninstall${NC}"
            echo
            echo "Usage: ./uninstall.sh [OPTIONS]"
            echo
            echo "Remove llama.cpp installation and related files."
            echo
            echo "Options:"
            echo "  --all               Remove everything (build, models, config, opencode)"
            echo "  --build             Remove llama.cpp build directory"
            echo "  --models            Remove downloaded GGUF models"
            echo "  --config            Remove local .env configuration"
            echo "  --opencode          Remove llama.cpp from OpenCode config"
            echo "  --dry-run           Show what would be removed without doing it"
            echo "  --non-interactive   Don't ask for confirmation"
            echo "  --help, -h          Show this help message"
            echo
            echo "Without options, runs in interactive mode to select what to remove."
            echo
            exit 0
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Size Calculation
# -----------------------------------------------------------------------------

get_dir_size() {
    local dir="$1"
    if [[ -d "$dir" ]]; then
        du -sh "$dir" 2>/dev/null | cut -f1
    else
        echo "0"
    fi
}

get_file_size() {
    local file="$1"
    if [[ -f "$file" ]]; then
        du -sh "$file" 2>/dev/null | cut -f1
    else
        echo "0"
    fi
}

# -----------------------------------------------------------------------------
# Inventory Check
# -----------------------------------------------------------------------------

BUILD_EXISTS=false
BUILD_SIZE="0"
MODELS_EXIST=false
MODEL_COUNT=0
MODELS_SIZE="0"
CONFIG_EXISTS=false
OPENCODE_HAS_LLAMA=false

check_inventory() {
    # Check build directory
    if [[ -d "$LLAMA_CPP_DIR" ]]; then
        BUILD_EXISTS=true
        BUILD_SIZE=$(get_dir_size "$LLAMA_CPP_DIR")
    fi
    
    # Check models
    if [[ -d "$MODELS_DIR" ]]; then
        for f in "$MODELS_DIR"/*.gguf; do
            [[ -f "$f" ]] && ((MODEL_COUNT++)) || true
        done
        if [[ $MODEL_COUNT -gt 0 ]]; then
            MODELS_EXIST=true
            MODELS_SIZE=$(get_dir_size "$MODELS_DIR")
        fi
    fi
    
    # Check config
    if [[ -f "$LOCAL_ENV" ]]; then
        CONFIG_EXISTS=true
    fi
    
    # Check OpenCode
    if [[ -f "$OPENCODE_CONFIG" ]] && command -v jq &>/dev/null; then
        if jq -e '.provider["llama.cpp"]' "$OPENCODE_CONFIG" &>/dev/null; then
            OPENCODE_HAS_LLAMA=true
        fi
    fi
}

# -----------------------------------------------------------------------------
# Interactive Selection with Gum
# -----------------------------------------------------------------------------

gum_selection() {
    echo
    gum style \
        --border rounded \
        --border-foreground 212 \
        --padding "0 2" \
        --margin "0" \
        "llama.cpp Uninstall"
    echo
    
    # Build options array
    local options=()
    local option_map=()
    
    if [[ "$BUILD_EXISTS" == true ]]; then
        options+=("Build directory ($BUILD_SIZE) - $LLAMA_CPP_DIR")
        option_map+=("build")
    fi
    
    if [[ "$MODELS_EXIST" == true ]]; then
        options+=("Downloaded models ($MODEL_COUNT files, $MODELS_SIZE) - $MODELS_DIR")
        option_map+=("models")
    fi
    
    if [[ "$CONFIG_EXISTS" == true ]]; then
        options+=("Local configuration (.env)")
        option_map+=("config")
    fi
    
    if [[ "$OPENCODE_HAS_LLAMA" == true ]]; then
        options+=("OpenCode llama.cpp provider config")
        option_map+=("opencode")
    fi
    
    if [[ ${#options[@]} -eq 0 ]]; then
        gum style --foreground 212 "Nothing to remove - llama.cpp is not installed"
        echo
        exit 0
    fi
    
    echo -e "${DIM}Use Space to toggle, Enter to confirm${NC}"
    echo
    
    # Show selection dialog
    local selections
    selections=$(gum choose --no-limit \
        --cursor-prefix="○ " \
        --selected-prefix="✓ " \
        --unselected-prefix="○ " \
        --cursor.foreground="212" \
        --selected.foreground="196" \
        --height=10 \
        "${options[@]}") || {
        echo
        print_status "Cancelled"
        exit 0
    }
    
    if [[ -z "$selections" ]]; then
        print_status "Nothing selected"
        exit 0
    fi
    
    # Parse selections
    while IFS= read -r line; do
        if [[ "$line" == *"Build directory"* ]]; then
            REMOVE_BUILD=true
        elif [[ "$line" == *"Downloaded models"* ]]; then
            REMOVE_MODELS=true
        elif [[ "$line" == *"Local configuration"* ]]; then
            REMOVE_CONFIG=true
        elif [[ "$line" == *"OpenCode"* ]]; then
            REMOVE_OPENCODE=true
        fi
    done <<< "$selections"
}

fallback_selection() {
    echo
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo -e "${CYAN}${BOLD}  llama.cpp Uninstall${NC}"
    echo -e "${CYAN}${BOLD}============================================${NC}"
    echo
    
    local idx=1
    local option_map=()
    
    if [[ "$BUILD_EXISTS" == true ]]; then
        echo -e "  ${BOLD}$idx)${NC} Build directory ($BUILD_SIZE)"
        echo -e "     ${DIM}$LLAMA_CPP_DIR${NC}"
        option_map+=("build")
        ((++idx))
    fi
    
    if [[ "$MODELS_EXIST" == true ]]; then
        echo -e "  ${BOLD}$idx)${NC} Downloaded models ($MODEL_COUNT files, $MODELS_SIZE)"
        echo -e "     ${DIM}$MODELS_DIR${NC}"
        option_map+=("models")
        ((++idx))
    fi
    
    if [[ "$CONFIG_EXISTS" == true ]]; then
        echo -e "  ${BOLD}$idx)${NC} Local configuration (.env)"
        echo -e "     ${DIM}$LOCAL_ENV${NC}"
        option_map+=("config")
        ((++idx))
    fi
    
    if [[ "$OPENCODE_HAS_LLAMA" == true ]]; then
        echo -e "  ${BOLD}$idx)${NC} OpenCode llama.cpp provider config"
        echo -e "     ${DIM}$OPENCODE_CONFIG${NC}"
        option_map+=("opencode")
        ((++idx))
    fi
    
    if [[ ${#option_map[@]} -eq 0 ]]; then
        print_success "Nothing to remove - llama.cpp is not installed"
        exit 0
    fi
    
    echo
    echo "Select items to remove (space-separated numbers, or 'all'):"
    echo -e "${DIM}Example: 1 2 3  or  all${NC}"
    echo
    read -rp "> " selection
    
    if [[ -z "$selection" ]]; then
        print_status "No selection made, exiting"
        exit 0
    fi
    
    if [[ "$selection" == "all" ]]; then
        REMOVE_BUILD=$BUILD_EXISTS
        REMOVE_MODELS=$MODELS_EXIST
        REMOVE_CONFIG=$CONFIG_EXISTS
        REMOVE_OPENCODE=$OPENCODE_HAS_LLAMA
    else
        for num in $selection; do
            local adjusted_idx=$((num - 1))
            if [[ $adjusted_idx -ge 0 && $adjusted_idx -lt ${#option_map[@]} ]]; then
                case "${option_map[$adjusted_idx]}" in
                    build) REMOVE_BUILD=true ;;
                    models) REMOVE_MODELS=true ;;
                    config) REMOVE_CONFIG=true ;;
                    opencode) REMOVE_OPENCODE=true ;;
                esac
            else
                print_warning "Invalid selection: $num"
            fi
        done
    fi
}

# -----------------------------------------------------------------------------
# Confirmation
# -----------------------------------------------------------------------------

confirm_removal() {
    local items=()
    [[ "$REMOVE_BUILD" == true ]] && items+=("llama.cpp build ($BUILD_SIZE)")
    [[ "$REMOVE_MODELS" == true ]] && items+=("$MODEL_COUNT model files ($MODELS_SIZE)")
    [[ "$REMOVE_CONFIG" == true ]] && items+=("local .env config")
    [[ "$REMOVE_OPENCODE" == true ]] && items+=("OpenCode llama.cpp provider config")
    
    if [[ ${#items[@]} -eq 0 ]]; then
        print_warning "Nothing selected to remove"
        exit 0
    fi
    
    echo
    print_warning "The following will be ${RED}permanently removed${NC}:"
    echo
    for item in "${items[@]}"; do
        echo -e "  ${RED}•${NC} $item"
    done
    echo
    
    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi
    
    if [[ "$NON_INTERACTIVE" == true ]]; then
        return 0
    fi
    
    # Confirm with gum or fallback
    if [[ "$HAS_GUM" == true ]]; then
        if ! gum confirm --default=false --affirmative="Yes, remove" --negative="Cancel" "Proceed with removal?"; then
            echo
            print_status "Cancelled"
            exit 0
        fi
    else
        read -rp "Are you sure? (y/N) " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            print_status "Cancelled"
            exit 0
        fi
    fi
}

# -----------------------------------------------------------------------------
# Removal Functions
# -----------------------------------------------------------------------------

remove_build() {
    if [[ ! -d "$LLAMA_CPP_DIR" ]]; then
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_status "[DRY-RUN] Would remove: $LLAMA_CPP_DIR ($BUILD_SIZE)"
        return
    fi
    
    start_spinner "Removing llama.cpp build directory ($BUILD_SIZE)..."
    rm -rf "$LLAMA_CPP_DIR"
    stop_spinner true "Removed llama.cpp build directory"
}

remove_models() {
    if [[ "$MODEL_COUNT" -eq 0 ]]; then
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_status "[DRY-RUN] Would remove: $MODEL_COUNT GGUF files ($MODELS_SIZE)"
        for f in "$MODELS_DIR"/*.gguf; do
            [[ -f "$f" ]] && echo "  - $(basename "$f")"
        done
        return
    fi
    
    start_spinner "Removing $MODEL_COUNT GGUF models ($MODELS_SIZE)..."
    rm -f "$MODELS_DIR"/*.gguf
    stop_spinner true "Removed all GGUF models"
    
    # Remove models directory if empty
    if [[ -d "$MODELS_DIR" ]] && [[ -z "$(ls -A "$MODELS_DIR")" ]]; then
        rmdir "$MODELS_DIR"
        print_status "Removed empty models directory"
    fi
}

remove_config() {
    if [[ ! -f "$LOCAL_ENV" ]]; then
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_status "[DRY-RUN] Would remove: $LOCAL_ENV"
        return
    fi
    
    rm -f "$LOCAL_ENV"
    print_success "Removed .env configuration"
}

remove_opencode_provider() {
    if [[ ! -f "$OPENCODE_CONFIG" ]]; then
        return
    fi
    
    if ! command -v jq &>/dev/null; then
        print_error "jq is required to modify OpenCode config. Install with: sudo pacman -S jq"
        return
    fi
    
    if ! jq -e '.provider["llama.cpp"]' "$OPENCODE_CONFIG" &>/dev/null; then
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        print_status "[DRY-RUN] Would remove llama.cpp provider from: $OPENCODE_CONFIG"
        return
    fi
    
    # Backup first
    local backup
    backup="$OPENCODE_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$OPENCODE_CONFIG" "$backup"
    print_status "Backed up config to: $(basename "$backup")"
    
    # Remove llama.cpp provider
    local updated
    updated=$(jq 'del(.provider["llama.cpp"])' "$OPENCODE_CONFIG")
    echo "$updated" | jq . > "$OPENCODE_CONFIG"
    
    print_success "Removed llama.cpp provider config from OpenCode"
}

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

show_summary() {
    echo
    if [[ "$DRY_RUN" == true ]]; then
        if [[ "$HAS_GUM" == true ]]; then
            gum style \
                --foreground 214 \
                --bold \
                "Dry run complete - no changes made"
        else
            echo -e "${YELLOW}${BOLD}Dry run complete - no changes made${NC}"
        fi
    else
        if [[ "$HAS_GUM" == true ]]; then
            gum style \
                --foreground 82 \
                --bold \
                "Uninstall complete!"
        else
            print_success "Uninstall complete!"
        fi
        echo
        echo "To reinstall, run:"
        echo -e "  ${CYAN}./setup.sh${NC}"
    fi
    echo
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Check what exists
check_inventory

# If no specific options given, run interactive mode
if [[ "$REMOVE_ALL" == false && "$REMOVE_BUILD" == false && "$REMOVE_MODELS" == false && "$REMOVE_CONFIG" == false && "$REMOVE_OPENCODE" == false ]]; then
    if [[ "$HAS_GUM" == true ]]; then
        gum_selection
    else
        fallback_selection
    fi
fi

# Confirm what will be removed
confirm_removal

# Perform removal
echo
[[ "$REMOVE_BUILD" == true ]] && remove_build
[[ "$REMOVE_MODELS" == true ]] && remove_models
[[ "$REMOVE_CONFIG" == true ]] && remove_config
[[ "$REMOVE_OPENCODE" == true ]] && remove_opencode_provider

# Show summary
show_summary
