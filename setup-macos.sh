#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp Metal Setup Script
# macOS setup for Apple Silicon with automatic system detection
# =============================================================================

# -----------------------------------------------------------------------------
# OS Check - This script is macOS-only (Metal)
# -----------------------------------------------------------------------------

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo
    echo "ERROR: This setup script is for macOS only."
    echo
    echo "Metal (Apple's GPU framework) is macOS/iOS-only."
    echo
    if [[ "$(uname -s)" == "Linux" ]]; then
        echo "For Linux with AMD GPUs, use setup.sh instead (ROCm/HIP backend)."
        echo
        echo "  ./setup.sh"
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
# Error Handling (macOS-specific messages)
# -----------------------------------------------------------------------------

handle_error() {
    local exit_code=$1
    local line_number=$2
    
    if [[ "$USER_INTERRUPTED" == true ]] || [[ $exit_code -eq 130 ]]; then
        exit "$exit_code"
    fi
    
    echo
    print_error "Something went wrong during setup."
    echo
    echo "Common solutions:"
    echo "  1. Make sure Xcode Command Line Tools are installed:"
    echo "     xcode-select --install"
    echo
    echo "  2. Ensure you have cmake:"
    echo "     brew install cmake"
    echo
    echo "  3. Check your macOS version (requires 11.0+):"
    echo "     sw_vers"
    echo
    echo -e "${DIM}(Technical: error on line $line_number, exit code $exit_code)${NC}"
    exit "$exit_code"
}

trap 'handle_error $? $LINENO' ERR

# -----------------------------------------------------------------------------
# Apple Silicon Detection
# -----------------------------------------------------------------------------

detect_apple_chip() {
    local chip_info
    chip_info=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown")
    
    if [[ "$chip_info" =~ "Apple M" ]]; then
        # Extract M1, M2, M3, M4, etc.
        local chip_name
        chip_name=$(echo "$chip_info" | grep -oE 'Apple M[0-9]+( Pro| Max| Ultra)?' || echo "Apple Silicon")
        echo "$chip_name"
    elif [[ "$(uname -m)" == "arm64" ]]; then
        echo "Apple Silicon"
    else
        echo "Intel"
    fi
}

# Detect unified memory (RAM) - on Apple Silicon this is shared with GPU
get_memory_gb() {
    local mem_bytes
    mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    echo $((mem_bytes / 1024 / 1024 / 1024))
}

# Check if running on Apple Silicon
is_apple_silicon() {
    [[ "$(uname -m)" == "arm64" ]]
}

# -----------------------------------------------------------------------------
# Command Line Arguments
# -----------------------------------------------------------------------------

SKIP_BUILD=false
SKIP_MODELS=false
FORCE_REBUILD=false
FORCE_ENV=false
NON_INTERACTIVE=false
IGNORE_WARNINGS=false
RUN_STATUS=false
RUN_UPDATE=false
RUN_VERIFY=false
VERIFY_MODEL=""
RESET_AGENTS=false

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
        --verify) RUN_VERIFY=true ;;
        --verify=*) RUN_VERIFY=true; VERIFY_MODEL="${arg#*=}" ;;
        --reset-agents) RESET_AGENTS=true ;;
        --help|-h)
            echo "Usage: ./setup-macos.sh [OPTIONS]"
            echo
            echo "Commands:"
            echo "  --status            Show current llama.cpp status"
            echo "  --update            Update llama.cpp to latest version and rebuild"
            echo "  --verify[=model]    Verify model file integrity (all or specific)"
            echo "  --reset-agents      Reset AGENTS.md to default template"
            echo
            echo "Setup Options:"
            echo "  --skip-build        Skip building llama.cpp (use existing build)"
            echo "  --skip-models       Skip model selection and downloading"
            echo "  --force-rebuild     Force rebuild even if build exists"
            echo "  --force-env         Regenerate .env file even if it exists"
            echo "  --non-interactive   Use default selections (no prompts)"
            echo "  --ignore-warnings   Continue setup despite warnings"
            echo "  --help, -h          Show this help message"
            echo
            echo "Files:"
            echo "  models.conf         Edit to customize available GGUF models"
            echo "  models-metadata.conf  Display names and context limits for OpenCode"
            echo "  .env                Local configuration"
            echo
            echo "Examples:"
            echo "  ./setup-macos.sh                  # Interactive setup"
            echo "  ./setup-macos.sh --status         # Check current status"
            echo "  ./setup-macos.sh --update         # Update llama.cpp"
            echo "  ./setup-macos.sh --non-interactive  # Automated setup"
            exit 0
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Reset Agents Mode
# -----------------------------------------------------------------------------

