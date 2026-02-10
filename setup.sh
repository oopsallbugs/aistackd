#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp GPU Setup Script
# Linux setup with automatic GPU detection (AMD ROCm/HIP or NVIDIA CUDA)
# =============================================================================

# -----------------------------------------------------------------------------
# Early --help Check (before OS validation)
# -----------------------------------------------------------------------------

for arg in "$@"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
        echo "Usage: ./setup.sh [OPTIONS]"
        echo
        echo "Linux setup for llama.cpp with GPU acceleration."
        echo "Automatically detects AMD (ROCm/HIP) or NVIDIA (CUDA) GPUs."
        echo "For macOS, use ./setup-macos.sh instead."
        echo
        echo "Commands:"
        echo "  --status            Show current llama.cpp status"
        echo "  --update            Update llama.cpp to latest version and rebuild"
        echo "  --fix-permissions   Fix GPU access permissions (AMD only)"
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
        echo "  .env                Local configuration"
        echo "  .env.example        Server configuration example"
        echo
        echo "Examples:"
        echo "  ./setup.sh                      # Interactive setup"
        echo "  ./setup.sh --status             # Check current status"
        echo "  ./setup.sh --update             # Update llama.cpp"
        echo "  ./setup.sh --fix-permissions    # Fix GPU permissions (AMD)"
        echo "  ./setup.sh --verify             # Verify all downloaded models"
        echo "  ./setup.sh --non-interactive    # Automated setup with defaults"
        exit 0
    fi
done

# -----------------------------------------------------------------------------
# OS Check - This script is Linux-only
# -----------------------------------------------------------------------------

if [[ "$(uname -s)" != "Linux" ]]; then
    echo
    echo "ERROR: This setup script is for Linux only."
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
# Error Handling (GPU-vendor-aware messages)
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
    
    local vendor
    vendor=$(detect_gpu_vendor)
    
    echo "Common solutions:"
    if [[ "$vendor" == "nvidia" ]]; then
        echo "  1. Make sure CUDA toolkit is installed:"
        echo "     nvcc --version"
        echo
        echo "  2. Verify NVIDIA driver is working:"
        echo "     nvidia-smi"
        echo
    elif [[ "$vendor" == "amd" ]]; then
        echo "  1. Make sure ROCm is installed:"
        echo "     rocminfo"
        echo
        echo "  2. Check HIP is available:"
        echo "     hipconfig --version"
        echo
    else
        echo "  1. No GPU detected - building CPU-only version"
        echo
    fi
    echo "  3. Ensure you have build tools:"
    echo "     cmake --version && make --version"
    echo
    echo -e "${DIM}(Technical: error on line $line_number, exit code $exit_code)${NC}"
    exit "$exit_code"
}

trap 'handle_error $? $LINENO' ERR

# -----------------------------------------------------------------------------
# GPU Detection (AMD-specific helpers)
# -----------------------------------------------------------------------------

# Get HSA override version based on GPU architecture (AMD only)
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
# VRAM Detection (vendor-aware)
# -----------------------------------------------------------------------------

DETECTED_VRAM_GB=""

get_vram_gb() {
    if [[ -n "$DETECTED_VRAM_GB" ]]; then
        echo "$DETECTED_VRAM_GB"
        return
    fi
    
    local vendor
    vendor=$(detect_gpu_vendor)
    
    if [[ "$vendor" == "nvidia" ]]; then
        DETECTED_VRAM_GB=$(get_nvidia_vram_gb)
        echo "$DETECTED_VRAM_GB"
        return
    fi
    
    # AMD detection via rocm-smi
    local vram_mb=""
    
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
SKIP_UPDATE_CHECK=false
SYNC_AGENTS=false
SYNC_TOOLS=false
SYNC_MODELS=false 


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
        --no-update-check) SKIP_UPDATE_CHECK=true ;;
        --sync-agents) 
            OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
            sync_agents "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "false" "true"
            exit 0
            ;;
        --sync-tools)
            OPENCODE_TOOLS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/tools"
            sync_tools "$SCRIPT_DIR" "$OPENCODE_TOOLS_DIR" "false" "true"
            exit 0
            ;;
        --sync-models)
            OPENCODE_MODELS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/models"
            sync_models "$SCRIPT_DIR" "$OPENCODE_MODELS_DIR" "false" "true"
            exit 0
            ;;
        # --help is handled early (before OS check)
    esac
