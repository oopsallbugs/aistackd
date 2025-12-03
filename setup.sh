#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp ROCm/HIP Setup Script
# Linux-only setup for AMD GPUs with automatic system detection
# =============================================================================

# -----------------------------------------------------------------------------
# OS Check - This script is Linux-only (ROCm/HIP)
# -----------------------------------------------------------------------------

if [[ "$(uname -s)" != "Linux" ]]; then
    echo
    echo "ERROR: This setup script is for Linux only."
    echo
    echo "ROCm/HIP (AMD's GPU compute platform) is Linux-only."
    echo
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "For macOS, use setup-macos.sh instead (Metal backend)."
        echo
        echo "  ./setup-macos.sh"
    fi
    echo
    exit 1
fi

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Source Common Library
# -----------------------------------------------------------------------------

if [[ ! -f "$SCRIPT_DIR/lib/common.sh" ]]; then
    echo "ERROR: lib/common.sh not found"
    echo "Please ensure the repository is complete."
    exit 1
fi

# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

# Initialize paths
init_paths "$SCRIPT_DIR"

# Set up signal handlers
setup_signal_handlers

# -----------------------------------------------------------------------------
# Error Handling (ROCm-specific messages)
# -----------------------------------------------------------------------------

handle_error() {
    local exit_code=$1
    local line_number=$2
    
    # Don't show error message if user cancelled (Ctrl+C)
    if [[ "$USER_INTERRUPTED" == true ]] || [[ $exit_code -eq 130 ]]; then
        exit "$exit_code"
    fi
    
    echo
    print_error "Something went wrong during setup."
    echo
    echo "Common solutions:"
    echo "  1. Make sure ROCm is installed:"
    echo "     rocminfo"
    echo
    echo "  2. Check HIP is available:"
    echo "     hipconfig --version"
    echo
    echo "  3. Ensure you have build tools:"
    echo "     cmake --version && make --version"
    echo
    echo -e "${DIM}(Technical: error on line $line_number, exit code $exit_code)${NC}"
    exit "$exit_code"
}

trap 'handle_error $? $LINENO' ERR

# -----------------------------------------------------------------------------
# GPU Detection (ROCm-specific)
# -----------------------------------------------------------------------------

# Get HSA override version based on GPU architecture
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

detect_amd_gpu() {
    local gpu_info
    gpu_info=$(lspci 2>/dev/null | grep -i 'vga.*amd\|display.*amd' | head -1) || true
    
    if [[ -z "$gpu_info" ]]; then
        echo "unknown|Unknown AMD GPU|gfx900"
        return
    fi
    
    # Map GPU to architecture
    if [[ "$gpu_info" =~ "Navi 31" ]]; then
        echo "navi31|RX 7900 XTX/XT/GRE|gfx1100"
    elif [[ "$gpu_info" =~ "Navi 32" ]]; then
        echo "navi32|RX 7800/7700 XT|gfx1101"
    elif [[ "$gpu_info" =~ "Navi 33" ]]; then
        echo "navi33|RX 7600|gfx1102"
    elif [[ "$gpu_info" =~ "Navi 21" ]]; then
        echo "navi21|RX 6900/6800 XT|gfx1030"
    elif [[ "$gpu_info" =~ "Navi 22" ]]; then
        echo "navi22|RX 6700 XT|gfx1031"
    elif [[ "$gpu_info" =~ "Navi 23" ]]; then
        echo "navi23|RX 6600 XT/6600|gfx1032"
    elif [[ "$gpu_info" =~ "Navi 10" ]]; then
        echo "navi10|RX 5700 XT/5700|gfx1010"
    elif [[ "$gpu_info" =~ "Vega 20" ]]; then
        echo "vega20|Radeon VII|gfx906"
    elif [[ "$gpu_info" =~ "Vega 10" ]]; then
        echo "vega10|RX Vega 64/56|gfx900"
    else
        echo "unknown|Unknown AMD GPU|gfx900"
    fi
}

# -----------------------------------------------------------------------------
# VRAM Detection (ROCm-specific)
# -----------------------------------------------------------------------------

DETECTED_VRAM_GB=""

get_vram_gb() {
    if [[ -n "$DETECTED_VRAM_GB" ]]; then
        echo "$DETECTED_VRAM_GB"
        return
    fi
    
    local vram_mb=""
    
    # Try rocm-smi first (most reliable for AMD GPUs)
    if command -v rocm-smi &>/dev/null; then
        vram_mb=$(rocm-smi --showmeminfo vram 2>/dev/null | grep -i "total" | head -1 | grep -oE '[0-9]+' | head -1)
    fi
    
    # Fallback: try to parse from rocminfo
    if [[ -z "$vram_mb" ]] && command -v rocminfo &>/dev/null; then
        vram_mb=$(rocminfo 2>/dev/null | grep -A 20 "Pool 1" | grep "Size:" | head -1 | grep -oE '[0-9]+')
    fi
    
    # Convert MB to GB
    if [[ -n "$vram_mb" && "$vram_mb" =~ ^[0-9]+$ ]]; then
        DETECTED_VRAM_GB=$((vram_mb / 1024))
        echo "$DETECTED_VRAM_GB"
    else
        DETECTED_VRAM_GB=0
        echo "0"
    fi
}