if [[ $RESET_AGENTS == true ]]; then
    OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
    handle_agents_md "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "false" "true"
    exit 0
fi

# -----------------------------------------------------------------------------
# Status Mode
# -----------------------------------------------------------------------------

if [[ $RUN_STATUS == true ]]; then
    print_header "llama.cpp Status"
    echo
    
    # Hardware
    echo -e "  ${BOLD}Hardware:${NC}"
    CHIP_NAME=$(detect_apple_chip)
    MEMORY_GB=$(get_memory_gb)
    echo -e "    $CHECKMARK Chip: ${GREEN}$CHIP_NAME${NC}"
    echo -e "    $CHECKMARK Memory: ${GREEN}${MEMORY_GB}GB${NC} (unified, shared with GPU)"
    if is_apple_silicon; then
        echo -e "    $CHECKMARK Architecture: ${GREEN}arm64 (Apple Silicon)${NC}"
    else
        echo -e "    $WARNMARK Architecture: ${YELLOW}x86_64 (Intel - no Metal GPU acceleration)${NC}"
    fi
    
    # Build status
    echo
    echo -e "  ${BOLD}Build:${NC}"
    if [[ -f "$LLAMA_CPP_DIR/build/bin/llama-server" ]]; then
        echo -e "    $CHECKMARK llama-server binary: ${GREEN}found${NC}"
        echo -e "    $CHECKMARK Location: $LLAMA_CPP_DIR/build/bin/llama-server"
    else
        echo -e "    $CROSSMARK llama-server binary: ${RED}not built${NC}"
        echo -e "    ${DIM}Run ./setup-macos.sh to build${NC}"
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
    
    echo
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
        echo "Run ./setup-macos.sh first to clone and build llama.cpp"
        exit 1
    fi
    
    cd "$LLAMA_CPP_DIR"
    
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    print_status "Current version: $CURRENT_COMMIT"
    
    print_status "Checking for updates..."
    if ! git fetch origin main --quiet 2>/dev/null; then
        print_warning "Could not fetch from remote. Check network connection."
        cd "$SCRIPT_DIR"
        exit 0
    fi
    
    LOCAL_HEAD=$(git rev-parse HEAD 2>/dev/null)
    REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null)
    
    if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
        print_success "Already up to date!"
        cd "$SCRIPT_DIR"
        exit 0
    fi
    
    COMMITS_BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null || echo "?")
    print_status "Updates available: $COMMITS_BEHIND new commit(s)"
    echo
    echo -e "${DIM}Recent changes:${NC}"
    git log HEAD..origin/main --oneline 2>/dev/null | head -5
    echo
    
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
    
    CHIP_NAME=$(detect_apple_chip)
    print_status "Building for: $CHIP_NAME"
    
    print_status "Cleaning previous build..."
    rm -rf build
    
    print_status "Configuring CMake with Metal..."
    cmake -B build -DCMAKE_BUILD_TYPE=Release
    
    # Get number of CPU cores for parallel build
    NUM_CORES=$(sysctl -n hw.ncpu 2>/dev/null || echo 4)
    
    print_status "Building (this may take 5-10 minutes)..."
    start_spinner "Compiling llama.cpp"
    cmake --build build --config Release -- -j"$NUM_CORES" > /dev/null 2>&1
    stop_spinner true "Build complete"
    
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
    
    verify_model() {
        local model_path="$1"
        local model_name
        model_name=$(basename "$model_path")
        
        ((VERIFY_COUNT++))
        
        if [[ ! -f "$model_path" ]]; then
            echo -e "  $CROSSMARK $model_name - file not found"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        if [[ ! -r "$model_path" ]]; then
            echo -e "  $CROSSMARK $model_name - file not readable"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        local file_size
        file_size=$(stat -f%z "$model_path" 2>/dev/null || echo 0)
        if [[ "$file_size" -lt 1048576 ]]; then
            echo -e "  $CROSSMARK $model_name - file too small"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        local magic
        magic=$(head -c 4 "$model_path" 2>/dev/null | tr -d '\0')
        if [[ "$magic" != "GGUF" ]]; then
            echo -e "  $CROSSMARK $model_name - invalid GGUF format (magic: $magic)"
            ((VERIFY_FAIL++))
            return 1
        fi
        
        local size_human
        size_human=$(du -h "$model_path" | cut -f1)
        
        echo -e "  $CHECKMARK $model_name ($size_human) - valid GGUF"
        ((VERIFY_PASS++))
        return 0
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

echo
echo -e "${CYAN}${BOLD}============================================${NC}"
echo -e "${CYAN}${BOLD}  llama.cpp Metal Setup (macOS)${NC}"
echo -e "${CYAN}${BOLD}============================================${NC}"
echo

# -----------------------------------------------------------------------------
# Hardware Detection
# -----------------------------------------------------------------------------

CHIP_NAME=$(detect_apple_chip)
MEMORY_GB=$(get_memory_gb)

print_status "Detected: $CHIP_NAME with ${MEMORY_GB}GB unified memory"

if ! is_apple_silicon; then
    print_warning "Intel Mac detected - Metal GPU acceleration will be limited"
    echo -e "  ${DIM}For best performance, Apple Silicon (M1/M2/M3/M4) is recommended${NC}"
    echo
fi

# -----------------------------------------------------------------------------
# Dependency Check
# -----------------------------------------------------------------------------

print_header "Checking Dependencies"

MISSING_REQUIRED=()

# Xcode Command Line Tools
if xcode-select -p &>/dev/null; then
    XCODE_PATH=$(xcode-select -p)
    echo -e "  $CHECKMARK Xcode CLI Tools      installed ($XCODE_PATH)"
else
    echo -e "  $CROSSMARK Xcode CLI Tools      not installed"
    MISSING_REQUIRED+=("xcode-cli")
fi

# Git
if command -v git &>/dev/null; then
    GIT_VERSION=$(git --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    echo -e "  $CHECKMARK git                  installed ($GIT_VERSION)"
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

# Check macOS version (Metal requires 10.11+, but 11.0+ recommended for Apple Silicon)
MACOS_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "0.0")
MACOS_MAJOR=$(echo "$MACOS_VERSION" | cut -d. -f1)
if [[ $MACOS_MAJOR -ge 11 ]]; then
    echo -e "  $CHECKMARK macOS version        $MACOS_VERSION"
else
    echo -e "  $WARNMARK macOS version        $MACOS_VERSION (11.0+ recommended)"
fi

echo

if [[ ${#MISSING_REQUIRED[@]} -gt 0 ]]; then
    print_header "Missing Required Dependencies"
    echo
    
    for dep in "${MISSING_REQUIRED[@]}"; do
        case $dep in
            xcode-cli)
                echo -e "  ${BOLD}Xcode Command Line Tools:${NC}"
                echo "    xcode-select --install"
                echo
                ;;
            git)
                echo -e "  ${BOLD}git:${NC}"
                echo "    Included with Xcode CLI Tools, or:"
                echo "    brew install git"
                echo
                ;;
            cmake)
                echo -e "  ${BOLD}cmake:${NC}"
                echo "    brew install cmake"
                echo
                ;;
            curl)
                echo -e "  ${BOLD}curl:${NC}"
                echo "    brew install curl"
                echo
                ;;
            gum)
                echo -e "  ${BOLD}gum (interactive menus):${NC}"
                echo "    brew install gum"
                echo "    Or run with: ./setup-macos.sh --non-interactive"
                echo
                ;;
        esac
    done
    
    echo -e "${YELLOW}${BOLD}After installing dependencies, run this script again.${NC}"
    exit 1
