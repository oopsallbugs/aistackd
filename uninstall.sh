#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Ollama Uninstall Script
# Clean removal of Ollama and related configurations
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
DIM='\033[2m'
NC='\033[0m'
CHECKMARK="${GREEN}✓${NC}"

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

# Spinner for operations without their own progress indicator
SPINNER_CHARS='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
SPINNER_PID=""

cleanup_spinner() {
    if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null
    fi
    SPINNER_PID=""
    printf "\r\033[K"  # Clear the line
}

trap cleanup_spinner EXIT

start_spinner() {
    local message="$1"
    local start_time=$SECONDS
    (
        local i=0
        local spin_len=${#SPINNER_CHARS}
        while true; do
            local elapsed=$((SECONDS - start_time))
            printf "\r  ${CYAN}%s${NC} %s ${DIM}(%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$elapsed"
            i=$(( (i + 1) % spin_len ))
            sleep 0.1
        done
    ) &
    SPINNER_PID=$!
}

stop_spinner() {
    local success=${1:-true}
    local message="${2:-}"
    
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null
        SPINNER_PID=""
    fi
    printf "\r\033[K"  # Clear the line
    
    if [[ -n "$message" ]]; then
        if [[ "$success" == "true" ]]; then
            print_success "$message"
        else
            print_error "$message"
        fi
    fi
}

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

# Parse command line arguments
FORCE=false
DRY_RUN=false
NON_INTERACTIVE=false
REMOVE_ALL=false

for arg in "$@"; do
    case $arg in
        --all) REMOVE_ALL=true; NON_INTERACTIVE=true ;;
        --force|-f) FORCE=true ;;
        --dry-run) DRY_RUN=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [OPTIONS]"
            echo ""
            echo "Interactively uninstall Ollama and select which components to remove."
            echo ""
            echo "Options:"
            echo "  --all              Remove everything (no prompts)"
            echo "  --force, -f        Skip final confirmation prompt"
            echo "  --dry-run          Show what would be removed without doing it"
            echo "  --non-interactive  Use default selections (container + image only)"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./uninstall.sh              # Interactive selection"
            echo "  ./uninstall.sh --all        # Remove everything"
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
    
    # Run gum choose
    echo -e "${BOLD}Select components to remove:${NC}"
    echo -e "${DIM}(Space to toggle, Enter to confirm, Ctrl+C to cancel)${NC}"
    echo ""
    
    SELECTIONS=$(gum choose --no-limit \
        --cursor-prefix="○ " \
        --selected-prefix="✓ " \
        --unselected-prefix="○ " \
        --cursor.foreground="212" \
        --selected.foreground="212" \
        ${SELECTED_ARG:+--selected="$SELECTED_ARG"} \
        "${OPTIONS[@]}") || {
        echo ""
        print_status "Uninstall cancelled"
        exit 0
    }
    
    # Reset all selections
    for comp in "${ALL_COMPONENTS[@]}"; do
        COMPONENT_SELECTED[$comp]=false
    done
    
    # Parse selections and update
    while IFS= read -r line; do
        # Extract the component key (before the colon)
        local_key="${line%%:*}"
        if [ -n "$local_key" ]; then
            COMPONENT_SELECTED[$local_key]=true
        fi
    done <<< "$SELECTIONS"
    
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

if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    # Check if models are selected (big warning)
    if [ "${COMPONENT_SELECTED[models]}" = true ] && [ "${COMPONENT_EXISTS[models]}" = true ]; then
        echo ""
        gum style --foreground 212 --bold "⚠ WARNING: Downloaded models will be permanently deleted!"
        echo ""
    fi
    
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

# Helper to check if item should be removed
should_remove() {
    local name="$1"
    [ "${COMPONENT_SELECTED[$name]}" = true ] && [ "${COMPONENT_EXISTS[$name]}" = true ]
}

# Linux: Docker-based removal
if [ "$IS_LINUX" = true ]; then
    if should_remove "container"; then
        print_status "Stopping and removing Ollama container..."
        if [ "$DRY_RUN" = false ]; then
            docker compose down 2>/dev/null || docker stop ollama 2>/dev/null || true
            docker rm -f ollama 2>/dev/null || true
        fi
        print_success "Container removed"
    fi
    
    if should_remove "image"; then
        print_status "Removing Ollama Docker image..."
        if [ "$DRY_RUN" = false ]; then
            docker rmi ollama/ollama:rocm 2>/dev/null || true
        fi
        print_success "Docker image removed"
    fi
fi

# macOS: Homebrew-based removal
if [ "$IS_MACOS" = true ]; then
    if should_remove "brew"; then
        print_status "Stopping Ollama service..."
        if [ "$DRY_RUN" = false ]; then
            brew services stop ollama 2>/dev/null || true
            pkill -x ollama 2>/dev/null || true
        fi
        
        print_status "Uninstalling Ollama via Homebrew..."
        if [ "$DRY_RUN" = false ]; then
            brew uninstall ollama 2>/dev/null || true
        fi
        print_success "Ollama uninstalled"
    fi
fi

# Remove models directory
if should_remove "models"; then
    if [ "$DRY_RUN" = false ]; then
        start_spinner "Removing models directory: $OLLAMA_DATA_DIR"
        # Try normal removal first, fall back to sudo if permission denied
        if ! rm -rf "$OLLAMA_DATA_DIR" 2>/dev/null; then
            stop_spinner false
            print_warning "Permission denied, trying with sudo..."
            sudo rm -rf "$OLLAMA_DATA_DIR"
        fi
        stop_spinner true "Models removed"
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
fi

echo ""
echo "To reinstall, run: ./setup.sh"
echo ""
