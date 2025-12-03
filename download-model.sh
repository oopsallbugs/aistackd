#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# llama.cpp Model Download Script
# Download individual GGUF models from HuggingFace
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
MODELS_CONF="$SCRIPT_DIR/models.conf"
MODELS_DIR="$SCRIPT_DIR/models"

# Colors - only use if terminal supports them
if [[ -t 1 ]] && [[ "${TERM:-dumb}" != "dumb" ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    DIM='\033[2m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    BOLD=''
    DIM=''
    NC=''
fi

# Check for gum
HAS_GUM=false
if command -v gum &>/dev/null; then
    HAS_GUM=true
fi

print_status() { echo -e "${CYAN}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Validate a models.conf entry
# Usage: validate_model_entry <category> <model_id> <hf_repo> <gguf_file> <size> [line_num]
# Returns 0 if valid, 1 if invalid (with warning printed)
validate_model_entry() {
    local category="$1"
    local model_id="$2"
    local hf_repo="$3"
    local gguf_file="$4"
    local size="$5"
    local line_num="${6:-}"
    
    local line_info=""
    [[ -n "$line_num" ]] && line_info=" (line $line_num)"
    
    # Required fields must not be empty
    if [[ -z "$category" || -z "$model_id" || -z "$hf_repo" || -z "$gguf_file" ]]; then
        print_warning "Skipping invalid entry${line_info}: missing required fields"
        return 1
    fi
    
    # model_id should be alphanumeric with hyphens/underscores/dots
    if [[ ! "$model_id" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        print_warning "Skipping invalid entry${line_info}: model_id contains invalid characters: $model_id"
        return 1
    fi
    
    # gguf_file must end in .gguf
    if [[ ! "$gguf_file" =~ \.gguf$ ]]; then
        print_warning "Skipping invalid entry${line_info}: gguf_file must end in .gguf: $gguf_file"
        return 1
    fi
    
    # gguf_file should not contain path traversal
    if [[ "$gguf_file" =~ \.\. || "$gguf_file" =~ ^/ ]]; then
        print_warning "Skipping invalid entry${line_info}: gguf_file contains invalid path: $gguf_file"
        return 1
    fi
    
    # hf_repo should look like owner/repo
    if [[ ! "$hf_repo" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]]; then
        print_warning "Skipping invalid entry${line_info}: hf_repo format invalid: $hf_repo"
        return 1
    fi
    
    return 0
}

# Parse size string to bytes (e.g., "20GB" -> 21474836480, "500MB" -> 524288000)
parse_size_bytes() {
    local size="$1"
    local result=0
    
    if [[ "$size" =~ ^([0-9]+)\.([0-9]+)GB$ ]]; then
        local whole="${BASH_REMATCH[1]}"
        local frac="${BASH_REMATCH[2]}"
        frac="${frac:0:2}"  # Keep 2 decimal places
        [[ ${#frac} -eq 1 ]] && frac="${frac}0"
        result=$(( (whole * 100 + frac) * 1073741824 / 100 ))
    elif [[ "$size" =~ ^([0-9]+)GB$ ]]; then
        result=$(( BASH_REMATCH[1] * 1073741824 ))
    elif [[ "$size" =~ ^([0-9]+)\.([0-9]+)MB$ ]]; then
        local whole="${BASH_REMATCH[1]}"
        result=$(( whole * 1048576 ))
    elif [[ "$size" =~ ^([0-9]+)MB$ ]]; then
        result=$(( BASH_REMATCH[1] * 1048576 ))
    fi
    
    echo "$result"
}

# Check available disk space before download
# Usage: check_disk_space <target_dir> <required_bytes> [model_size_string]
# Returns 0 if enough space, 1 if not
check_disk_space() {
    local target_dir="$1"
    local required_bytes="$2"
    local size_str="${3:-}"
    
    # Get available space in bytes
    local available_bytes
    available_bytes=$(df -B1 "$target_dir" 2>/dev/null | tail -1 | awk '{print $4}')
    
    if [[ -z "$available_bytes" || ! "$available_bytes" =~ ^[0-9]+$ ]]; then
        # Can't determine disk space, proceed anyway
        return 0
    fi
    
    # Require at least required_bytes + 10% buffer
    local required_with_buffer=$(( required_bytes * 110 / 100 ))
    
    if [[ $available_bytes -lt $required_with_buffer ]]; then
        local available_gb=$(( available_bytes / 1073741824 ))
        local required_gb=$(( required_bytes / 1073741824 ))
        print_error "Insufficient disk space"
        echo
        echo -e "  ${BOLD}Required:${NC}  ~${size_str:-${required_gb}GB}"
        echo -e "  ${BOLD}Available:${NC} ${available_gb}GB"
        echo
        echo "Free up space in: $target_dir"
        return 1
    fi
    
    return 0
}

# Spinner for operations
SPINNER_CHARS='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
SPINNER_PID=""

# Track temp files for cleanup
TEMP_FILES=()

cleanup_temp_files() {
    for f in "${TEMP_FILES[@]}"; do
        [[ -f "$f" ]] && rm -f "$f"
    done
    TEMP_FILES=()
}

cleanup_spinner() {
    if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
    fi
    SPINNER_PID=""
    printf "\r\033[K"
}

handle_interrupt() {
    cleanup_spinner
    cleanup_temp_files
    echo
    echo
    print_status "Cancelled by user (Ctrl+C)"
    echo
    exit 130
}

cleanup_all() {
    cleanup_spinner
    cleanup_temp_files
}

trap handle_interrupt INT TERM PIPE
trap cleanup_all EXIT

# Download spinner with progress tracking
start_download_spinner() {
    local message="$1"
    local output_file="$2"
    local expected_size="$3"  # Optional expected size in bytes
    local start_time=$SECONDS
    (
        local i=0
        local spin_len=${#SPINNER_CHARS}
        while true; do
            local elapsed=$((SECONDS - start_time))
            local current_size=0
            local size_str=""
            
            if [[ -f "$output_file" ]]; then
                current_size=$(stat -c%s "$output_file" 2>/dev/null || stat -f%z "$output_file" 2>/dev/null || echo 0)
            fi
            
            # Format size
            if [[ $current_size -ge 1073741824 ]]; then
                size_str="$(echo "scale=1; $current_size / 1073741824" | bc 2>/dev/null || echo "?")GB"
            elif [[ $current_size -ge 1048576 ]]; then
                size_str="$(( current_size / 1048576 ))MB"
            elif [[ $current_size -gt 0 ]]; then
                size_str="$(( current_size / 1024 ))KB"
            fi
            
            # Show progress with optional percentage
            if [[ -n "$expected_size" && "$expected_size" -gt 0 && $current_size -gt 0 ]]; then
                local pct=$(( current_size * 100 / expected_size ))
                printf "\r  ${CYAN}%s${NC} %s ${DIM}[%s] %d%% (%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$size_str" "$pct" "$elapsed"
            elif [[ -n "$size_str" ]]; then
                printf "\r  ${CYAN}%s${NC} %s ${DIM}[%s] (%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$size_str" "$elapsed"
            else
                printf "\r  ${CYAN}%s${NC} %s ${DIM}(%ds)${NC}  " "${SPINNER_CHARS:i:1}" "$message" "$elapsed"
            fi
            
            i=$(( (i + 1) % spin_len ))
            sleep 0.2
        done
    ) &
    SPINNER_PID=$!
}

stop_spinner() {
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    printf "\r\033[K"
}

show_help() {
    echo
    echo -e "${CYAN}${BOLD}llama.cpp Model Downloader${NC}"
    echo
    echo "Usage: ./download-model.sh [OPTIONS] <model-id>"
    echo
    echo "Arguments:"
    echo "  model-id          Model ID from models.conf (e.g., qwen3-8b-q4km)"
    echo
    echo "Options:"
    echo "  --list            List all available models"
    echo "  --list-downloaded List only downloaded models"
    echo "  --info <model>    Show detailed info about a model"
    echo "  --force           Re-download even if model exists"
    echo "  --search [query]  Search HuggingFace for GGUF models"
    echo "  --trending        Show trending GGUF models on HuggingFace"
    echo "  --browse <repo>   List GGUF files in a HuggingFace repo"
    echo "  --add <repo>      Download a model and add to models.conf"
    echo "  --cleanup         Find and remove orphan .gguf files not in models.conf"
    echo "  --validate        Validate models.conf syntax"
    echo "  --help            Show this help message"
    echo
    echo "Adding new models:"
    echo "  ./download-model.sh --search codestral       # Find models"
    echo "  ./download-model.sh --add <repo>             # Download + add + sync"
    echo
    echo "Cleaning up:"
    echo "  ./download-model.sh --cleanup                # Remove orphan models"
    echo
    echo "Examples:"
    echo "  ./download-model.sh --add bartowski/Codestral-22B-v0.1-GGUF"
    echo "  ./download-model.sh qwen3-8b-q4km"
    echo
}

list_models() {
    local show_all=${1:-true}
    
    echo
    echo -e "${CYAN}${BOLD}Available Models${NC}  ${DIM}(${GREEN}✓${NC}${DIM} = installed)${NC}"
    echo
    
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found at: $MODELS_CONF"
        exit 1
    fi
    
    local current_category=""
    
    while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
        # Skip comments and empty lines
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim whitespace
        category="${category#"${category%%[![:space:]]*}"}"
        category="${category%"${category##*[![:space:]]}"}"
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        hf_repo="${hf_repo#"${hf_repo%%[![:space:]]*}"}"
        hf_repo="${hf_repo%"${hf_repo##*[![:space:]]}"}"
        gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
        gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
        size="${size#"${size%%[![:space:]]*}"}"
        size="${size%"${size##*[![:space:]]}"}"
        description="${description#"${description%%[![:space:]]*}"}"
        description="${description%"${description##*[![:space:]]}"}"
        
        # Validate entry
        validate_model_entry "$category" "$model_id" "$hf_repo" "$gguf_file" "$size" || continue
        
        local is_downloaded=false
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            is_downloaded=true
        fi
        
        # Skip non-downloaded if --list-downloaded
        if [[ "$show_all" != true && "$is_downloaded" != true ]]; then
            continue
        fi
        
        # Print category header
        if [[ "$category" != "$current_category" ]]; then
            current_category="$category"
            echo
            echo -e "  ${BOLD}${category^^}${NC}"
        fi
        
        if [[ "$is_downloaded" == true ]]; then
            local actual_size
            actual_size=$(du -h "$MODELS_DIR/$gguf_file" | cut -f1)
            echo -e "    ${GREEN}✓${NC} $model_id (${actual_size}) - $description"
        else
            echo -e "    ${DIM}○${NC} $model_id (~$size) - $description"
        fi
    done < "$MODELS_CONF"
    
    echo
    echo -e "${DIM}Models directory: $MODELS_DIR${NC}"
    echo
    echo -e "${BOLD}To add new models:${NC}"
    echo "  ./download-model.sh --search <query>    # Find models on HuggingFace"
    echo "  ./download-model.sh --add <repo>        # Download + add + sync"
    echo
}

show_model_info() {
    local search_model="$1"
    
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found"
        exit 1
    fi
    
    while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        
        if [[ "$model_id" == "$search_model" ]]; then
            # Trim all fields
            category="${category#"${category%%[![:space:]]*}"}"
            category="${category%"${category##*[![:space:]]}"}"
            hf_repo="${hf_repo#"${hf_repo%%[![:space:]]*}"}"
            hf_repo="${hf_repo%"${hf_repo##*[![:space:]]}"}"
            gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
            gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
            size="${size#"${size%%[![:space:]]*}"}"
            size="${size%"${size##*[![:space:]]}"}"
            description="${description#"${description%%[![:space:]]*}"}"
            description="${description%"${description##*[![:space:]]}"}"
            
            echo
            echo -e "${CYAN}${BOLD}Model: $model_id${NC}"
            echo
            echo -e "  ${BOLD}Category:${NC}     $category"
            echo -e "  ${BOLD}Description:${NC}  $description"
            echo -e "  ${BOLD}Size:${NC}         ~$size"
            echo -e "  ${BOLD}GGUF File:${NC}    $gguf_file"
            echo -e "  ${BOLD}HuggingFace:${NC}  https://huggingface.co/$hf_repo"
            echo
            
            if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
                local actual_size
                actual_size=$(du -h "$MODELS_DIR/$gguf_file" | cut -f1)
                echo -e "  ${BOLD}Status:${NC}       ${GREEN}[INSTALLED]${NC} ($actual_size)"
                echo -e "  ${BOLD}Location:${NC}     $MODELS_DIR/$gguf_file"
            else
                echo -e "  ${BOLD}Status:${NC}       ${DIM}[NOT INSTALLED]${NC}"
            fi
            echo
            return 0
        fi
    done < "$MODELS_CONF"
    
    print_error "Model '$search_model' not found in models.conf"
    echo
    echo "Run './download-model.sh --list' to see available models"
    exit 1
}

download_model() {
    local search_model="$1"
    local force=${2:-false}
    
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found"
        exit 1
    fi
    
    local found=false
    local hf_repo=""
    local gguf_file=""
    local size=""
    local description=""
    
    while IFS='|' read -r category model_id repo file sz desc || [[ -n "$category" ]]; do
        [[ "$category" =~ ^[[:space:]]*# ]] && continue
        [[ "$category" =~ ^ALIAS: ]] && continue
        [[ -z "$category" ]] && continue
        
        # Trim model_id
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        
        if [[ "$model_id" == "$search_model" ]]; then
            found=true
            # Trim all fields
            category="${category#"${category%%[![:space:]]*}"}"
            category="${category%"${category##*[![:space:]]}"}"
            hf_repo="${repo#"${repo%%[![:space:]]*}"}"
            hf_repo="${hf_repo%"${hf_repo##*[![:space:]]}"}"
            gguf_file="${file#"${file%%[![:space:]]*}"}"
            gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
            size="${sz#"${sz%%[![:space:]]*}"}"
            size="${size%"${size##*[![:space:]]}"}"
            description="${desc#"${desc%%[![:space:]]*}"}"
            description="${description%"${description##*[![:space:]]}"}"
            
            # Validate the entry before using it
            if ! validate_model_entry "$category" "$model_id" "$hf_repo" "$gguf_file" "$size"; then
                print_error "Model entry for '$search_model' is invalid"
                exit 1
            fi
            break
        fi
    done < "$MODELS_CONF"
    
    if [[ "$found" != true ]]; then
        print_error "Model '$search_model' not found in models.conf"
        echo
        echo "Run './download-model.sh --list' to see available models"
        exit 1
    fi
    
    local output_path="$MODELS_DIR/$gguf_file"
    
    # Check if already exists
    if [[ -f "$output_path" && "$force" != true ]]; then
        local actual_size
        actual_size=$(du -h "$output_path" | cut -f1)
        print_success "$search_model already downloaded ($actual_size)"
        echo
        echo "Use --force to re-download"
        exit 0
    fi
    
    if [[ -f "$output_path" && "$force" == true ]]; then
        print_warning "Re-downloading $search_model (--force)"
        rm -f "$output_path"
    fi
    
    # Create models directory
    mkdir -p "$MODELS_DIR"
    
    # Check disk space before downloading
    local required_bytes
    required_bytes=$(parse_size_bytes "$size")
    if [[ "$required_bytes" -gt 0 ]]; then
        if ! check_disk_space "$MODELS_DIR" "$required_bytes" "$size"; then
            exit 1
        fi
    fi
    
    echo
    echo -e "${CYAN}${BOLD}Downloading: $search_model${NC}"
    echo
    echo -e "  ${BOLD}File:${NC}        $gguf_file"
    echo -e "  ${BOLD}Size:${NC}        ~$size"
    echo -e "  ${BOLD}Source:${NC}      huggingface.co/$hf_repo"
    echo -e "  ${BOLD}Destination:${NC} $output_path"
    echo
    
    # Get expected file size from HuggingFace API (for progress %)
    local expected_bytes=""
    if command -v jq &>/dev/null; then
        expected_bytes=$(curl -sf "https://huggingface.co/api/models/$hf_repo/tree/main" 2>/dev/null | \
            jq -r ".[] | select(.path == \"$gguf_file\") | .size" 2>/dev/null || echo)
    fi
    
    # Download using huggingface-cli (preferred) or curl (fallback)
    if command -v huggingface-cli &>/dev/null; then
        start_download_spinner "Downloading with huggingface-cli" "$output_path" "$expected_bytes"
        
        huggingface-cli download "$hf_repo" "$gguf_file" \
            --local-dir "$MODELS_DIR" \
            --local-dir-use-symlinks False \
            --quiet 2>/dev/null
        local dl_status=$?
        
        stop_spinner
        
        # huggingface-cli may create nested directories, move file if needed
        if [[ -f "$MODELS_DIR/$gguf_file" ]]; then
            : # File is where we expect
        elif [[ -f "$MODELS_DIR/$hf_repo/$gguf_file" ]]; then
            mv "$MODELS_DIR/$hf_repo/$gguf_file" "$output_path"
            rm -rf "$MODELS_DIR/${hf_repo%%/*}" 2>/dev/null || true
        fi
        
        if [[ $dl_status -ne 0 ]]; then
            print_error "Download failed"
            exit 1
        fi
    else
        local url="https://huggingface.co/$hf_repo/resolve/main/$gguf_file"
        start_download_spinner "Downloading with curl" "$output_path" "$expected_bytes"
        
        local curl_error
        curl_error=$(mktemp)
        TEMP_FILES+=("$curl_error")
        
        # Use timeout and retry options for large file downloads
        # --connect-timeout: max time for connection establishment
        # --max-time: no limit for large files (handled by -C - for resume)
        # --retry: retry on transient failures
        # --retry-delay: wait between retries
        # -C -: resume from where left off if interrupted
        curl -fL \
            --connect-timeout 30 \
            --retry 3 \
            --retry-delay 5 \
            --retry-connrefused \
            -C - \
            -o "$output_path" "$url" 2>"$curl_error"
        local dl_status=$?
        
        stop_spinner
        
        if [[ $dl_status -ne 0 ]]; then
            print_error "Download failed"
            if [[ -s "$curl_error" ]]; then
                echo -e "${DIM}curl error: $(cat "$curl_error")${NC}"
            fi
            rm -f "$output_path" "$curl_error"
            exit 1
        fi
        rm -f "$curl_error"
    fi
    
    # Verify download
    if [[ -f "$output_path" ]]; then
        local actual_size
        actual_size=$(du -h "$output_path" | cut -f1)
        echo
        print_success "Downloaded: $search_model ($actual_size)"
        
        # Auto-sync to OpenCode config
        if [[ -x "$SCRIPT_DIR/sync-opencode-config.sh" ]]; then
            echo
            "$SCRIPT_DIR/sync-opencode-config.sh"
        fi
        
        echo
        echo "Start server with:"
        echo "  ./start-server.sh $search_model"
        echo
    else
        print_error "Download failed - file not found at $output_path"
        exit 1
    fi
}

# =============================================================================
# HuggingFace Search Functions
# =============================================================================

search_huggingface() {
    local query="${1:-}"
    local limit="${2:-20}"
    
    echo
    echo -e "${CYAN}${BOLD}Searching HuggingFace for GGUF models...${NC}"
    echo
    
    if ! command -v curl &>/dev/null; then
        print_error "curl is required for searching"
        exit 1
    fi
    
    if ! command -v jq &>/dev/null; then
        print_error "jq is required for searching (install: sudo pacman -S jq)"
        exit 1
    fi
    
    local url="https://huggingface.co/api/models?filter=gguf&sort=downloads&direction=-1&limit=$limit"
    if [[ -n "$query" ]]; then
        url="https://huggingface.co/api/models?search=$query&filter=gguf&sort=downloads&direction=-1&limit=$limit"
    fi
    
    local response
    response=$(curl -sf --connect-timeout 15 --max-time 60 "$url")
    
    if [[ -z "$response" || "$response" == "[]" ]]; then
        print_warning "No results found"
        return
    fi
    
    echo -e "  ${BOLD}Top GGUF Models${NC}${query:+ matching \"$query\"}:"
    echo
    
    # Parse and display results
    echo "$response" | jq -r '.[] | "\(.modelId)|\(.downloads)|\(.likes)"' | while IFS='|' read -r model_id downloads likes; do
        # Format download count
        local dl_formatted
        if [[ $downloads -ge 1000000 ]]; then
            dl_formatted="$(( downloads / 1000000 ))M"
        elif [[ $downloads -ge 1000 ]]; then
            dl_formatted="$(( downloads / 1000 ))K"
        else
            dl_formatted="$downloads"
        fi
        
        printf "    ${GREEN}%-50s${NC} ${DIM}↓${dl_formatted} ♥${likes}${NC}\n" "$model_id"
    done
    
    echo
    echo -e "${BOLD}To add a model:${NC}"
    echo "  ./download-model.sh --add <repo>       # Download + add + sync"
    echo
}

show_trending() {
    local limit="${1:-15}"
    
    echo
    echo -e "${CYAN}${BOLD}Trending GGUF Models on HuggingFace${NC}"
    echo
    
    if ! command -v curl &>/dev/null; then
        print_error "curl is required"
        exit 1
    fi
    
    if ! command -v jq &>/dev/null; then
        print_error "jq is required (install: sudo pacman -S jq)"
        exit 1
    fi
    
    # Get trending (sorted by likes, recent)
    local url="https://huggingface.co/api/models?filter=gguf&sort=likes7d&direction=-1&limit=$limit"
    
    local response
    response=$(curl -sf --connect-timeout 15 --max-time 60 "$url")
    
    if [[ -z "$response" || "$response" == "[]" ]]; then
        print_warning "Could not fetch trending models"
        return
    fi
    
    echo -e "  ${BOLD}Trending This Week:${NC}"
    echo
    
    echo "$response" | jq -r '.[] | "\(.modelId)|\(.downloads)|\(.likes)"' | while IFS='|' read -r model_id downloads likes; do
        local dl_formatted
        if [[ $downloads -ge 1000000 ]]; then
            dl_formatted="$(( downloads / 1000000 ))M"
        elif [[ $downloads -ge 1000 ]]; then
            dl_formatted="$(( downloads / 1000 ))K"
        else
            dl_formatted="$downloads"
        fi
        
        printf "    ${GREEN}%-50s${NC} ${DIM}↓${dl_formatted} ♥${likes}${NC}\n" "$model_id"
    done
    
    echo
    echo -e "${BOLD}To add a model:${NC}"
    echo "  ./download-model.sh --search <query>   # Search for models"
    echo "  ./download-model.sh --add <repo>       # Download + add + sync"
    echo
}

browse_model_files() {
    local repo="$1"
    
    echo
    echo -e "${CYAN}${BOLD}Files in: $repo${NC}"
    echo
    
    if ! command -v curl &>/dev/null || ! command -v jq &>/dev/null; then
        print_error "curl and jq are required"
        exit 1
    fi
    
    # Fetch file listing from HuggingFace API
    local url="https://huggingface.co/api/models/$repo/tree/main"
    local response
    response=$(curl -sf --connect-timeout 15 --max-time 60 "$url")
    
    if [[ -z "$response" ]] || echo "$response" | jq -e '.error' &>/dev/null; then
        print_error "Could not fetch files for '$repo'"
        echo "Check if the repository exists: https://huggingface.co/$repo"
        exit 1
    fi
    
    echo -e "  ${BOLD}GGUF Files:${NC}"
    echo
    
    # Filter and display .gguf files with sizes
    echo "$response" | jq -r '.[] | select(.path | endswith(".gguf")) | "\(.path)|\(.size)"' | while IFS='|' read -r filename size; do
        # Format size
        local size_formatted
        if [[ $size -ge 1073741824 ]]; then
            size_formatted="$(echo "scale=1; $size / 1073741824" | bc)GB"
        elif [[ $size -ge 1048576 ]]; then
            size_formatted="$(( size / 1048576 ))MB"
        else
            size_formatted="${size}B"
        fi
        
        # Highlight Q4_K_M as recommended
        if [[ "$filename" == *"Q4_K_M"* ]]; then
            printf "    ${GREEN}%-60s${NC} %s ${YELLOW}← recommended${NC}\n" "$filename" "$size_formatted"
        else
            printf "    %-60s %s\n" "$filename" "$size_formatted"
        fi
    done
    
    echo
    echo -e "${BOLD}To download a model:${NC}"
    echo "  ./download-model.sh --add $repo"
    echo
}

add_model() {
    local repo="$1"
    local specific_file="${2:-}"
    
    echo
    echo -e "${CYAN}${BOLD}Add Model from: $repo${NC}"
    echo
    
    if ! command -v curl &>/dev/null || ! command -v jq &>/dev/null; then
        print_error "curl and jq are required"
        exit 1
    fi
    
    # Fetch file listing
    local url="https://huggingface.co/api/models/$repo/tree/main"
    local response
    response=$(curl -sf --connect-timeout 15 --max-time 60 "$url")
    
    if [[ -z "$response" ]] || echo "$response" | jq -e '.error' &>/dev/null; then
        print_error "Could not fetch files for '$repo'"
        echo "Check if the repository exists: https://huggingface.co/$repo"
        exit 1
    fi
    
    # Get list of GGUF files
    local gguf_files
    gguf_files=$(echo "$response" | jq -r '.[] | select(.path | endswith(".gguf")) | "\(.path)|\(.size)"')
    
    if [[ -z "$gguf_files" ]]; then
        print_error "No GGUF files found in $repo"
        exit 1
    fi
    
    # Build arrays of files and sizes
    local files_array=()
    local sizes_array=()
    local display_options=()
    local recommended_file=""
    
    while IFS='|' read -r filename size; do
        files_array+=("$filename")
        sizes_array+=("$size")
        
        local size_formatted
        if [[ $size -ge 1073741824 ]]; then
            size_formatted="$(echo "scale=1; $size / 1073741824" | bc)GB"
        elif [[ $size -ge 1048576 ]]; then
            size_formatted="$(( size / 1048576 ))MB"
        else
            size_formatted="${size}B"
        fi
        
        if [[ "$filename" == *"Q4_K_M"* ]]; then
            display_options+=("$filename ($size_formatted) ← recommended")
            [[ -z "$recommended_file" ]] && recommended_file="$filename ($size_formatted) ← recommended"
        else
            display_options+=("$filename ($size_formatted)")
        fi
    done <<< "$gguf_files"
    
    local selected_files=()
    local selected_sizes=()
    
    if [[ -n "$specific_file" ]]; then
        # User specified a file on command line
        for i in "${!files_array[@]}"; do
            if [[ "${files_array[$i]}" == "$specific_file" ]]; then
                selected_files+=("${files_array[$i]}")
                selected_sizes+=("${sizes_array[$i]}")
                break
            fi
        done
        
        if [[ ${#selected_files[@]} -eq 0 ]]; then
            print_error "File '$specific_file' not found in $repo"
            echo
            echo "Available files:"
            printf '  %s\n' "${files_array[@]}"
            exit 1
        fi
    elif [[ "$HAS_GUM" == true ]]; then
        # Use gum for multi-select
        echo -e "  ${DIM}Quantization: Q2/Q3 = smaller/lower quality │ Q4_K_M = best balance │ Q5+ = higher quality${NC}"
        echo -e "  ${DIM}Size is disk space. VRAM usage ~10-20% higher when loaded.${NC}"
        echo -e "  ${DIM}Use Space to toggle, Enter to confirm${NC}"
        echo
        
        local gum_selected
        if [[ -n "$recommended_file" ]]; then
            gum_selected=$(gum choose --no-limit \
                --cursor-prefix="○ " \
                --selected-prefix="✓ " \
                --unselected-prefix="○ " \
                --cursor.foreground="212" \
                --selected.foreground="212" \
                --height=20 \
                --selected="$recommended_file" \
                "${display_options[@]}") || {
                echo
                print_status "Selection cancelled"
                exit 0
            }
        else
            gum_selected=$(gum choose --no-limit \
                --cursor-prefix="○ " \
                --selected-prefix="✓ " \
                --unselected-prefix="○ " \
                --cursor.foreground="212" \
                --selected.foreground="212" \
                --height=20 \
                "${display_options[@]}") || {
                echo
                print_status "Selection cancelled"
                exit 0
            }
        fi
        
        if [[ -z "$gum_selected" ]]; then
            print_warning "No models selected"
            exit 0
        fi
        
        # Parse selections back to filenames
        while IFS= read -r line; do
            # Extract filename from "filename (size)" or "filename (size) ← recommended"
            # Use more robust extraction: everything before " ("
            local selected_name
            selected_name="${line%% (*}"
            
            for i in "${!files_array[@]}"; do
                if [[ "${files_array[$i]}" == "$selected_name" ]]; then
                    selected_files+=("${files_array[$i]}")
                    selected_sizes+=("${sizes_array[$i]}")
                    break
                fi
            done
        done <<< "$gum_selected"
    else
        # Fallback to numbered menu (single select)
        echo -e "  ${DIM}Quantization: Q2/Q3 = smaller/lower quality │ Q4_K_M = best balance │ Q5+ = higher quality${NC}"
        echo -e "  ${DIM}Size is disk space. VRAM usage ~10-20% higher when loaded.${NC}"
        echo -e "  ${DIM}Install 'gum' for multi-select: sudo pacman -S gum${NC}"
        echo
        printf "  ${BOLD}%-60s %s${NC}\n" "Available GGUF files" "Disk Size"
        echo
        
        local i=1
        local recommended_idx=""
        
        for opt in "${display_options[@]}"; do
            if [[ "$opt" == *"← recommended"* ]]; then
                printf "    ${GREEN}%2d)${NC} %s\n" "$i" "$opt"
                [[ -z "$recommended_idx" ]] && recommended_idx=$i
            else
                printf "    %2d) %s\n" "$i" "$opt"
            fi
            ((i++))
        done
        
        echo
        local default_prompt=""
        [[ -n "$recommended_idx" ]] && default_prompt=" [${recommended_idx}]"
        
        read -r -p "Select file number${default_prompt}: " selection
        
        # Use recommended if empty
        [[ -z "$selection" && -n "$recommended_idx" ]] && selection=$recommended_idx
        
        if ! [[ "$selection" =~ ^[0-9]+$ ]] || [[ $selection -lt 1 ]] || [[ $selection -gt ${#files_array[@]} ]]; then
            print_error "Invalid selection"
            exit 1
        fi
        
        selected_files+=("${files_array[$((selection-1))]}")
        selected_sizes+=("${sizes_array[$((selection-1))]}")
    fi
    
    if [[ ${#selected_files[@]} -eq 0 ]]; then
        print_warning "No models selected"
        exit 0
    fi
    
    # Download each selected file
    local downloaded_models=()
    
    for i in "${!selected_files[@]}"; do
        local sel_file="${selected_files[$i]}"
        local sel_size="${selected_sizes[$i]}"
        
        # Format size for display
        local size_formatted
        if [[ $sel_size -ge 1073741824 ]]; then
            size_formatted="$(echo "scale=1; $sel_size / 1073741824" | bc)GB"
        elif [[ $sel_size -ge 1048576 ]]; then
            size_formatted="$(( sel_size / 1048576 ))MB"
        else
            size_formatted="${sel_size}B"
        fi
        
        # Generate model ID from filename
        local model_id
        model_id=$(echo "$sel_file" | sed 's/\.gguf$//' | tr '[:upper:]' '[:lower:]' | tr '._' '-' | sed 's/--*/-/g')
        
        echo
        echo -e "${BOLD}[$((i+1))/${#selected_files[@]}] Downloading: $sel_file${NC}"
        echo "  Size:     $size_formatted"
        echo "  Model ID: $model_id"
        
        # Check if already exists in models.conf
        if grep -q "|${model_id}|" "$MODELS_CONF" 2>/dev/null; then
            print_warning "Model '$model_id' already exists in models.conf, skipping..."
            continue
        fi
        
        # Create models directory
        mkdir -p "$MODELS_DIR"
        
        local output_path="$MODELS_DIR/$sel_file"
        
        # Check if file already downloaded
        if [[ -f "$output_path" ]]; then
            local actual_size
            actual_size=$(du -h "$output_path" | cut -f1)
            print_status "File already exists ($actual_size), adding to config..."
        else
            # Download with spinner
            if command -v huggingface-cli &>/dev/null; then
                start_download_spinner "Downloading with huggingface-cli" "$output_path" "$sel_size"
                huggingface-cli download "$repo" "$sel_file" \
                    --local-dir "$MODELS_DIR" \
                    --local-dir-use-symlinks False \
                    --quiet 2>/dev/null
                local dl_status=$?
                stop_spinner
                
                if [[ $dl_status -ne 0 ]]; then
                    print_error "Download failed for $sel_file"
                    continue
                fi
            else
                local dl_url="https://huggingface.co/$repo/resolve/main/$sel_file"
                start_download_spinner "Downloading with curl" "$output_path" "$sel_size"
                
                local curl_error
                curl_error=$(mktemp)
                TEMP_FILES+=("$curl_error")
                
                curl -fL \
                    --connect-timeout 30 \
                    --retry 3 \
                    --retry-delay 5 \
                    --retry-connrefused \
                    -C - \
                    -o "$output_path" "$dl_url" 2>"$curl_error"
                local dl_status=$?
                stop_spinner
                
                if [[ $dl_status -ne 0 ]]; then
                    print_error "Download failed for $sel_file"
                    if [[ -s "$curl_error" ]]; then
                        echo -e "${DIM}curl error: $(cat "$curl_error")${NC}"
                    fi
                    rm -f "$output_path" "$curl_error"
                    continue
                fi
                rm -f "$curl_error"
            fi
        fi
        
        # Verify download
        if [[ ! -f "$output_path" ]]; then
            print_error "Download failed for $sel_file"
            continue
        fi
        
        # Add to models.conf
        if ! grep -q "|${model_id}|" "$MODELS_CONF" 2>/dev/null; then
            # Ensure uncategorized section exists
            if ! grep -q "^# UNCATEGORIZED" "$MODELS_CONF"; then
                echo >> "$MODELS_CONF"
                echo "# -----------------------------------------------------------------------------" >> "$MODELS_CONF"
                echo "# UNCATEGORIZED - Move these to appropriate categories" >> "$MODELS_CONF"
                echo "# -----------------------------------------------------------------------------" >> "$MODELS_CONF"
            fi
            
            # Generate a description from the filename
            local auto_desc
            auto_desc=$(echo "$sel_file" | sed 's/\.gguf$//' | sed 's/[._-]/ /g' | sed 's/  */ /g')
            
            # Add the model entry
            echo "uncategorized|${model_id}|${repo}|${sel_file}|${size_formatted}|${auto_desc}" >> "$MODELS_CONF"
        fi
        
        local actual_size
        actual_size=$(du -h "$output_path" | cut -f1)
        print_success "Ready: $model_id ($actual_size)"
        downloaded_models+=("$model_id")
    done
    
    if [[ ${#downloaded_models[@]} -eq 0 ]]; then
        print_warning "No new models were downloaded"
        exit 0
    fi
    
    # Auto-sync to OpenCode config
    if [[ -x "$SCRIPT_DIR/sync-opencode-config.sh" ]]; then
        echo
        "$SCRIPT_DIR/sync-opencode-config.sh"
    fi
    
    echo
    echo -e "${BOLD}Models added:${NC}"
    for m in "${downloaded_models[@]}"; do
        echo "  - $m"
    done
    echo
    echo "Start server with:"
    echo "  ./start-server.sh ${downloaded_models[0]}"
    echo
    echo -e "${DIM}Models added to models.conf - will appear in future ./setup.sh runs${NC}"
    echo -e "${DIM}Edit models.conf to change category (coding/general/reasoning)${NC}"
    echo
}

# =============================================================================
# Validate models.conf Syntax
# =============================================================================

validate_models_conf() {
    echo
    echo -e "${CYAN}${BOLD}Validating models.conf${NC}"
    echo
    
    if [[ ! -f "$MODELS_CONF" ]]; then
        print_error "models.conf not found at: $MODELS_CONF"
        exit 1
    fi
    
    local errors=0
    local warnings=0
    local line_num=0
    local model_count=0
    local alias_count=0
    local whitelist_count=0
    
    while IFS= read -r line || [[ -n "$line" ]]; do
        ((++line_num))
        
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        
        # Count and validate ALIAS lines
        if [[ "$line" =~ ^ALIAS: ]]; then
            alias_count=$((alias_count + 1))
            if [[ ! "$line" =~ ^ALIAS:[^=]+=.+$ ]]; then
                echo -e "  ${RED}✗${NC} Line $line_num: Invalid ALIAS format"
                echo -e "    ${DIM}Expected: ALIAS:name=model_id${NC}"
                echo -e "    ${DIM}Got: $line${NC}"
                errors=$((errors + 1))
            fi
            continue
        fi
        
        # Count and validate WHITELIST lines
        if [[ "$line" =~ ^WHITELIST: ]]; then
            whitelist_count=$((whitelist_count + 1))
            continue
        fi
        
        # Model entries should have exactly 5 pipes (6 fields)
        local pipe_count
        pipe_count=$(echo "$line" | tr -cd '|' | wc -c)
        
        if [[ $pipe_count -ne 5 ]]; then
            echo -e "  ${RED}✗${NC} Line $line_num: Expected 5 pipes (6 fields), found $pipe_count"
            echo -e "    ${DIM}$line${NC}"
            errors=$((errors + 1))
            continue
        fi
        
        model_count=$((model_count + 1))
        
        # Parse fields
        IFS='|' read -r category model_id hf_repo gguf_file size description <<< "$line"
        
        # Trim fields
        model_id="${model_id#"${model_id%%[![:space:]]*}"}"
        model_id="${model_id%"${model_id##*[![:space:]]}"}"
        gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
        gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
        
        # Check for empty required fields
        if [[ -z "$model_id" ]]; then
            echo -e "  ${RED}✗${NC} Line $line_num: Missing model_id"
            errors=$((errors + 1))
        fi
        
        if [[ -z "$gguf_file" ]]; then
            echo -e "  ${RED}✗${NC} Line $line_num: Missing gguf_file"
            errors=$((errors + 1))
        fi
        
        # Warn about commas in description (breaks gum menus)
        if [[ "$description" == *","* ]]; then
            echo -e "  ${YELLOW}!${NC} Line $line_num: Comma in description may cause menu issues"
            echo -e "    ${DIM}Model: $model_id${NC}"
            warnings=$((warnings + 1))
        fi
        
        # Check GGUF file extension
        if [[ -n "$gguf_file" && "$gguf_file" != *.gguf ]]; then
            echo -e "  ${YELLOW}!${NC} Line $line_num: GGUF file doesn't have .gguf extension"
            echo -e "    ${DIM}File: $gguf_file${NC}"
            warnings=$((warnings + 1))
        fi
    done < "$MODELS_CONF"
    
    echo
    echo -e "  ${BOLD}Summary:${NC}"
    echo "    Models:    $model_count"
    echo "    Aliases:   $alias_count"
    echo "    Whitelist: $whitelist_count"
    echo "    Errors:    $errors"
    echo "    Warnings:  $warnings"
    echo
    
    if [[ $errors -gt 0 ]]; then
        print_error "Validation failed with $errors error(s)"
        return 1
    elif [[ $warnings -gt 0 ]]; then
        print_warning "Validation passed with $warnings warning(s)"
        return 0
    else
        print_success "Validation passed!"
        return 0
    fi
}

# =============================================================================
# Orphan Model Cleanup
# =============================================================================

cleanup_orphan_models() {
    echo
    echo -e "${CYAN}${BOLD}Orphan Model Cleanup${NC}"
    echo
    
    if [[ ! -d "$MODELS_DIR" ]]; then
        print_warning "Models directory not found: $MODELS_DIR"
        return 0
    fi
    
    # Build list of known GGUF files from models.conf
    declare -A known_files
    declare -A whitelisted_files
    
    if [[ -f "$MODELS_CONF" ]]; then
        while IFS='|' read -r category model_id hf_repo gguf_file size description || [[ -n "$category" ]]; do
            # Skip comments
            [[ "$category" =~ ^[[:space:]]*# ]] && continue
            [[ -z "$category" ]] && continue
            
            # Handle WHITELIST entries (files user wants to keep but aren't in main config)
            if [[ "$category" =~ ^WHITELIST: ]]; then
                # Format: WHITELIST: filename.gguf | reason
                local wl_file="${category#WHITELIST:}"
                wl_file="${wl_file#"${wl_file%%[![:space:]]*}"}"
                wl_file="${wl_file%"${wl_file##*[![:space:]]}"}"
                whitelisted_files["$wl_file"]=1
                continue
            fi
            
            # Skip ALIAS lines
            [[ "$category" =~ ^ALIAS: ]] && continue
            
            # Trim gguf_file
            gguf_file="${gguf_file#"${gguf_file%%[![:space:]]*}"}"
            gguf_file="${gguf_file%"${gguf_file##*[![:space:]]}"}"
            
            [[ -n "$gguf_file" ]] && known_files["$gguf_file"]=1
        done < "$MODELS_CONF"
    fi
    
    # Find orphan files
    declare -a orphan_files=()
    declare -a orphan_sizes=()
    local total_orphan_bytes=0
    
    for gguf in "$MODELS_DIR"/*.gguf; do
        [[ -f "$gguf" ]] || continue
        local filename
        filename=$(basename "$gguf")
        
        # Check if it's known or whitelisted
        if [[ -z "${known_files[$filename]:-}" && -z "${whitelisted_files[$filename]:-}" ]]; then
            orphan_files+=("$filename")
            local file_size
            file_size=$(stat -c%s "$gguf" 2>/dev/null || stat -f%z "$gguf" 2>/dev/null || echo 0)
            orphan_sizes+=("$file_size")
            total_orphan_bytes=$((total_orphan_bytes + file_size))
        fi
    done
    
    if [[ ${#orphan_files[@]} -eq 0 ]]; then
        print_success "No orphan models found - all .gguf files are in models.conf"
        echo
        return 0
    fi
    
    # Format total size
    local total_size_human
    if [[ $total_orphan_bytes -ge 1073741824 ]]; then
        total_size_human="$(echo "scale=1; $total_orphan_bytes / 1073741824" | bc 2>/dev/null || echo "?")GB"
    elif [[ $total_orphan_bytes -ge 1048576 ]]; then
        total_size_human="$(( total_orphan_bytes / 1048576 ))MB"
    else
        total_size_human="$(( total_orphan_bytes / 1024 ))KB"
    fi
    
    echo -e "  ${BOLD}Found ${#orphan_files[@]} orphan model(s) (${total_size_human} total):${NC}"
    echo
    
    for i in "${!orphan_files[@]}"; do
        local fname="${orphan_files[$i]}"
        local fsize="${orphan_sizes[$i]}"
        
        # Format size
        local size_human
        if [[ $fsize -ge 1073741824 ]]; then
            size_human="$(echo "scale=1; $fsize / 1073741824" | bc 2>/dev/null || echo "?")GB"
        elif [[ $fsize -ge 1048576 ]]; then
            size_human="$(( fsize / 1048576 ))MB"
        else
            size_human="$(( fsize / 1024 ))KB"
        fi
        
        echo -e "    ${YELLOW}○${NC} $fname ${DIM}($size_human)${NC}"
    done
    
    echo
    echo -e "${DIM}These files are in $MODELS_DIR but not listed in models.conf${NC}"
    echo
    
    local action=""
    
    if [[ "$HAS_GUM" == true ]]; then
        echo -e "${BOLD}What would you like to do?${NC}"
        echo
        action=$(gum choose --cursor-prefix="○ " --selected-prefix="◉ " \
            --cursor.foreground="212" \
            "Delete all orphan models" \
            "Select which to delete" \
            "Whitelist all (keep but don't warn)" \
            "Do nothing") || {
            print_status "Cleanup cancelled"
            return 0
        }
    else
        echo "Options:"
        echo "  1) Delete all orphan models"
        echo "  2) Whitelist all (keep but don't warn)"
        echo "  3) Do nothing"
        echo
        read -r -p "Select option [1-3]: " choice
        case "$choice" in
            1) action="Delete all orphan models" ;;
            2) action="Whitelist all (keep but don't warn)" ;;
            *) action="Do nothing" ;;
        esac
    fi
    
    case "$action" in
        "Delete all orphan models")
            echo
            echo -e "${YELLOW}${BOLD}WARNING: This will permanently delete the following files:${NC}"
            for fname in "${orphan_files[@]}"; do
                echo "  - $MODELS_DIR/$fname"
            done
            echo
            
            local confirm=""
            if [[ "$HAS_GUM" == true ]]; then
                confirm=$(gum confirm "Delete ${#orphan_files[@]} file(s) (${total_size_human})?" && echo "yes" || echo "no")
            else
                read -r -p "Are you sure? Type 'yes' to confirm: " confirm
            fi
            
            if [[ "$confirm" == "yes" ]]; then
                local deleted_count=0
                local deleted_bytes=0
                
                for i in "${!orphan_files[@]}"; do
                    local fname="${orphan_files[$i]}"
                    local fsize="${orphan_sizes[$i]}"
                    local fpath="$MODELS_DIR/$fname"
                    
                    if rm -f "$fpath"; then
                        echo -e "  ${GREEN}✓${NC} Deleted: $fname"
                        ((deleted_count++))
                        deleted_bytes=$((deleted_bytes + fsize))
                    else
                        echo -e "  ${RED}✗${NC} Failed to delete: $fname"
                    fi
                done
                
                # Format deleted size
                local deleted_human
                if [[ $deleted_bytes -ge 1073741824 ]]; then
                    deleted_human="$(echo "scale=1; $deleted_bytes / 1073741824" | bc 2>/dev/null || echo "?")GB"
                else
                    deleted_human="$(( deleted_bytes / 1048576 ))MB"
                fi
                
                echo
                print_success "Deleted $deleted_count file(s), freed $deleted_human"
            else
                print_status "Deletion cancelled"
            fi
            ;;
            
        "Select which to delete")
            if [[ "$HAS_GUM" == false ]]; then
                print_warning "Selection mode requires gum. Install with: sudo pacman -S gum"
                return 1
            fi
            
            # Build options with sizes
            local options=()
            for i in "${!orphan_files[@]}"; do
                local fname="${orphan_files[$i]}"
                local fsize="${orphan_sizes[$i]}"
                local size_human
                if [[ $fsize -ge 1073741824 ]]; then
                    size_human="$(echo "scale=1; $fsize / 1073741824" | bc 2>/dev/null || echo "?")GB"
                else
                    size_human="$(( fsize / 1048576 ))MB"
                fi
                options+=("$fname ($size_human)")
            done
            
            echo
            echo -e "${BOLD}Select files to delete (Space to toggle, Enter to confirm):${NC}"
            echo
            
            local selected
            selected=$(gum choose --no-limit \
                --cursor-prefix="○ " \
                --selected-prefix="✓ " \
                --unselected-prefix="○ " \
                --cursor.foreground="212" \
                --selected.foreground="212" \
                --height=15 \
                "${options[@]}") || {
                print_status "Selection cancelled"
                return 0
            }
            
            if [[ -z "$selected" ]]; then
                print_status "No files selected"
                return 0
            fi
            
            # Parse and delete selected files
            local deleted_count=0
            while IFS= read -r line; do
                # Extract filename from "filename (size)"
                local fname="${line%% (*}"
                local fpath="$MODELS_DIR/$fname"
                
                if [[ -f "$fpath" ]]; then
                    if rm -f "$fpath"; then
                        echo -e "  ${GREEN}✓${NC} Deleted: $fname"
                        ((deleted_count++))
                    else
                        echo -e "  ${RED}✗${NC} Failed: $fname"
                    fi
                fi
            done <<< "$selected"
            
            echo
            print_success "Deleted $deleted_count file(s)"
            ;;
            
        "Whitelist all (keep but don't warn)")
            echo
            print_status "Adding orphan models to whitelist..."
            
            # Add whitelist section if not exists
            if ! grep -q "^# WHITELIST" "$MODELS_CONF" 2>/dev/null; then
                echo >> "$MODELS_CONF"
                echo "# -----------------------------------------------------------------------------" >> "$MODELS_CONF"
                echo "# WHITELIST - Models to keep but not track in main config" >> "$MODELS_CONF"
                echo "# Format: WHITELIST: filename.gguf | reason for keeping" >> "$MODELS_CONF"
                echo "# -----------------------------------------------------------------------------" >> "$MODELS_CONF"
            fi
            
            for fname in "${orphan_files[@]}"; do
                if ! grep -q "^WHITELIST:.*$fname" "$MODELS_CONF" 2>/dev/null; then
                    echo "WHITELIST: $fname | Added by cleanup on $(date +%Y-%m-%d)" >> "$MODELS_CONF"
                    echo -e "  ${GREEN}✓${NC} Whitelisted: $fname"
                fi
            done
            
            echo
            print_success "Whitelisted ${#orphan_files[@]} model(s)"
            echo -e "${DIM}Edit models.conf to remove from whitelist or add proper entries${NC}"
            ;;
            
        *)
            print_status "No action taken"
            ;;
    esac
    
    echo
}

# =============================================================================
# Main
# =============================================================================

if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi

FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            list_models true
            exit 0
            ;;
        --list-downloaded)
            list_models false
            exit 0
            ;;
        --info)
            if [[ -z "${2:-}" ]]; then
                print_error "--info requires a model ID"
                exit 1
            fi
            show_model_info "$2"
            exit 0
            ;;
        --search)
            search_huggingface "${2:-}"
            exit 0
            ;;
        --trending)
            show_trending
            exit 0
            ;;
        --browse)
            if [[ -z "${2:-}" ]]; then
                print_error "--browse requires a HuggingFace repo (e.g., bartowski/Qwen2.5-Coder-32B-Instruct-GGUF)"
                exit 1
            fi
            browse_model_files "$2"
            exit 0
            ;;
        --add)
            if [[ -z "${2:-}" ]]; then
                print_error "--add requires a HuggingFace repo (e.g., bartowski/Codestral-22B-v0.1-GGUF)"
                exit 1
            fi
            add_model "$2" "${3:-}"
            exit 0
            ;;
        --cleanup)
            cleanup_orphan_models
            exit 0
            ;;
        --validate)
            validate_models_conf
            exit $?
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        -*)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            download_model "$1" "$FORCE"
            exit 0
            ;;
    esac
done