done

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
    if curl -sf "http://$LLAMA_HOST:$LLAMA_PORT/health" &>/dev/null; then
        echo -e "    $CHECKMARK Status: ${GREEN}running${NC}"
        echo -e "    $CHECKMARK Endpoint: http://$LLAMA_HOST:$LLAMA_PORT"
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
            ((model_count++)) || true
        done
        if [[ $model_count -eq 0 ]]; then
            echo -e "    ${DIM}No models downloaded${NC}"
        fi
    else
        echo -e "    ${DIM}Models directory not found${NC}"
    fi
    
    # GPU (vendor-aware)
    echo
    echo -e "  ${BOLD}GPU:${NC}"
    GPU_VENDOR=$(detect_gpu_vendor)
    GPU_VENDOR_DISPLAY=$(get_gpu_vendor_display_name "$GPU_VENDOR")
    
    if [[ "$GPU_VENDOR" == "nvidia" ]]; then
        IFS='|' read -r GPU_NAME vram_gb <<< "$(detect_nvidia_gpu)"
        echo -e "    $CHECKMARK Vendor: ${GREEN}$GPU_VENDOR_DISPLAY${NC}"
        echo -e "    $CHECKMARK GPU: ${GREEN}$GPU_NAME${NC}"
        if [[ "$vram_gb" -gt 0 ]]; then
            echo -e "    $CHECKMARK VRAM: ${GREEN}${vram_gb}GB${NC}"
        fi
    elif [[ "$GPU_VENDOR" == "amd" ]]; then
        IFS='|' read -r _GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
        echo -e "    $CHECKMARK Vendor: ${GREEN}$GPU_VENDOR_DISPLAY${NC}"
        echo -e "    $CHECKMARK GPU: ${GREEN}$GPU_NAME${NC}"
        echo -e "    $CHECKMARK Target: $GPU_TARGET"
        vram_gb=$(get_vram_gb)
        if [[ "$vram_gb" -gt 0 ]]; then
            echo -e "    $CHECKMARK VRAM: ${GREEN}${vram_gb}GB${NC}"
        fi
    else
        echo -e "    $WARNMARK No GPU detected (CPU-only mode)"
    fi
    
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Fix Permissions Mode (AMD ROCm only)
# -----------------------------------------------------------------------------