fi

print_success "All dependencies satisfied!"

# -----------------------------------------------------------------------------
# Clone/Update llama.cpp
# -----------------------------------------------------------------------------

print_header "Setting Up llama.cpp Repository"

if [[ -d "$LLAMA_CPP_DIR" ]]; then
    if [[ "$FORCE_REBUILD" == true ]]; then
        print_status "Force rebuild requested, removing existing directory..."
        rm -rf "$LLAMA_CPP_DIR"
    else
        print_status "llama.cpp directory exists, pulling latest..."
        cd "$LLAMA_CPP_DIR"
        if git rev-parse --git-dir &>/dev/null; then
            git pull 2>/dev/null || print_warning "Failed to pull latest (continuing with existing)"
        else
            print_warning "Not a valid git repository, will re-clone"
            cd "$SCRIPT_DIR"
            rm -rf "$LLAMA_CPP_DIR"
        fi
        cd "$SCRIPT_DIR"
    fi
fi

if [[ ! -d "$LLAMA_CPP_DIR" ]]; then
    print_status "Cloning llama.cpp..."
    if ! git clone --depth 1 https://github.com/ggerganov/llama.cpp "$LLAMA_CPP_DIR"; then
        print_error "Failed to clone llama.cpp repository"
        echo "Check your network connection and try again"
        exit 1
    fi
