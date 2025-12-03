#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Ollama Uninstall Script
# Clean removal of Ollama and related configurations
# =============================================================================

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source common library
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

print_debug() { [ "$DEBUG_MODE" = true ] && echo -e "${DIM}[DEBUG]${NC} $1" || true; }

trap 'cleanup_spinner' EXIT

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

OLLAMA_DATA_DIR="${OLLAMA_DATA_DIR:-$HOME/.ollama}"
OPENCODE_CONFIG="$HOME/.config/opencode/opencode.json"
IS_MACOS=false
IS_LINUX=false

if [[ "$(uname -s)" == "Darwin" ]]; then
    IS_MACOS=true
elif [[ "$(uname -s)" == "Linux" ]]; then
    IS_LINUX=true
fi

# -----------------------------------------------------------------------------
# Detect Installed Dependencies
# -----------------------------------------------------------------------------

# Track which dependencies were likely installed for this setup
declare -a INSTALLED_DEPS

detect_dependencies() {
    INSTALLED_DEPS=()
    
    if [ "$IS_LINUX" = true ]; then
        command -v docker &>/dev/null && INSTALLED_DEPS+=("Docker")
        command -v gum &>/dev/null && INSTALLED_DEPS+=("gum")
        command -v bc &>/dev/null && INSTALLED_DEPS+=("bc")
        command -v curl &>/dev/null && INSTALLED_DEPS+=("curl")
    fi
    
    if [ "$IS_MACOS" = true ]; then
        command -v brew &>/dev/null && INSTALLED_DEPS+=("Homebrew")
        command -v gum &>/dev/null && INSTALLED_DEPS+=("gum")
        # Check for Bash 4+ installed via Homebrew
        [[ -x "/opt/homebrew/bin/bash" ]] && INSTALLED_DEPS+=("Bash 4+ (Homebrew)")
    fi
}

show_dependency_notice() {
    if [ ${#INSTALLED_DEPS[@]} -eq 0 ]; then
        return
    fi
    
    echo ""
    echo -e "${YELLOW}${BOLD}Dependencies not removed:${NC}"
    for dep in "${INSTALLED_DEPS[@]}"; do
        echo -e "  ${DIM}○ ${dep}${NC}"
    done
    echo ""
    echo -e "${DIM}These are kept because they may be used by other applications.${NC}"
    echo -e "${DIM}To remove them manually:${NC}"
    if [ "$IS_LINUX" = true ]; then
        echo -e "${DIM}  sudo pacman -R docker gum bc  # Arch${NC}"
        echo -e "${DIM}  sudo apt remove docker.io gum bc  # Ubuntu${NC}"
    fi
    if [ "$IS_MACOS" = true ]; then
        echo -e "${DIM}  brew uninstall gum${NC}"
        echo -e "${DIM}  # Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)\"${NC}"
    fi
    echo ""
}

# Parse command line arguments
FORCE=false
DRY_RUN=false
NON_INTERACTIVE=false
REMOVE_ALL=false
DEBUG_MODE=false

for arg in "$@"; do
    case $arg in
        --all) REMOVE_ALL=true; NON_INTERACTIVE=true; FORCE=true ;;
        --force|-f) FORCE=true ;;
        --dry-run) DRY_RUN=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --debug) DEBUG_MODE=true ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [OPTIONS]"
            echo ""
            echo "Interactively uninstall Ollama and select which components to remove."
            echo ""
            echo "Options:"
            echo "  --all              Remove everything (still confirms model deletion)"
            echo "  --force, -f        Skip final confirmation prompt"
            echo "  --dry-run          Show what would be removed without doing it"
            echo "  --non-interactive  Use default selections (container + image only)"
            echo "  --debug            Show detailed debug output for troubleshooting"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Model deletion always requires explicit y/N confirmation for safety."
            echo ""
            echo "Examples:"
            echo "  ./uninstall.sh              # Interactive selection"
            echo "  ./uninstall.sh --all        # Remove everything (confirms models)"
            echo "  ./uninstall.sh --dry-run    # Preview what would be removed"
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
# Banner
# -----------------------------------------------------------------------------

echo ""
echo -e "${CYAN}${BOLD}============================================${NC}"
echo -e "${CYAN}${BOLD}  Ollama Uninstall${NC}"
echo -e "${CYAN}${BOLD}============================================${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    print_warning "DRY RUN MODE - No changes will be made"
    echo ""
fi

# -----------------------------------------------------------------------------
# Dependency Check
# -----------------------------------------------------------------------------