if [[ $FIX_PERMISSIONS == true ]]; then
    GPU_VENDOR=$(detect_gpu_vendor)
    
    if [[ "$GPU_VENDOR" == "nvidia" ]]; then
        print_header "GPU Permissions Check"
        echo
        print_status "NVIDIA GPUs typically don't require special permission fixes."
        echo
        echo "If you're having issues, check:"
        echo "  1. NVIDIA driver is installed: nvidia-smi"
        echo "  2. CUDA toolkit is installed: nvcc --version"
        echo "  3. User is in 'video' group (some distros): groups \$USER"
        echo
        exit 0
    elif [[ "$GPU_VENDOR" == "cpu" ]]; then
        print_header "GPU Permissions Check"
        echo
        print_warning "No GPU detected. Nothing to fix."
        echo
        exit 0
    fi
    
    # AMD ROCm permission fixes
    print_header "Fixing AMD GPU Access Permissions"
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
    if ! git fetch origin master --quiet 2>/dev/null; then
        print_warning "Could not fetch from remote. Check network connection."
        print_status "Continuing with existing version..."
        cd "$SCRIPT_DIR"
        exit 0
    fi
    
    LOCAL_HEAD=$(git rev-parse HEAD 2>/dev/null)
    REMOTE_HEAD=$(git rev-parse origin/master 2>/dev/null)
    
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
    COMMITS_BEHIND=$(git rev-list HEAD..origin/master --count 2>/dev/null || echo "?")
    print_status "Updates available: $COMMITS_BEHIND new commit(s)"
    echo
    echo -e "${DIM}Recent changes:${NC}"
    git log HEAD..origin/master --oneline 2>/dev/null | head -5
    echo
    
    # Pull updates
    print_status "Pulling updates..."
    if ! git pull origin master 2>/dev/null; then
        print_error "Failed to pull updates. You may have local changes."
        echo "Try: cd llama.cpp && git stash && git pull"
        cd "$SCRIPT_DIR"
        exit 1
    fi
    
    NEW_COMMIT=$(git rev-parse --short HEAD)
    print_success "Updated: $CURRENT_COMMIT -> $NEW_COMMIT"
    
    # Rebuild
    print_header "Rebuilding llama.cpp"
    
    # Detect GPU vendor and get appropriate build flags
    GPU_VENDOR=$(detect_gpu_vendor)
    GPU_VENDOR_DISPLAY=$(get_gpu_vendor_display_name "$GPU_VENDOR")
    
    if [[ "$GPU_VENDOR" == "nvidia" ]]; then
        IFS='|' read -r GPU_NAME _vram <<< "$(detect_nvidia_gpu)"
        print_status "Building for: $GPU_NAME (CUDA)"
        CMAKE_GPU_FLAGS=$(get_cmake_gpu_flags "$GPU_VENDOR")
    elif [[ "$GPU_VENDOR" == "amd" ]]; then
        IFS='|' read -r _GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
        print_status "Building for: $GPU_NAME ($GPU_TARGET)"
        CMAKE_GPU_FLAGS=$(get_cmake_gpu_flags "$GPU_VENDOR" "$GPU_TARGET")
        
        # Set up HIP environment for AMD
        HIPCXX="$(hipconfig -l)/clang"
        export HIPCXX
        HIP_PATH="$(hipconfig -R)"
        export HIP_PATH
    else
        print_status "Building CPU-only version"
        CMAKE_GPU_FLAGS=""
    fi
    
    # Clean and rebuild
    print_status "Cleaning previous build..."
    rm -rf build
    
    print_status "Configuring CMake..."
    # shellcheck disable=SC2086  # Word splitting is intentional for cmake flags
    cmake -S . -B build \
        $CMAKE_GPU_FLAGS \
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
# Banner and Initial GPU Detection
# -----------------------------------------------------------------------------

# Detect GPU vendor first
GPU_VENDOR=$(detect_gpu_vendor)
GPU_VENDOR_DISPLAY=$(get_gpu_vendor_display_name "$GPU_VENDOR")

# Show appropriate banner based on GPU vendor
if [[ "$GPU_VENDOR" == "nvidia" ]]; then
    print_banner "llama.cpp CUDA Setup"
elif [[ "$GPU_VENDOR" == "amd" ]]; then
    print_banner "llama.cpp ROCm/HIP Setup"
else
    print_banner "llama.cpp CPU Setup"
fi

# -----------------------------------------------------------------------------
# Load Configuration
# -----------------------------------------------------------------------------

# Detect and display GPU info based on vendor
if [[ "$GPU_VENDOR" == "nvidia" ]]; then
    IFS='|' read -r GPU_NAME GPU_VRAM_GB <<< "$(detect_nvidia_gpu)"
    print_status "Detected GPU: $GPU_NAME (${GPU_VRAM_GB}GB VRAM)"
elif [[ "$GPU_VENDOR" == "amd" ]]; then
    IFS='|' read -r _GPU_CHIP GPU_NAME GPU_TARGET <<< "$(detect_amd_gpu)"
    print_status "Detected GPU: $GPU_NAME ($GPU_TARGET)"
else
    print_warning "No GPU detected - will build CPU-only version"
fi

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

# GPU-specific dependencies
if [[ "$GPU_VENDOR" == "nvidia" ]]; then
    # NVIDIA: Check for CUDA toolkit
    NVCC_PATH=$(detect_nvcc || echo "")
    if [[ -n "$NVCC_PATH" ]]; then
        CUDA_VERSION=$("$NVCC_PATH" --version 2>/dev/null | grep "release" | grep -oE '[0-9]+\.[0-9]+' | head -1)
        echo -e "  $CHECKMARK nvcc                 installed ($CUDA_VERSION)"
    else
        echo -e "  $CROSSMARK nvcc                 not installed"
        MISSING_REQUIRED+=("cuda")
    fi
    
    # Check nvidia-smi (driver)
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
        echo -e "  $CHECKMARK nvidia-smi           driver $DRIVER_VERSION"
    else
        echo -e "  $CROSSMARK nvidia-smi           driver not working"
        MISSING_REQUIRED+=("nvidia-driver")
    fi
    
