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
CROSSMARK="${RED}✗${NC}"

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_header() { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

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
REMOVE_MODELS=false
REMOVE_OPENCODE=false
REMOVE_ALL=false
FORCE=false
DRY_RUN=false

for arg in "$@"; do
    case $arg in
        --models) REMOVE_MODELS=true ;;
        --opencode) REMOVE_OPENCODE=true ;;
        --all) REMOVE_ALL=true ;;
        --force|-f) FORCE=true ;;
        --dry-run) DRY_RUN=true ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [OPTIONS]"
            echo ""
            echo "Uninstalls Ollama and optionally removes related data."
            echo ""
            echo "Options:"
            echo "  --models      Remove downloaded models (~/.ollama)"
            echo "  --opencode    Remove OpenCode Ollama configuration"
            echo "  --all         Remove everything (models + opencode config)"
            echo "  --force, -f   Skip confirmation prompts"
            echo "  --dry-run     Show what would be removed without doing it"
            echo "  --help, -h    Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./uninstall.sh                  # Remove Ollama container only"
            echo "  ./uninstall.sh --models         # Also remove downloaded models"
            echo "  ./uninstall.sh --all            # Remove everything"
            echo "  ./uninstall.sh --all --dry-run  # Preview full removal"
            exit 0
            ;;
        *)
            print_error "Unknown option: $arg"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# --all implies both
if [ "$REMOVE_ALL" = true ]; then
    REMOVE_MODELS=true
    REMOVE_OPENCODE=true
fi

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
# Show what will be removed
# -----------------------------------------------------------------------------

print_header "Components to Remove"

echo ""
echo -e "  ${BOLD}Core:${NC}"

if [ "$IS_LINUX" = true ]; then
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^ollama$'; then
        echo -e "    $CHECKMARK Ollama Docker container"
        CONTAINER_EXISTS=true
    else
        echo -e "    $CROSSMARK Ollama Docker container (not found)"
        CONTAINER_EXISTS=false
    fi
    
    if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q 'ollama/ollama:rocm'; then
        echo -e "    $CHECKMARK Ollama ROCm Docker image"
        IMAGE_EXISTS=true
    else
        echo -e "    $CROSSMARK Ollama ROCm Docker image (not found)"
        IMAGE_EXISTS=false
    fi
elif [ "$IS_MACOS" = true ]; then
    if brew list ollama &>/dev/null 2>&1; then
        echo -e "    $CHECKMARK Ollama (Homebrew)"
        BREW_INSTALLED=true
    else
        echo -e "    $CROSSMARK Ollama (not installed via Homebrew)"
        BREW_INSTALLED=false
    fi
    
    if pgrep -x "ollama" &>/dev/null; then
        echo -e "    $CHECKMARK Ollama service (running)"
        SERVICE_RUNNING=true
    else
        echo -e "    $CROSSMARK Ollama service (not running)"
        SERVICE_RUNNING=false
    fi
fi

echo ""
echo -e "  ${BOLD}Data:${NC}"

if [ "$REMOVE_MODELS" = true ]; then
    if [ -d "$OLLAMA_DATA_DIR" ]; then
        MODEL_SIZE=$(du -sh "$OLLAMA_DATA_DIR" 2>/dev/null | cut -f1 || echo "unknown")
        echo -e "    $CHECKMARK Models directory: $OLLAMA_DATA_DIR ($MODEL_SIZE)"
        MODELS_EXIST=true
    else
        echo -e "    $CROSSMARK Models directory (not found)"
        MODELS_EXIST=false
    fi
else
    if [ -d "$OLLAMA_DATA_DIR" ]; then
        MODEL_SIZE=$(du -sh "$OLLAMA_DATA_DIR" 2>/dev/null | cut -f1 || echo "unknown")
        echo -e "    ${DIM}○ Models directory: $OLLAMA_DATA_DIR ($MODEL_SIZE) - KEEPING${NC}"
    fi
fi

echo ""
echo -e "  ${BOLD}Configuration:${NC}"

if [ "$REMOVE_OPENCODE" = true ]; then
    if [ -f "$OPENCODE_CONFIG" ]; then
        echo -e "    $CHECKMARK OpenCode config: $OPENCODE_CONFIG"
        OPENCODE_EXISTS=true
    else
        echo -e "    $CROSSMARK OpenCode config (not found)"
        OPENCODE_EXISTS=false
    fi
else
    if [ -f "$OPENCODE_CONFIG" ]; then
        echo -e "    ${DIM}○ OpenCode config: $OPENCODE_CONFIG - KEEPING${NC}"
    fi