# Check for gum (required for interactive mode)
if [ "$NON_INTERACTIVE" = false ]; then
    if ! command -v gum &>/dev/null; then
        print_error "gum is required for interactive mode but not installed"
        echo ""
        echo "Install gum:"
        echo "  Arch Linux:     sudo pacman -S gum"
        echo "  Fedora:         sudo dnf install gum"
        echo "  macOS:          brew install gum"
        echo "  Ubuntu/Debian:  See https://github.com/charmbracelet/gum#installation"
        echo ""
        echo "Or run with --non-interactive or --all to skip the interactive menu"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Detect Components
# -----------------------------------------------------------------------------

# All possible components
ALL_COMPONENTS=(container image brew models opencode env backups)

# Arrays to track what exists and what's selected
declare -A COMPONENT_EXISTS
declare -A COMPONENT_SELECTED
declare -A COMPONENT_DESC
declare -A COMPONENT_LABEL

# Initialize all to false
for comp in "${ALL_COMPONENTS[@]}"; do
    COMPONENT_EXISTS[$comp]=false
    COMPONENT_SELECTED[$comp]=false
    COMPONENT_DESC[$comp]=""
    COMPONENT_LABEL[$comp]=""
done

print_status "Detecting installed components..."

# Detect dependencies that will be kept
detect_dependencies

# Detect Linux Docker components
if [ "$IS_LINUX" = true ]; then
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
        COMPONENT_EXISTS[container]=true
        COMPONENT_SELECTED[container]=true  # Default selected
        COMPONENT_DESC[container]="Ollama Docker container"
        COMPONENT_LABEL[container]="container"
    fi
    
    if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q 'ollama/ollama:rocm'; then
        COMPONENT_EXISTS[image]=true
        COMPONENT_SELECTED[image]=true  # Default selected
        IMG_SIZE=$(docker images ollama/ollama:rocm --format "{{.Size}}" 2>/dev/null || echo "unknown")
        COMPONENT_DESC[image]="Ollama ROCm Docker image ($IMG_SIZE)"
        COMPONENT_LABEL[image]="image"
    fi
fi

# Detect macOS components
if [ "$IS_MACOS" = true ]; then
    if brew list ollama &>/dev/null 2>&1; then
        COMPONENT_EXISTS[brew]=true
        COMPONENT_SELECTED[brew]=true  # Default selected
        COMPONENT_DESC[brew]="Ollama (Homebrew)"
        COMPONENT_LABEL[brew]="brew"
    fi
fi

# Models directory
if [ -d "$OLLAMA_DATA_DIR" ]; then
    COMPONENT_EXISTS[models]=true
    MODEL_SIZE=$(du -sh "$OLLAMA_DATA_DIR" 2>/dev/null | cut -f1 || echo "unknown")
    COMPONENT_DESC[models]="Models directory: $OLLAMA_DATA_DIR ($MODEL_SIZE)"
    COMPONENT_LABEL[models]="models"
fi

# OpenCode config
if [ -f "$OPENCODE_CONFIG" ]; then
    COMPONENT_EXISTS[opencode]=true
    COMPONENT_DESC[opencode]="OpenCode config: $OPENCODE_CONFIG"
    COMPONENT_LABEL[opencode]="opencode"
fi

# Local .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    COMPONENT_EXISTS[env]=true
    COMPONENT_DESC[env]="Local .env file"
    COMPONENT_LABEL[env]="env"
fi