elif [[ "$GPU_VENDOR" == "amd" ]]; then
    # AMD: Check HIP/ROCm
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
    
    # AMD GPU device
    if [[ -e /dev/kfd ]]; then
        echo -e "  $CHECKMARK AMD GPU (/dev/kfd)   detected"
    else
        echo -e "  $CROSSMARK AMD GPU (/dev/kfd)   not found"
        MISSING_REQUIRED+=("amd-gpu")
    fi
else
    # CPU-only: Just note it
    echo -e "  $WARNMARK GPU                   none detected (CPU-only build)"
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

# AMD-specific permission checks
if [[ "$GPU_VENDOR" == "amd" ]]; then
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
            cuda)
                echo -e "  ${BOLD}CUDA Toolkit:${NC}"
                echo "    See: https://developer.nvidia.com/cuda-downloads"
                echo "    Arch Linux:  sudo pacman -S cuda"
                echo "    Ubuntu:      sudo apt install nvidia-cuda-toolkit"
                echo
                ;;
            nvidia-driver)
                echo -e "  ${BOLD}NVIDIA Driver:${NC}"
                echo "    Arch Linux:  sudo pacman -S nvidia"
                echo "    Ubuntu:      sudo apt install nvidia-driver-XXX"
                echo "    Or use:      ubuntu-drivers autoinstall"
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
# Clone/Update llama.cpp
# -----------------------------------------------------------------------------

print_header "Setting Up llama.cpp Repository"

clone_or_update_repo "https://github.com/ggerganov/llama.cpp" "$LLAMA_CPP_DIR" "$FORCE_REBUILD" || exit 1

# Clear update check cache since we just updated
rm -f "${XDG_CACHE_HOME:-$HOME/.cache}/llama-cpp-setup/update-check" 2>/dev/null || true

# -----------------------------------------------------------------------------
# Build llama.cpp (vendor-aware)
# -----------------------------------------------------------------------------

if [[ "$SKIP_BUILD" == false ]]; then
    if [[ "$GPU_VENDOR" == "nvidia" ]]; then
        print_header "Building llama.cpp with CUDA"
    elif [[ "$GPU_VENDOR" == "amd" ]]; then
        print_header "Building llama.cpp with HIP/ROCm"
    else
        print_header "Building llama.cpp (CPU-only)"
    fi
    
    cd "$LLAMA_CPP_DIR"
    
    # Check if already built
    if [[ -f "build/bin/llama-server" && "$FORCE_REBUILD" != true ]]; then
        print_status "llama-server already built (use --force-rebuild to rebuild)"
    else
        # Get CMake GPU flags based on vendor
        if [[ "$GPU_VENDOR" == "nvidia" ]]; then
            CMAKE_GPU_FLAGS=$(get_cmake_gpu_flags "$GPU_VENDOR")
            print_status "Configuring CMake with CUDA..."
        elif [[ "$GPU_VENDOR" == "amd" ]]; then
            CMAKE_GPU_FLAGS=$(get_cmake_gpu_flags "$GPU_VENDOR" "$GPU_TARGET")
            print_status "Configuring CMake with HIP for $GPU_TARGET..."
            
            # Set up HIP environment for AMD
            HIPCXX="$(hipconfig -l)/clang"
            export HIPCXX
            HIP_PATH="$(hipconfig -R)"
            export HIP_PATH
        else
            CMAKE_GPU_FLAGS=""
            print_status "Configuring CMake for CPU-only build..."
        fi
        
        # Configure with CMake
        # shellcheck disable=SC2086  # Word splitting is intentional for cmake flags
        cmake -S . -B build \
            $CMAKE_GPU_FLAGS \
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
# Create local .env (vendor-aware)
# -----------------------------------------------------------------------------

print_header "Creating Local Configuration"