fi

print_success "llama.cpp repository ready"

# -----------------------------------------------------------------------------
# Build llama.cpp with Metal
# -----------------------------------------------------------------------------

if [[ "$SKIP_BUILD" == false ]]; then
    print_header "Building llama.cpp with Metal"
    
    cd "$LLAMA_CPP_DIR"
    
    if [[ -f "build/bin/llama-server" && "$FORCE_REBUILD" != true ]]; then
        print_status "llama-server already built (use --force-rebuild to rebuild)"
    else
        print_status "Configuring CMake with Metal backend..."
        
        # Metal is enabled by default on macOS, no special flags needed
        cmake -B build -DCMAKE_BUILD_TYPE=Release
        
        # Get number of CPU cores for parallel build
        NUM_CORES=$(sysctl -n hw.ncpu 2>/dev/null || echo 4)
        
        print_status "Building (this may take 5-10 minutes)..."
        start_spinner "Compiling llama.cpp"
        cmake --build build --config Release -- -j"$NUM_CORES" > /dev/null 2>&1
        stop_spinner true "Build complete"
    fi
    
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
    handle_opencode_config "$OPENCODE_CONFIG" "$SCRIPT_DIR/sync-opencode-config.sh" "$NON_INTERACTIVE" _generate_config
else
    print_warning "No models downloaded, skipping OpenCode config"
fi

# Handle AGENTS.md
OPENCODE_CONFIG_DIR="$(dirname "$OPENCODE_CONFIG")"
handle_agents_md "$SCRIPT_DIR" "$OPENCODE_CONFIG_DIR" "$NON_INTERACTIVE" "false"

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

if [[ -f "$LOCAL_ENV" && "$FORCE_ENV" != "true" ]]; then
    print_status ".env already exists, keeping current configuration"
    print_status "Use --force-env to regenerate"
else
    if [[ -f "$LOCAL_ENV" ]]; then
        print_status "Regenerating .env (--force-env)"
    fi
    
    cat > "$LOCAL_ENV" << EOF
# llama.cpp Configuration (macOS)
# Generated by setup-macos.sh on $(date)

# Hardware (detected: $CHIP_NAME)
CHIP_NAME=$CHIP_NAME
MEMORY_GB=$MEMORY_GB

# Server settings
LLAMA_PORT=$DEFAULT_PORT
LLAMA_CONTEXT=$DEFAULT_CONTEXT

# Paths
LLAMA_CPP_DIR=$LLAMA_CPP_DIR
MODELS_DIR=$MODELS_DIR
EOF

    print_success "Created .env"
fi

# -----------------------------------------------------------------------------
# Setup Complete
# -----------------------------------------------------------------------------

print_header "Setup Complete!"

echo
echo -e "${BOLD}Configuration:${NC}"
echo "  Chip:             $CHIP_NAME"
echo "  Memory:           ${MEMORY_GB}GB unified"
echo "  llama.cpp:        $LLAMA_CPP_DIR"
echo "  Models:           $MODELS_DIR"
echo "  Server port:      $DEFAULT_PORT"
echo
echo -e "${BOLD}Quick commands:${NC}"
echo "  Start server:     ./start-server.sh <model-id>"
echo "  Download model:   ./download-model.sh <model-id>"
echo "  Check status:     ./setup-macos.sh --status"
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
            test_choice=$(gum choose --cursor-prefix="[ ] " --selected-prefix="[x] " \
                --cursor.foreground="212" \
                "Yes - test with $TEST_MODEL (smallest)" \
                "Choose different model" \
                "Skip test") || true
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
                    selected_label=$(gum choose --cursor-prefix="[ ] " --selected-prefix="[x] " \
                        --cursor.foreground="212" \
                        "${test_model_labels[@]}" \
                        "Skip test") || true
                    
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
                    run_inference_test "$selected_model" "$sel_gguf_file" "$sel_size_mb" || true
                fi
                ;;
            *)
                run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" || true
                ;;
        esac
    else
        run_inference_test "$TEST_MODEL" "$test_gguf_file" "$test_size_mb" || true
    fi
fi

echo
echo -e "${BOLD}Using with OpenCode:${NC}"
echo "  1. Start server:  ./start-server.sh ${EXAMPLE_MODEL:-<model-id>}"
echo "  2. Run opencode in any project"
echo "  3. Use '/models' to select llama.cpp provider"
echo
echo -e "${GREEN}${BOLD}Happy coding!${NC}"
echo