# Backup files
BACKUP_COUNT=$(find "$SCRIPT_DIR" -name "*.backup.*" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
if [ "$BACKUP_COUNT" -gt 0 ]; then
    COMPONENT_EXISTS[backups]=true
    COMPONENT_DESC[backups]="Backup files ($BACKUP_COUNT files)"
    COMPONENT_LABEL[backups]="backups"
fi

# Override selections if --all flag
if [ "$REMOVE_ALL" = true ]; then
    for comp in "${ALL_COMPONENTS[@]}"; do
        if [ "${COMPONENT_EXISTS[$comp]}" = true ]; then
            COMPONENT_SELECTED[$comp]=true
        fi
    done
fi

# Check if anything exists
ANYTHING_EXISTS=false
for comp in "${ALL_COMPONENTS[@]}"; do
    if [ "${COMPONENT_EXISTS[$comp]}" = true ]; then
        ANYTHING_EXISTS=true
        break
    fi
done

if [ "$ANYTHING_EXISTS" = false ]; then
    echo ""
    print_warning "No Ollama components found to uninstall"
    exit 0
fi

echo ""

# -----------------------------------------------------------------------------
# Interactive Selection with gum
# -----------------------------------------------------------------------------

if [ "$NON_INTERACTIVE" = false ]; then
    # Build options array for gum
    OPTIONS=()
    PRESELECTED=()
    
    for comp in "${ALL_COMPONENTS[@]}"; do
        if [ "${COMPONENT_EXISTS[$comp]}" = true ]; then
            OPTIONS+=("${COMPONENT_LABEL[$comp]}:${COMPONENT_DESC[$comp]}")
            if [ "${COMPONENT_SELECTED[$comp]}" = true ]; then
                PRESELECTED+=("${COMPONENT_LABEL[$comp]}:${COMPONENT_DESC[$comp]}")
            fi
        fi
    done
    
    # Build the --selected argument
    SELECTED_ARG=""
    if [ ${#PRESELECTED[@]} -gt 0 ]; then
        SELECTED_ARG=$(IFS=,; echo "${PRESELECTED[*]}")
    fi
    
    print_debug "OPTIONS array has ${#OPTIONS[@]} items"
    print_debug "PRESELECTED array has ${#PRESELECTED[@]} items"
    print_debug "SELECTED_ARG: '$SELECTED_ARG'"
    
    # Check if we have any options to show
    if [ ${#OPTIONS[@]} -eq 0 ]; then
        print_warning "No components detected to uninstall"
        exit 0
    fi
    
    # Show dependency notice before selection
    show_dependency_notice
    
    # Run gum choose
    echo -e "${BOLD}Select components to remove:${NC}"
    echo -e "${DIM}(Space or x to toggle, Enter to confirm, Ctrl+C to cancel)${NC}"
    echo ""
    
    # Temporarily disable exit on error for gum (it may return non-zero in some cases)
    set +e
    SELECTIONS=$(gum choose --no-limit \
        --cursor-prefix="○ " \
        --selected-prefix="✓ " \
        --unselected-prefix="○ " \
        --cursor.foreground="212" \
        --selected.foreground="212" \
        ${SELECTED_ARG:+--selected="$SELECTED_ARG"} \
        "${OPTIONS[@]}")
    GUM_EXIT_CODE=$?
    set -e
    
    # Only treat as cancellation if Ctrl+C (130) or genuine error with no output
    if [[ $GUM_EXIT_CODE -ne 0 && -z "$SELECTIONS" ]]; then
        echo ""
        print_status "Uninstall cancelled"
        exit 0
    fi
    
    # Reset all selections
    for comp in "${ALL_COMPONENTS[@]}"; do
        COMPONENT_SELECTED[$comp]=false
    done
    
    # Parse selections and update
    print_debug "Raw gum output: '$SELECTIONS'"
    if [[ -n "$SELECTIONS" ]]; then
        while IFS= read -r line; do
            # Skip empty lines
            [[ -z "$line" ]] && continue
            # Extract the component key (before the colon) and trim whitespace
            local_key="${line%%:*}"
            local_key="${local_key// /}"  # Remove any spaces
            print_debug "Parsed key: '$local_key'"
            # Only set if key is non-empty and exists in our components
            if [[ -n "$local_key" ]] && [[ "${COMPONENT_EXISTS[$local_key]+isset}" == "isset" ]]; then
                COMPONENT_SELECTED[$local_key]=true
                print_debug "Set COMPONENT_SELECTED[$local_key]=true"
            else
                print_debug "Skipping unknown key: '$local_key'"
            fi
        done <<< "$SELECTIONS"
    else
        print_debug "No selections from gum (empty output)"
    fi
    
    # Debug: show all final selections
    if [ "$DEBUG_MODE" = true ]; then
        for comp in "${ALL_COMPONENTS[@]}"; do
            print_debug "Final: COMPONENT_SELECTED[$comp]=${COMPONENT_SELECTED[$comp]}"
        done
    fi
    
    echo ""
fi

# -----------------------------------------------------------------------------
# Show Summary
# -----------------------------------------------------------------------------

print_header "Components to Remove"
echo ""

# Check if anything is selected
ANYTHING_SELECTED=false
for comp in "${ALL_COMPONENTS[@]}"; do
    if [ "${COMPONENT_SELECTED[$comp]}" = true ] && [ "${COMPONENT_EXISTS[$comp]}" = true ]; then
        ANYTHING_SELECTED=true
        break
    fi
done

if [ "$ANYTHING_SELECTED" = false ]; then
    if [ "$NON_INTERACTIVE" = true ]; then
        print_warning "No core components (container/image) found to remove"
        echo ""
        echo "Use --all to remove remaining components (models, config, etc.)"
        echo "Or run interactively: ./uninstall.sh"
    else
        print_warning "No components selected for removal"
        echo ""
        echo "Run again and select items to remove, or use --all to remove everything."
    fi
    exit 0
fi

# Show what will be removed
for comp in "${ALL_COMPONENTS[@]}"; do
    if [ "${COMPONENT_SELECTED[$comp]}" = true ] && [ "${COMPONENT_EXISTS[$comp]}" = true ]; then
        echo -e "  $CHECKMARK ${COMPONENT_DESC[$comp]}"
    fi
done

echo ""

# Show what will be kept
KEEPING_SOMETHING=false
for comp in "${ALL_COMPONENTS[@]}"; do
    if [ "${COMPONENT_EXISTS[$comp]}" = true ] && [ "${COMPONENT_SELECTED[$comp]}" = false ]; then
        if [ "$KEEPING_SOMETHING" = false ]; then
            echo -e "${DIM}Keeping:${NC}"
            KEEPING_SOMETHING=true
        fi
        echo -e "  ${DIM}○ ${COMPONENT_DESC[$comp]}${NC}"
    fi
done

if [ "$KEEPING_SOMETHING" = true ]; then
    echo ""
fi

# -----------------------------------------------------------------------------
# Final Confirmation
# -----------------------------------------------------------------------------

# Special confirmation for models deletion (requires explicit y/n even with --all)
if [ "${COMPONENT_SELECTED[models]}" = true ] && [ "${COMPONENT_EXISTS[models]}" = true ]; then
    echo ""
    if [ "$NON_INTERACTIVE" = true ]; then
        gum style --foreground 212 --bold "⚠ WARNING: Downloaded models will be permanently deleted!"
    else
        gum style --foreground 212 --bold "⚠ WARNING: Downloaded models will be permanently deleted!"
    fi
    echo ""
    
    # Always require confirmation for model deletion (even with --all or --force)
    if [ "$DRY_RUN" = false ]; then
        read -p "Delete all downloaded models? This cannot be undone. (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Keeping models, continuing with other removals..."
            COMPONENT_SELECTED[models]=false
        fi
    fi
fi

# Interactive confirmation for remaining items (skip if --force or --all)
if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    if ! gum confirm "Proceed with removal?"; then
        print_status "Uninstall cancelled"
        exit 0
    fi
    echo ""
fi

# -----------------------------------------------------------------------------
# Perform Uninstall
# -----------------------------------------------------------------------------

print_header "Removing Components"

# Temporarily disable exit on error for removal operations
# (we handle errors gracefully within each section)
set +e

# Helper to check if item should be removed
should_remove() {
    local name="$1"
    [ "${COMPONENT_SELECTED[$name]}" = true ] && [ "${COMPONENT_EXISTS[$name]}" = true ]
}

# Helper to check if container is running
container_is_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'
}

# -----------------------------------------------------------------------------
# Remove Models via API (before stopping container)
# -----------------------------------------------------------------------------
# This removes model data through the Ollama API, avoiding permission issues
# Must happen BEFORE container is removed

if should_remove "models" && [ "$DRY_RUN" = false ]; then
    if container_is_running; then
        print_status "Removing models via Ollama API..."
        INSTALLED_MODELS=$(docker exec ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
        if [ -n "$INSTALLED_MODELS" ]; then
            while IFS= read -r model; do
                [ -z "$model" ] && continue
                print_status "  Removing $model..."
                docker exec ollama ollama rm "$model" 2>/dev/null || true
            done <<< "$INSTALLED_MODELS"
            print_success "Models removed via API"
        else
            print_status "No models found in Ollama"
        fi
    else
        print_debug "Container not running, will remove models directory directly"
    fi
fi

# -----------------------------------------------------------------------------
# Remove Container and Image
# -----------------------------------------------------------------------------

# Linux: Docker-based removal
if [ "$IS_LINUX" = true ]; then
    print_debug "IS_LINUX=true, checking container removal..."
    if should_remove "container"; then
        print_status "Stopping Ollama container..."
        if [ "$DRY_RUN" = false ]; then
            # Stop container gracefully first
            docker stop ollama 2>/dev/null || true
            # Wait for container to fully stop
            docker wait ollama 2>/dev/null || true
            # Now remove it
            print_status "Removing Ollama container..."
            docker compose down --volumes 2>/dev/null || true
            docker rm -f ollama 2>/dev/null || true
        fi
        print_success "Container removed"
    fi
    
    print_debug "Checking image removal..."
    if should_remove "image"; then
        print_status "Removing Ollama Docker image..."
        if [ "$DRY_RUN" = false ]; then
            docker rmi ollama/ollama:rocm 2>/dev/null || true
        fi
        print_success "Docker image removed"
    fi
fi

print_debug "Finished Docker section"

# macOS: Homebrew-based removal
if [ "$IS_MACOS" = true ]; then
    print_debug "IS_MACOS=true, checking brew removal..."
    if should_remove "brew"; then
        print_status "Stopping Ollama service..."
        if [ "$DRY_RUN" = false ]; then
            brew services stop ollama 2>/dev/null || true
            # Wait a moment for service to stop
            sleep 1
            pkill -x ollama 2>/dev/null || true
        fi
        
        print_status "Uninstalling Ollama via Homebrew..."
        if [ "$DRY_RUN" = false ]; then
            brew uninstall ollama 2>/dev/null || true
        fi
        print_success "Ollama uninstalled"
    fi
fi

# -----------------------------------------------------------------------------
# Remove Models Directory
# -----------------------------------------------------------------------------
# Note: With non-root container configuration, the models directory should be
# owned by the user, so sudo should rarely be needed. The sudo fallback handles
# legacy installations that ran as root.

print_debug "Checking models: SELECTED=${COMPONENT_SELECTED[models]:-unset} EXISTS=${COMPONENT_EXISTS[models]:-unset}"

# Remove models directory (should be mostly empty now if API removal worked)
if should_remove "models"; then
    print_debug "should_remove models returned true"
    if [ "$DRY_RUN" = false ]; then
        start_spinner "Removing models directory: $OLLAMA_DATA_DIR"
        # Try normal removal first, fall back to sudo if permission denied
        if ! rm -rf "$OLLAMA_DATA_DIR" 2>/dev/null; then
            stop_spinner false
            print_warning "Permission denied, trying with sudo..."
            if ! sudo rm -rf "$OLLAMA_DATA_DIR"; then
                print_error "Failed to remove models directory (sudo required)"
                print_status "Remove manually with: sudo rm -rf $OLLAMA_DATA_DIR"
            else
                print_success "Models removed"
            fi
        else
            stop_spinner true "Models removed"
        fi
    else
        print_status "Would remove: $OLLAMA_DATA_DIR"
    fi
fi

# Remove OpenCode config
if should_remove "opencode"; then
    print_status "Removing OpenCode config: $OPENCODE_CONFIG"
    if [ "$DRY_RUN" = false ]; then
        rm -f "$OPENCODE_CONFIG"
    fi
    print_success "OpenCode config removed"
fi

# Remove local .env
if should_remove "env"; then
    print_status "Removing local .env file"
    if [ "$DRY_RUN" = false ]; then
        rm -f "$SCRIPT_DIR/.env"
    fi
    print_success "Local .env removed"
fi

# Remove backup files
if should_remove "backups"; then
    print_status "Removing backup files"
    if [ "$DRY_RUN" = false ]; then
        find "$SCRIPT_DIR" -name "*.backup.*" -delete 2>/dev/null || true
    fi
    print_success "Backup files removed"
fi

# Re-enable exit on error
set -e

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

print_header "Uninstall Complete"

echo ""
if [ "$DRY_RUN" = true ]; then
    print_warning "DRY RUN - No changes were made"
    echo ""
    echo "Run without --dry-run to perform the uninstall."
else
    print_success "Selected components have been removed"
    
    # Show notes about kept items
    echo ""
    if [ "${COMPONENT_EXISTS[models]}" = true ] && [ "${COMPONENT_SELECTED[models]}" = false ]; then
        echo -e "${DIM}Note: Models still exist at $OLLAMA_DATA_DIR${NC}"
    fi
    
    if [ "${COMPONENT_EXISTS[opencode]}" = true ] && [ "${COMPONENT_SELECTED[opencode]}" = false ]; then
        echo -e "${DIM}Note: OpenCode config still exists at $OPENCODE_CONFIG${NC}"
    fi
    
    if [ "${COMPONENT_EXISTS[env]}" = true ] && [ "${COMPONENT_SELECTED[env]}" = false ]; then
        echo -e "${DIM}Note: .env file kept (useful for reinstalling)${NC}"
    fi
    
    # Always show dependency notice at the end
    show_dependency_notice
fi

echo ""
if [ "$IS_MACOS" = true ]; then
    echo "To reinstall, run: ./setup-macos.sh"
else
    echo "To reinstall, run: ./setup.sh"
fi
echo ""