if [[ -f "$LOCAL_ENV" && "$FORCE_ENV" != "true" ]]; then
    print_status ".env already exists, keeping current configuration"
    print_status "Use --force-env to regenerate"
else
    if [[ -f "$LOCAL_ENV" ]]; then
        print_status "Regenerating .env (--force-env)"
    fi
    
    # Generate vendor-specific .env content
    if [[ "$GPU_VENDOR" == "nvidia" ]]; then
        cat > "$LOCAL_ENV" << EOF
# llama.cpp Configuration
# Generated by setup.sh on $(date)

# GPU Configuration (detected: $GPU_NAME)
GPU_VENDOR=nvidia
GPU_LAYERS=99

# Server settings
LLAMA_PORT=$LLAMA_PORT
LLAMA_HOST=$LLAMA_HOST  # Use 127.0.0.1 to restrict to local-only (breaks Docker/OpenHands)

# Paths
LLAMA_CPP_DIR=$LLAMA_CPP_DIR
MODELS_DIR=$MODELS_DIR
EOF
    elif [[ "$GPU_VENDOR" == "amd" ]]; then
        # Get appropriate HSA version for detected GPU
        DETECTED_HSA_VERSION=$(get_hsa_version "$GPU_TARGET")
        
        cat > "$LOCAL_ENV" << EOF
# llama.cpp Configuration
# Generated by setup.sh on $(date)

# GPU Configuration (detected: $GPU_NAME)
GPU_VENDOR=amd
GPU_TARGET=$GPU_TARGET
HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION:-$DETECTED_HSA_VERSION}
GPU_LAYERS=99

# Server settings
LLAMA_PORT=$LLAMA_PORT
LLAMA_HOST=$LLAMA_HOST  # Use 127.0.0.1 to restrict to local-only (breaks Docker/OpenHands)

# Paths
LLAMA_CPP_DIR=$LLAMA_CPP_DIR
MODELS_DIR=$MODELS_DIR
EOF
    else
        cat > "$LOCAL_ENV" << EOF
# llama.cpp Configuration
# Generated by setup.sh on $(date)

# GPU Configuration (CPU-only mode)
GPU_VENDOR=cpu
GPU_LAYERS=0

# Server settings
LLAMA_PORT=$LLAMA_PORT
LLAMA_HOST=$LLAMA_HOST  # Use 127.0.0.1 to restrict to local-only (breaks Docker/OpenHands)

# Paths
LLAMA_CPP_DIR=$LLAMA_CPP_DIR
MODELS_DIR=$MODELS_DIR
EOF
    fi

    print_success "Created .env"
fi

# -----------------------------------------------------------------------------
# Orphan Model Cleanup
# -----------------------------------------------------------------------------

if [[ -d "$MODELS_DIR" ]]; then
    check_orphan_models "$SCRIPT_DIR" "$NON_INTERACTIVE"
fi

# -----------------------------------------------------------------------------
# Setup Complete
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo
echo -e "${BOLD}Configuration:${NC}"
if [[ "$GPU_VENDOR" == "nvidia" ]]; then
    echo "  GPU:              $GPU_NAME (CUDA)"
elif [[ "$GPU_VENDOR" == "amd" ]]; then
    echo "  GPU:              $GPU_NAME ($GPU_TARGET)"
else
    echo "  GPU:              CPU-only"
fi
echo "  llama.cpp:        $LLAMA_CPP_DIR"
echo "  Models:           $MODELS_DIR"
echo "  Server host:      $LLAMA_HOST"
echo "  Server port:      $LLAMA_PORT"
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
    
    # Get environment variables for GPU vendor
    if [[ "$GPU_VENDOR" == "amd" ]]; then
        DETECTED_HSA_VERSION=$(get_hsa_version "$GPU_TARGET")
        GPU_ENV="HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION:-$DETECTED_HSA_VERSION}"
    else
        GPU_ENV=""
    fi
    
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
                    run_inference_test "$selected_model" "$sel_gguf_file" "$sel_size_mb" "$GPU_ENV" || true
                fi
                ;;
            *)
                run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" "$GPU_ENV" || true
                ;;
        esac
    else
        run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" "$GPU_ENV" || true
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

exit 0