# Hardware status functions are now in lib/common.sh:
# - get_model_size_gb()
# - get_model_hardware_status()
# - format_hardware_tag()

# -----------------------------------------------------------------------------
# Command Line Arguments
# -----------------------------------------------------------------------------

SKIP_BUILD=false
SKIP_MODELS=false
FORCE_REBUILD=false
NON_INTERACTIVE=false
IGNORE_WARNINGS=false
RUN_STATUS=false
RUN_UPDATE=false
FIX_PERMISSIONS=false
RUN_VERIFY=false
VERIFY_MODEL=""
GPU_TARGET=""
FORCE_ENV=false
RESET_AGENTS=false
SKIP_UPDATE_CHECK=false

for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --skip-models) SKIP_MODELS=true ;;
        --force-rebuild) FORCE_REBUILD=true ;;
        --force-env) FORCE_ENV=true ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --ignore-warnings) IGNORE_WARNINGS=true ;;
        --status) RUN_STATUS=true ;;
        --update) RUN_UPDATE=true ;;
        --fix-permissions) FIX_PERMISSIONS=true ;;
        --verify) RUN_VERIFY=true ;;
        --verify=*) RUN_VERIFY=true; VERIFY_MODEL="${arg#*=}" ;;
        --reset-agents) RESET_AGENTS=true ;;
        --no-update-check) SKIP_UPDATE_CHECK=true ;;
        --help|-h)
            echo "Usage: ./setup.sh [OPTIONS]"
            echo
            echo "Commands:"
            echo "  --status            Show current llama.cpp status"
            echo "  --update            Update llama.cpp to latest version and rebuild"
            echo "  --fix-permissions   Fix GPU access permissions (add user to groups)"
            echo "  --verify[=model]    Verify model file integrity (all or specific)"
            echo "  --reset-agents      Reset agent files to defaults"
            echo
            echo "Setup Options:"
            echo "  --skip-build        Skip building llama.cpp (use existing build)"
            echo "  --skip-models       Skip model selection and downloading"
            echo "  --force-rebuild     Force rebuild even if build exists"
            echo "  --force-env         Regenerate .env file even if it exists"
            echo "  --non-interactive   Use default selections (no prompts)"
            echo "  --ignore-warnings   Continue setup despite permission warnings"
            echo "  --no-update-check   Skip checking for updates"
            echo "  --help, -h          Show this help message"
            echo
            echo "Files:"
            echo "  models.conf         Edit to customize available GGUF models"
            echo "  models-metadata.conf  Display names and context limits for OpenCode"
            echo "  .env                Local configuration"
            echo "  .env.example        Template with all available settings"
            echo
            echo "Examples:"
            echo "  ./setup.sh                      # Interactive setup"
            echo "  ./setup.sh --status             # Check current status"
            echo "  ./setup.sh --update             # Update llama.cpp"
            echo "  ./setup.sh --fix-permissions    # Fix GPU permissions"
            echo "  ./setup.sh --verify             # Verify all downloaded models"
            echo "  ./setup.sh --non-interactive    # Automated setup with defaults"
            exit 0
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Reset Agents Mode
# -----------------------------------------------------------------------------

if [[ $RESET_AGENTS == true ]]; then
    OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
    sync_agents "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "false" "true"
    exit 0
fi

# -----------------------------------------------------------------------------
# Status Mode
# -----------------------------------------------------------------------------