fi

# Local .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo -e "    $CHECKMARK Local .env file"
    ENV_EXISTS=true
else
    echo -e "    $CROSSMARK Local .env file (not found)"
    ENV_EXISTS=false
fi

echo ""

# -----------------------------------------------------------------------------
# Confirmation
# -----------------------------------------------------------------------------

if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    echo -e "${YELLOW}${BOLD}WARNING:${NC} This will remove the above components."
    if [ "$REMOVE_MODELS" = true ]; then
        echo -e "${YELLOW}         Downloaded models will be permanently deleted!${NC}"
    fi
    echo ""
    read -p "Are you sure you want to continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "Uninstall cancelled"
        exit 0
    fi
    echo ""
fi

# -----------------------------------------------------------------------------
# Perform Uninstall
# -----------------------------------------------------------------------------

print_header "Removing Components"

# Linux: Docker-based removal
if [ "$IS_LINUX" = true ]; then
    # Stop and remove container
    if [ "${CONTAINER_EXISTS:-false}" = true ]; then
        print_status "Stopping Ollama container..."
        if [ "$DRY_RUN" = false ]; then
            docker compose down 2>/dev/null || docker stop ollama 2>/dev/null || true
            docker rm -f ollama 2>/dev/null || true
        fi
        print_success "Container removed"
    fi
    
    # Remove Docker image
    if [ "${IMAGE_EXISTS:-false}" = true ]; then
        print_status "Removing Ollama Docker image..."
        if [ "$DRY_RUN" = false ]; then
            docker rmi ollama/ollama:rocm 2>/dev/null || true
        fi
        print_success "Docker image removed"
    fi
fi

# macOS: Homebrew-based removal
if [ "$IS_MACOS" = true ]; then
    # Stop service
    if [ "${SERVICE_RUNNING:-false}" = true ]; then
        print_status "Stopping Ollama service..."
        if [ "$DRY_RUN" = false ]; then
            brew services stop ollama 2>/dev/null || true
            pkill -x ollama 2>/dev/null || true
        fi
        print_success "Service stopped"
    fi
    
    # Uninstall via Homebrew
    if [ "${BREW_INSTALLED:-false}" = true ]; then
        print_status "Uninstalling Ollama via Homebrew..."
        if [ "$DRY_RUN" = false ]; then
            brew uninstall ollama 2>/dev/null || true
        fi
        print_success "Ollama uninstalled"
    fi
fi

# Remove models directory
if [ "$REMOVE_MODELS" = true ] && [ "${MODELS_EXIST:-false}" = true ]; then
    print_status "Removing models directory: $OLLAMA_DATA_DIR"
    if [ "$DRY_RUN" = false ]; then
        rm -rf "$OLLAMA_DATA_DIR"
    fi
    print_success "Models removed"
fi

# Remove OpenCode config
if [ "$REMOVE_OPENCODE" = true ] && [ "${OPENCODE_EXISTS:-false}" = true ]; then
    print_status "Removing OpenCode config: $OPENCODE_CONFIG"
    if [ "$DRY_RUN" = false ]; then
        rm -f "$OPENCODE_CONFIG"
    fi
    print_success "OpenCode config removed"
fi

# Remove local .env
if [ "${ENV_EXISTS:-false}" = true ]; then
    print_status "Removing local .env file"
    if [ "$DRY_RUN" = false ]; then
        rm -f "$SCRIPT_DIR/.env"
    fi
    print_success "Local .env removed"
fi

# Remove backup files
BACKUP_COUNT=$(find "$SCRIPT_DIR" -name "*.backup.*" 2>/dev/null | wc -l || echo "0")
if [ "$BACKUP_COUNT" -gt 0 ]; then
    print_status "Removing $BACKUP_COUNT backup file(s)"
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
    print_success "Ollama has been uninstalled"
    echo ""
    
    if [ "$REMOVE_MODELS" = false ] && [ -d "$OLLAMA_DATA_DIR" ]; then
        echo -e "${DIM}Note: Models still exist at $OLLAMA_DATA_DIR${NC}"
        echo -e "${DIM}      Run with --models to remove them${NC}"
    fi
    
    if [ "$REMOVE_OPENCODE" = false ] && [ -f "$OPENCODE_CONFIG" ]; then
        echo -e "${DIM}Note: OpenCode config still exists at $OPENCODE_CONFIG${NC}"
        echo -e "${DIM}      Run with --opencode to remove it${NC}"
    fi
fi

echo ""
echo "To reinstall, run: ./setup.sh"
echo ""