if [[ $RUN_STATUS == true ]]; then
    print_header "llama.cpp Status"
    echo
    
    # Build status
    echo -e "  ${BOLD}Build:${NC}"
    if [[ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]]; then
        echo -e "    $CHECKMARK llama-server binary: ${GREEN}found${NC}"
        echo -e "    $CHECKMARK Location: $LLAMA_CPP_DIR/build/bin/llama-server"
    else
        echo -e "    $CROSSMARK llama-server binary: ${RED}not built${NC}"
        echo -e "    ${DIM}Run ./setup.sh to build${NC}"
    fi
    
    # Server status
    echo
    echo -e "  ${BOLD}Server:${NC}"
    if curl -sf "http://127.0.0.1:$DEFAULT_PORT/health" &>/dev/null; then
        echo -e "    $CHECKMARK Status: ${GREEN}running${NC}"
        echo -e "    $CHECKMARK Endpoint: http://127.0.0.1:$DEFAULT_PORT"
    else
        echo -e "    $CROSSMARK Status: ${RED}not running${NC}"
        echo -e "    ${DIM}Start with: ./start-server.sh <model>${NC}"
    fi
    
    # Models
    echo
    echo -e "  ${BOLD}Downloaded Models:${NC}"
    if [[ -d "$MODELS_DIR" ]]; then
        model_count=0
        for gguf in "$MODELS_DIR"/*.gguf; do
            [[ -f "$gguf" ]] || continue
            fname=$(basename "$gguf")
            fsize=$(du -h "$gguf" | cut -f1)
            echo -e "    - $fname ($fsize)"
            ((model_count++))
        done
        if [[ $model_count -eq 0 ]]; then
            echo -e "    ${DIM}No models downloaded${NC}"
        fi
    else
        echo -e "    ${DIM}Models directory not found${NC}"
    fi
    
    # GPU
    echo
    echo -e "  ${BOLD}GPU:${NC}"
    IFS='|' read -r _GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
    echo -e "    $CHECKMARK Detected: ${GREEN}$GPU_NAME${NC}"
    echo -e "    $CHECKMARK Target: $GPU_TARGET"
    
    # VRAM
    vram_gb=$(get_vram_gb)
    if [[ "$vram_gb" -gt 0 ]]; then
        echo -e "    $CHECKMARK VRAM: ${GREEN}${vram_gb}GB${NC}"
    fi
    
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Fix Permissions Mode
# -----------------------------------------------------------------------------

if [[ $FIX_PERMISSIONS == true ]]; then
    print_header "Fixing GPU Access Permissions"
    echo
    
    CURRENT_USER=$(whoami)
    CHANGES_MADE=false
    NEEDS_LOGOUT=false
    
    # Check video group
    if getent group video &>/dev/null; then
        if groups "$CURRENT_USER" | grep -qw video; then
            echo -e "  $CHECKMARK User '$CURRENT_USER' already in 'video' group"
        else
            echo -e "  ${YELLOW}Adding '$CURRENT_USER' to 'video' group...${NC}"
            if sudo usermod -aG video "$CURRENT_USER"; then
                echo -e "  $CHECKMARK Added to 'video' group"
                CHANGES_MADE=true
                NEEDS_LOGOUT=true
            else
                echo -e "  $CROSSMARK Failed to add to 'video' group"
            fi
        fi
    else
        echo -e "  $WARNMARK 'video' group does not exist on this system"
    fi
    
    # Check render group
    if getent group render &>/dev/null; then
        if groups "$CURRENT_USER" | grep -qw render; then
            echo -e "  $CHECKMARK User '$CURRENT_USER' already in 'render' group"
        else
            echo -e "  ${YELLOW}Adding '$CURRENT_USER' to 'render' group...${NC}"
            if sudo usermod -aG render "$CURRENT_USER"; then
                echo -e "  $CHECKMARK Added to 'render' group"
                CHANGES_MADE=true
                NEEDS_LOGOUT=true
            else
                echo -e "  $CROSSMARK Failed to add to 'render' group"
            fi
        fi
    else
        echo -e "  $WARNMARK 'render' group does not exist on this system"
    fi
    
    # Check /dev/kfd permissions
    echo
    echo -e "  ${BOLD}Device Permissions:${NC}"
    if [[ -e /dev/kfd ]]; then
        if [[ -r /dev/kfd && -w /dev/kfd ]]; then
            echo -e "  $CHECKMARK /dev/kfd is accessible"
        else
            echo -e "  $CROSSMARK /dev/kfd exists but is not accessible"
            echo -e "    ${DIM}This may require a logout/login after group changes${NC}"
        fi
    else
        echo -e "  $CROSSMARK /dev/kfd not found - ROCm may not be installed"
    fi
    
    # Check /dev/dri permissions
    if [[ -d /dev/dri ]]; then
        if [[ -r /dev/dri/renderD128 ]]; then
            echo -e "  $CHECKMARK /dev/dri/renderD128 is accessible"
        else
            echo -e "  $CROSSMARK /dev/dri/renderD128 not accessible"
        fi
    fi
    
    echo
    if [[ $NEEDS_LOGOUT == true ]]; then
        print_warning "Group changes require logout/login to take effect"
        echo
        echo "Options:"
        echo "  1. Log out and log back in"
        echo "  2. Reboot your system"
        echo "  3. Run: newgrp video && newgrp render (temporary, current shell only)"
        echo
    elif [[ $CHANGES_MADE == false ]]; then
        print_success "All permissions are correctly configured!"
    fi
    
    exit 0
fi

# -----------------------------------------------------------------------------
# Update Mode
# -----------------------------------------------------------------------------

if [[ $RUN_UPDATE == true ]]; then
    print_header "Updating llama.cpp"
    echo
    
    if [[ ! -d "$LLAMA_CPP_DIR" ]]; then
        print_error "llama.cpp not found at: $LLAMA_CPP_DIR"
        echo "Run ./setup.sh first to clone and build llama.cpp"
        exit 1
    fi
    
    cd "$LLAMA_CPP_DIR"
    
    # Get current commit
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    print_status "Current version: $CURRENT_COMMIT"
    
    # Fetch and check for updates
    print_status "Checking for updates..."
    if ! git fetch origin main --quiet 2>/dev/null; then
        print_warning "Could not fetch from remote. Check network connection."
        print_status "Continuing with existing version..."
        cd "$SCRIPT_DIR"
        exit 0
    fi
    
    LOCAL_HEAD=$(git rev-parse HEAD 2>/dev/null)
    REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null)
    
    if [[ -z "$LOCAL_HEAD" || -z "$REMOTE_HEAD" ]]; then
        print_warning "Could not determine git state. Repository may be corrupted."
        cd "$SCRIPT_DIR"
        exit 1
    fi
    
    if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
        print_success "Already up to date!"
        cd "$SCRIPT_DIR"
        exit 0
    fi
    
    # Show what's new
    COMMITS_BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null || echo "?")
    print_status "Updates available: $COMMITS_BEHIND new commit(s)"
    echo
    echo -e "${DIM}Recent changes:${NC}"
    git log HEAD..origin/main --oneline 2>/dev/null | head -5
    echo
    
    # Pull updates
    print_status "Pulling updates..."
    if ! git pull origin main 2>/dev/null; then
        print_error "Failed to pull updates. You may have local changes."
        echo "Try: cd llama.cpp && git stash && git pull"
        cd "$SCRIPT_DIR"
        exit 1
    fi
    
    NEW_COMMIT=$(git rev-parse --short HEAD)
    print_success "Updated: $CURRENT_COMMIT -> $NEW_COMMIT"
    
    # Rebuild
    print_header "Rebuilding llama.cpp"
    
    # Detect GPU for build
    IFS='|' read -r _GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
    print_status "Building for: $GPU_NAME ($GPU_TARGET)"
    
    # Set up HIP environment
    HIPCXX="$(hipconfig -l)/clang"
    export HIPCXX
    HIP_PATH="$(hipconfig -R)"
    export HIP_PATH
    
    # Clean and rebuild
    print_status "Cleaning previous build..."
    rm -rf build
    
    print_status "Configuring CMake..."
    cmake -S . -B build \
        -DGGML_HIP=ON \
        -DGPU_TARGETS="$GPU_TARGET" \
        -DCMAKE_BUILD_TYPE=Release
    
    print_status "Building (this may take 10-20 minutes)..."
    start_spinner "Compiling llama.cpp"
    cmake --build build --config Release -- -j"$(nproc)" > /dev/null 2>&1
    stop_spinner true "Build complete"
    
    # Verify build
    if [[ -f "build/bin/llama-server" ]]; then
        print_success "llama-server rebuilt successfully"
    else
        print_error "Build failed - llama-server not found"
        cd "$SCRIPT_DIR"
        exit 1
    fi
    
    cd "$SCRIPT_DIR"
    
    echo
    print_success "Update complete!"
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Verify Mode
# -----------------------------------------------------------------------------

if [[ $RUN_VERIFY == true ]]; then
    print_header "Verifying Model Files"
    echo
    
    if [[ ! -d "$MODELS_DIR" ]]; then
        print_error "Models directory not found: $MODELS_DIR"
        exit 1
    fi
    
    VERIFY_COUNT=0
    VERIFY_PASS=0
    VERIFY_FAIL=0
    
    # Wrapper to use common verify function and track counts
    verify_model() {
        local model_path="$1"
        ((VERIFY_COUNT++))
        if verify_gguf_model "$model_path"; then
            ((VERIFY_PASS++))
        else
            ((VERIFY_FAIL++))
        fi
    }
    
    if [[ -n "$VERIFY_MODEL" ]]; then
        load_models_conf
        if [[ -n "${MODEL_INFO[$VERIFY_MODEL]:-}" ]]; then
            IFS='|' read -r _category _hf_repo gguf_file size _description <<< "${MODEL_INFO[$VERIFY_MODEL]}"
            verify_model "$MODELS_DIR/$gguf_file"
        elif [[ -f "$MODELS_DIR/$VERIFY_MODEL" ]]; then
            verify_model "$MODELS_DIR/$VERIFY_MODEL"
        elif [[ -f "$MODELS_DIR/${VERIFY_MODEL}.gguf" ]]; then
            verify_model "$MODELS_DIR/${VERIFY_MODEL}.gguf"
        else
            print_error "Model not found: $VERIFY_MODEL"
            exit 1
        fi
    else
        for gguf in "$MODELS_DIR"/*.gguf; do
            [[ -f "$gguf" ]] || continue
            verify_model "$gguf"
        done
    fi
    
    echo
    if [[ $VERIFY_COUNT -eq 0 ]]; then
        print_warning "No model files found in $MODELS_DIR"
    else
        echo -e "  ${BOLD}Results:${NC} $VERIFY_PASS passed, $VERIFY_FAIL failed, $VERIFY_COUNT total"
        if [[ $VERIFY_FAIL -gt 0 ]]; then
            echo
            print_warning "Some models failed verification"
            echo "Re-download failed models with: ./download-model.sh --force <model>"
            exit 1
        else
            print_success "All models verified!"
        fi
    fi
    
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------

print_banner "llama.cpp ROCm/HIP Setup"

# -----------------------------------------------------------------------------
# Load Configuration
# -----------------------------------------------------------------------------

# Detect GPU
IFS='|' read -r _GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
print_status "Detected GPU: $GPU_NAME ($GPU_TARGET)"

# -----------------------------------------------------------------------------
# Dependency Check
# -----------------------------------------------------------------------------

print_header "Checking Dependencies"

MISSING_REQUIRED=()
PERMISSION_WARNINGS=()

# Git
if command -v git &>/dev/null; then
    echo -e "  $CHECKMARK git                  installed"
else
    echo -e "  $CROSSMARK git                  not installed"
    MISSING_REQUIRED+=("git")
fi

# CMake
if command -v cmake &>/dev/null; then
    CMAKE_VERSION=$(cmake --version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
    echo -e "  $CHECKMARK cmake                installed ($CMAKE_VERSION)"
else
    echo -e "  $CROSSMARK cmake                not installed"
    MISSING_REQUIRED+=("cmake")
fi

# Make or Ninja
if command -v ninja &>/dev/null; then
    echo -e "  $CHECKMARK ninja                installed"
elif command -v make &>/dev/null; then
    echo -e "  $CHECKMARK make                 installed"
else
    echo -e "  $CROSSMARK make/ninja           not installed"
    MISSING_REQUIRED+=("make")
fi

# HIP/ROCm
if command -v hipconfig &>/dev/null; then
    HIP_VERSION=$(hipconfig --version 2>/dev/null || echo "unknown")
    echo -e "  $CHECKMARK hipconfig            installed ($HIP_VERSION)"
else
    echo -e "  $CROSSMARK hipconfig            not installed"
    MISSING_REQUIRED+=("rocm")
fi

# Check for HIP compiler
if command -v hipcc &>/dev/null; then
    echo -e "  $CHECKMARK hipcc                installed"
else
    echo -e "  $CROSSMARK hipcc                not installed"
    MISSING_REQUIRED+=("hipcc")
fi

# curl or huggingface-cli for downloads
if command -v huggingface-cli &>/dev/null; then
    echo -e "  $CHECKMARK huggingface-cli      installed (recommended)"
elif command -v curl &>/dev/null; then
    echo -e "  $CHECKMARK curl                 installed (fallback for downloads)"
else
    echo -e "  $CROSSMARK curl                 not installed"
    MISSING_REQUIRED+=("curl")
fi

# gum (required for interactive mode)
if [[ $NON_INTERACTIVE == false ]]; then
    if command -v gum &>/dev/null; then
        echo -e "  $CHECKMARK gum                  installed"
    else
        echo -e "  $CROSSMARK gum                  not installed (required for interactive mode)"
        MISSING_REQUIRED+=("gum")
    fi
fi

# AMD GPU device
if [[ -e /dev/kfd ]]; then
    echo -e "  $CHECKMARK AMD GPU (/dev/kfd)   detected"
else
    echo -e "  $CROSSMARK AMD GPU (/dev/kfd)   not found"
    MISSING_REQUIRED+=("amd-gpu")
fi

# User groups - these are warnings, not hard requirements
IN_VIDEO_GROUP=false
IN_RENDER_GROUP=false
if groups | grep -q '\bvideo\b'; then
    IN_VIDEO_GROUP=true
fi
if groups | grep -q '\brender\b'; then
    IN_RENDER_GROUP=true
fi

if [[ $IN_VIDEO_GROUP == true && $IN_RENDER_GROUP == true ]]; then
    echo -e "  $CHECKMARK User groups          video, render"
else
    MISSING_GROUPS=""
    [[ $IN_VIDEO_GROUP == false ]] && MISSING_GROUPS+="video "
    [[ $IN_RENDER_GROUP == false ]] && MISSING_GROUPS+="render"
    echo -e "  $WARNMARK User groups          missing: ${MISSING_GROUPS}(may cause GPU issues)"
    PERMISSION_WARNINGS+=("user-groups")
fi

# Check /dev/kfd permissions
if [[ -e /dev/kfd ]]; then
    if [[ -r /dev/kfd && -w /dev/kfd ]]; then
        echo -e "  $CHECKMARK /dev/kfd access      read/write OK"
    else
        echo -e "  $WARNMARK /dev/kfd access      no read/write permission"
        PERMISSION_WARNINGS+=("kfd-permissions")
    fi
fi

# Check /dev/dri permissions
if [[ -d /dev/dri ]]; then
    if [[ -r /dev/dri/renderD128 ]]; then
        echo -e "  $CHECKMARK /dev/dri access      OK"
    else
        echo -e "  $WARNMARK /dev/dri access      limited permissions"
        PERMISSION_WARNINGS+=("dri-permissions")
    fi
fi

echo

if [[ ${#MISSING_REQUIRED[@]} -gt 0 ]]; then
    print_header "Missing Required Dependencies"
    echo
    
    for dep in "${MISSING_REQUIRED[@]}"; do
        case $dep in
            git)
                echo -e "  ${BOLD}git:${NC}"
                echo "    Arch Linux:  sudo pacman -S git"
                echo "    Ubuntu:      sudo apt install git"
                echo
                ;;
            cmake)
                echo -e "  ${BOLD}cmake:${NC}"
                echo "    Arch Linux:  sudo pacman -S cmake"
                echo "    Ubuntu:      sudo apt install cmake"
                echo
                ;;
            make)
                echo -e "  ${BOLD}make (or ninja):${NC}"
                echo "    Arch Linux:  sudo pacman -S make ninja"
                echo "    Ubuntu:      sudo apt install build-essential ninja-build"
                echo
                ;;
            rocm|hipcc)
                echo -e "  ${BOLD}ROCm/HIP:${NC}"
                echo "    See: https://rocm.docs.amd.com/projects/install-on-linux/en/latest/"
                echo "    Arch Linux:  yay -S rocm-hip-sdk"
                echo "    Ubuntu:      Follow AMD ROCm installation guide"
                echo
                ;;
            curl)
                echo -e "  ${BOLD}curl:${NC}"
                echo "    Arch Linux:  sudo pacman -S curl"
                echo "    Ubuntu:      sudo apt install curl"
                echo
                ;;
            gum)
                echo -e "  ${BOLD}gum (interactive menus):${NC}"
                echo "    Arch Linux:  sudo pacman -S gum"
                echo "    Ubuntu:      See https://github.com/charmbracelet/gum#installation"
                echo "    Or run with: ./setup.sh --non-interactive"
                echo
                ;;
            amd-gpu)
                echo -e "  ${BOLD}AMD GPU (/dev/kfd):${NC}"
                echo "    No AMD GPU detected. This setup requires an AMD GPU with ROCm support."
                echo "    See: https://rocm.docs.amd.com/projects/install-on-linux/en/latest/"
                echo
                ;;
        esac
    done
    
    echo -e "${YELLOW}${BOLD}After installing dependencies, run this script again.${NC}"
    exit 1
fi

# Handle permission warnings
if [[ ${#PERMISSION_WARNINGS[@]} -gt 0 ]]; then
    print_header "Permission Warnings"
    echo
    
    for warn in "${PERMISSION_WARNINGS[@]}"; do
        case $warn in
            user-groups)
                echo -e "  ${BOLD}User not in video/render groups:${NC}"
                echo "    This may prevent GPU access for llama-server."
                echo
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video,render \$USER"
                echo "                 Then log out and back in"
                echo
                ;;
            kfd-permissions)
                echo -e "  ${BOLD}No read/write access to /dev/kfd:${NC}"
                echo "    GPU compute device not accessible."
                echo
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG render \$USER"
                echo "                 Then log out and back in"
                echo
                ;;
            dri-permissions)
                echo -e "  ${BOLD}Limited access to /dev/dri:${NC}"
                echo "    GPU render devices may not be accessible."
                echo
                echo "    Quick fix:   ./setup.sh --fix-permissions"
                echo "    Manual fix:  sudo usermod -aG video \$USER"
                echo "                 Then log out and back in"
                echo
                ;;
        esac
    done
    
    if [[ $IGNORE_WARNINGS == false && $NON_INTERACTIVE == false ]]; then
        echo -e "  ${DIM}The build may still succeed, but llama-server might not access the GPU.${NC}"
        echo
        
        continue_setup=""
        if [[ "$HAS_GUM" == true ]]; then
            if gum confirm "Continue with setup?"; then
                continue_setup="y"
            else
                continue_setup="n"
            fi
        else
            read -p "Continue with setup? (y/N) " -n 1 -r
            echo
            continue_setup="$REPLY"
        fi
        
        if [[ ! "$continue_setup" =~ ^[Yy]$ ]]; then
            echo
            print_status "To fix permissions, run: ./setup.sh --fix-permissions"
            print_status "Or continue anyway with: ./setup.sh --ignore-warnings"
            echo
            exit 1
        fi
    elif [[ $NON_INTERACTIVE == true ]]; then
        echo -e "  ${DIM}Non-interactive mode: continuing despite permission warnings.${NC}"
        echo -e "  ${DIM}Fix later with: ./setup.sh --fix-permissions${NC}"
        print_warning "GPU access may fail until permissions are fixed"
    else
        print_warning "Continuing despite permission warnings (--ignore-warnings)"
    fi
fi

print_success "All dependencies satisfied!"

# -----------------------------------------------------------------------------
# Ensure models-metadata.conf exists
# -----------------------------------------------------------------------------

ensure_metadata_conf "$SCRIPT_DIR" "$NON_INTERACTIVE"

# -----------------------------------------------------------------------------
# Clone/Update llama.cpp
# -----------------------------------------------------------------------------

print_header "Setting Up llama.cpp Repository"

clone_or_update_repo "https://github.com/ggerganov/llama.cpp" "$LLAMA_CPP_DIR" "$FORCE_REBUILD" || exit 1

# -----------------------------------------------------------------------------
# Build llama.cpp with HIP
# -----------------------------------------------------------------------------

if [[ "$SKIP_BUILD" == false ]]; then
    print_header "Building llama.cpp with HIP/ROCm"
    
    cd "$LLAMA_CPP_DIR"
    
    # Check if already built
    if [[ -f "build/bin/llama-server" && "$FORCE_REBUILD" != true ]]; then
        print_status "llama-server already built (use --force-rebuild to rebuild)"
    else
        print_status "Configuring CMake with HIP for $GPU_TARGET..."
        
        # Set up HIP environment
        HIPCXX="$(hipconfig -l)/clang"
        export HIPCXX
        HIP_PATH="$(hipconfig -R)"
        export HIP_PATH
        
        # Configure with CMake
        cmake -S . -B build \
            -DGGML_HIP=ON \
            -DGPU_TARGETS="$GPU_TARGET" \
            -DCMAKE_BUILD_TYPE=Release
        
        print_status "Building (this may take 10-20 minutes)..."
        start_spinner "Compiling llama.cpp"
        cmake --build build --config Release -- -j"$(nproc)" > /dev/null 2>&1
        stop_spinner true "Build complete"
    fi
    
    # Verify build
    if [[ -f "build/bin/llama-server" ]]; then
        print_success "llama-server built successfully"
    else
        print_error "Build failed - llama-server not found"
        exit 1
    fi
    
    cd "$SCRIPT_DIR"
else
    print_status "Skipping build (--skip-build)"
fi

# -----------------------------------------------------------------------------
# Model Selection & Download
# -----------------------------------------------------------------------------

if [[ "$SKIP_MODELS" == false ]]; then
    print_header "Model Selection"
    
    load_models_conf
    
    if [[ "$NON_INTERACTIVE" == false ]]; then
        gum_model_selection
    else
        print_status "Using default model selection (--non-interactive)"
    fi
    
    read -ra SELECTED_MODELS <<< "$(get_selected_models)"
    
    if [[ ${#SELECTED_MODELS[@]} -eq 0 ]]; then
        print_warning "No models selected"
    else
        print_header "Downloading Models"
        
        for model in "${SELECTED_MODELS[@]}"; do
            download_model "$model"
        done
    fi
else
    print_status "Skipping model selection (--skip-models)"
fi

# -----------------------------------------------------------------------------
# Generate OpenCode Config
# -----------------------------------------------------------------------------

print_header "OpenCode Configuration"

# Get list of downloaded models
DOWNLOADED_MODELS=()
load_models_conf
for model in "${MODEL_ORDER[@]}"; do
    IFS='|' read -r _category _hf_repo gguf_file size _description <<< "${MODEL_INFO[$model]}"
    if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
        DOWNLOADED_MODELS+=("$model")
    fi
done

if [[ ${#DOWNLOADED_MODELS[@]} -gt 0 ]]; then
    # Callback function for config generation
    _generate_config() { generate_opencode_config "${DOWNLOADED_MODELS[@]}"; }
    handle_opencode_config "$OPENCODE_CONFIG" "$SCRIPT_DIR/sync-opencode.sh" "$NON_INTERACTIVE" _generate_config
else
    print_warning "No models downloaded, skipping OpenCode config"
fi

# Sync agent files (AGENTS.md, plan.md, review.md, debug.md)
OPENCODE_CONFIG_DIR="$(dirname "$OPENCODE_CONFIG")"
sync_agents "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "$NON_INTERACTIVE" "false"

# -----------------------------------------------------------------------------
# Orphan Model Cleanup
# -----------------------------------------------------------------------------

if [[ -d "$MODELS_DIR" ]]; then
    check_orphan_models "$SCRIPT_DIR" "$NON_INTERACTIVE"
fi

# -----------------------------------------------------------------------------
# Create local .env
# -----------------------------------------------------------------------------

print_header "Creating Local Configuration"

# Get appropriate HSA version for detected GPU
DETECTED_HSA_VERSION=$(get_hsa_version "$GPU_TARGET")

if [[ -f "$LOCAL_ENV" && "$FORCE_ENV" != "true" ]]; then
    print_status ".env already exists, keeping current configuration"
    print_status "Use --force-env to regenerate"
else
    if [[ -f "$LOCAL_ENV" ]]; then
        print_status "Regenerating .env (--force-env)"
    fi
    
    cat > "$LOCAL_ENV" << EOF
# llama.cpp Configuration
# Generated by setup.sh on $(date)

# GPU Target (detected: $GPU_NAME)
GPU_TARGET=$GPU_TARGET

# Server settings
LLAMA_PORT=$DEFAULT_PORT
LLAMA_CONTEXT=$DEFAULT_CONTEXT

# Paths
LLAMA_CPP_DIR=$LLAMA_CPP_DIR
MODELS_DIR=$MODELS_DIR

# GPU settings (auto-detected based on GPU architecture)
HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION:-$DETECTED_HSA_VERSION}
EOF

    print_success "Created .env"
fi

# -----------------------------------------------------------------------------
# Setup Complete
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo
echo -e "${BOLD}Configuration:${NC}"
echo "  GPU:              $GPU_NAME ($GPU_TARGET)"
echo "  llama.cpp:        $LLAMA_CPP_DIR"
echo "  Models:           $MODELS_DIR"
echo "  Server port:      $DEFAULT_PORT"
echo
echo -e "${BOLD}Quick commands:${NC}"
echo "  Start server:     ./start-server.sh <model-id>"
echo "  Download model:   ./download-model.sh <model-id>"
echo "  Check status:     ./setup.sh --status"
echo
echo -e "${BOLD}Available models:${NC}"
for model in "${MODEL_ORDER[@]}"; do
    IFS='|' read -r _category _hf_repo gguf_file size _description <<< "${MODEL_INFO[$model]}"
    if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
        echo -e "  $CHECKMARK $model ($size)"
    else
        echo -e "  $CROSSMARK $model ($size) - not downloaded"
    fi
done

# Pick best model for example and smallest for test
EXAMPLE_MODEL=$(pick_example_model)
TEST_MODEL=$(pick_test_model)
[[ -z "$TEST_MODEL" ]] && TEST_MODEL="$EXAMPLE_MODEL"

# Run inference test if we have a model
if [[ -n "$TEST_MODEL" ]]; then
    IFS='|' read -r _ _ test_gguf_file test_size _ <<< "${MODEL_INFO[$TEST_MODEL]}"
    test_size_mb=$(parse_size_mb "$test_size")
    
    # Get HSA environment for ROCm
    DETECTED_HSA_VERSION=$(get_hsa_version "$GPU_TARGET")
    HSA_ENV="HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION:-$DETECTED_HSA_VERSION}"
    
    if [[ "$NON_INTERACTIVE" == false ]]; then
        echo
        
        # Build list of downloaded models for "other" option
        declare -a test_models=()
        declare -a test_model_labels=()
        for model in "${MODEL_ORDER[@]}"; do
            IFS='|' read -r _category _hf_repo gguf_file size _description <<< "${MODEL_INFO[$model]}"
            if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
                test_models+=("$model")
                test_model_labels+=("$model ($size)")
            fi
        done
        
        test_choice=""
        selected_model=""
        
        if [[ "$HAS_GUM" == true ]]; then
            echo -e "${BOLD}Run inference test?${NC}"
            echo
            gum_exit=0
            test_choice=$(gum choose --cursor-prefix="$GUM_RADIO_CURSOR" --selected-prefix="$GUM_RADIO_SELECTED" \
                --cursor.foreground="212" \
                "Yes - test with $TEST_MODEL (smallest)" \
                "Choose different model" \
                "Skip test") && gum_exit=0 || gum_exit=$?
            check_user_interrupt $gum_exit
            [[ -z "$test_choice" ]] && test_choice="Skip test"
        else
            read -p "Run inference test with $TEST_MODEL (smallest)? [Y/n/other] " -r
            if [[ "$REPLY" =~ ^[Nn]$ ]]; then
                test_choice="Skip test"
            elif [[ "$REPLY" =~ ^[Oo]$ ]] || [[ "$REPLY" == "other" ]]; then
                test_choice="Choose different model"
            else
                test_choice="Yes"
            fi
        fi
        
        case "$test_choice" in
            "Skip test")
                print_status "Skipping inference test"
                ;;
            "Choose different model")
                echo
                
                if [[ "$HAS_GUM" == true ]]; then
                    echo -e "${BOLD}Select model for inference test:${NC}"
                    echo
                    gum_exit2=0
                    selected_label=$(gum choose --cursor-prefix="$GUM_RADIO_CURSOR" --selected-prefix="$GUM_RADIO_SELECTED" \
                        --cursor.foreground="212" \
                        "${test_model_labels[@]}" \
                        "Skip test") && gum_exit2=0 || gum_exit2=$?
                    check_user_interrupt $gum_exit2
                    
                    if [[ "$selected_label" == "Skip test" ]] || [[ -z "$selected_label" ]]; then
                        print_status "Skipping inference test"
                    else
                        for i in "${!test_model_labels[@]}"; do
                            if [[ "${test_model_labels[$i]}" == "$selected_label" ]]; then
                                selected_model="${test_models[$i]}"
                                break
                            fi
                        done
                    fi
                else
                    echo -e "${BOLD}Select model for inference test:${NC}"
                    echo
                    idx=1
                    for label in "${test_model_labels[@]}"; do
                        echo "  $idx) $label"
                        ((idx++))
                    done
                    echo "  0) Skip test"
                    echo
                    read -p "Select [0-$((idx-1))]: " choice
                    
                    if [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -gt 0 ]] && [[ "$choice" -lt $idx ]]; then
                        selected_model="${test_models[$((choice-1))]}"
                    elif [[ "$choice" != "0" ]]; then
                        print_warning "Invalid selection, skipping test"
                    fi
                fi
                
                if [[ -n "$selected_model" ]]; then
                    IFS='|' read -r _ _ sel_gguf_file sel_size _ <<< "${MODEL_INFO[$selected_model]}"
                    sel_size_mb=$(parse_size_mb "$sel_size")
                    run_inference_test "$selected_model" "$sel_gguf_file" "$sel_size_mb" "$HSA_ENV" || true
                fi
                ;;
            *)
                run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" "$HSA_ENV" || true
                ;;
        esac
    else
        run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" "$HSA_ENV" || true
    fi
fi

echo
echo -e "${BOLD}Using with OpenCode:${NC}"
echo "  1. Start server:  ./start-server.sh ${EXAMPLE_MODEL:-<model-id>}"
echo "  2. Run opencode in any project"
echo "  3. Use '/models' to select llama.cpp provider"

if ! command -v opencode &>/dev/null; then
    echo
    print_warning "OpenCode is not installed"
    echo "  Install with: npm install -g opencode"
    echo "  More info:    https://opencode.ai"
fi

# Check for llama.cpp updates (once per day, cached)
if [[ "$SKIP_UPDATE_CHECK" != true ]]; then
    update_msg=$(check_llama_cpp_updates "$LLAMA_CPP_DIR" 2>/dev/null)
    if [[ -n "$update_msg" ]]; then
        show_update_notification "llama.cpp" "$update_msg" "./setup.sh --update"
    fi
fi

echo
echo -e "${GREEN}${BOLD}Happy coding!${NC}"
echo
