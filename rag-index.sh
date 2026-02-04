#!/usr/bin/env bash
# =============================================================================
# RAG Index CLI
# Index files and directories into RAG collections
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
source "$SCRIPT_DIR/lib/common.sh"

RAG_PORT="${RAG_PORT:-8081}"
RAG_URL="http://127.0.0.1:$RAG_PORT"

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

show_help() {
    echo "Usage: $0 [OPTIONS] PATH [PATH...]"
    echo
    echo "Index files and directories into a RAG collection."
    echo
    echo "Options:"
    echo "  -c, --collection NAME   Collection to index to (required)"
    echo "  --clear                 Clear collection before indexing"
    echo "  --list                  List all collections and their stats"
    echo "  -h, --help              Show this help"
    echo
    echo "Examples:"
    echo "  $0 --collection coding ~/projects/my-app/"
    echo "  $0 --collection notes ~/notes/work.md ~/notes/personal.md"
    echo "  $0 --clear --collection coding ~/projects/my-app/"
    echo "  $0 --list"
    echo
}

# -----------------------------------------------------------------------------
# Check Server
# -----------------------------------------------------------------------------

check_server() {
    if ! curl -sf "$RAG_URL/health" &>/dev/null; then
        print_error "RAG server is not running"
        echo "Start it with: ./start-rag.sh"
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Parse Arguments
# -----------------------------------------------------------------------------

COLLECTION=""
CLEAR_FIRST=false
LIST_COLLECTIONS=false
PATHS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--collection)
            COLLECTION="$2"
            shift 2
            ;;
        --clear)
            CLEAR_FIRST=true
            shift
            ;;
        --list)
            LIST_COLLECTIONS=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            PATHS+=("$1")
            shift
            ;;
    esac
done

# -----------------------------------------------------------------------------
# List Collections
# -----------------------------------------------------------------------------

if [[ "$LIST_COLLECTIONS" == true ]]; then
    check_server
    
    print_header "RAG Collections"
    echo
    
    response=$(curl -sf "$RAG_URL/collections")
    
    if command -v jq &>/dev/null; then
        echo "$response" | jq -r '.[] | "  \(.name): \(.document_count) chunks - \(.description)"'
    else
        echo "$response"
    fi
    echo
    exit 0
fi

# -----------------------------------------------------------------------------
# Validate Arguments
# -----------------------------------------------------------------------------

if [[ -z "$COLLECTION" ]]; then
    print_error "Collection name is required"
    echo "Use --collection NAME to specify the target collection"
    echo "Use --list to see available collections"
    exit 1
fi

if [[ ${#PATHS[@]} -eq 0 && "$CLEAR_FIRST" == false ]]; then
    print_error "At least one path is required"
    show_help
    exit 1
fi

check_server

# -----------------------------------------------------------------------------
# Clear Collection (if requested)
# -----------------------------------------------------------------------------

if [[ "$CLEAR_FIRST" == true ]]; then
    print_status "Clearing collection: $COLLECTION"
    
    response=$(curl -sf -X DELETE "$RAG_URL/collections/$COLLECTION" 2>&1) || {
        print_error "Failed to clear collection"
        echo "$response"
        exit 1
    }
    
    print_success "Collection cleared"
    
    # If no paths provided, just clear and exit
    if [[ ${#PATHS[@]} -eq 0 ]]; then
        exit 0
    fi
fi

# -----------------------------------------------------------------------------
# Index Files
# -----------------------------------------------------------------------------

# Convert paths to absolute paths
ABS_PATHS=()
for path in "${PATHS[@]}"; do
    abs_path=$(realpath "$path" 2>/dev/null || echo "$path")
    if [[ ! -e "$abs_path" ]]; then
        print_warning "Path does not exist: $path"
        continue
    fi
    ABS_PATHS+=("$abs_path")
done

if [[ ${#ABS_PATHS[@]} -eq 0 ]]; then
    print_error "No valid paths to index"
    exit 1
fi

print_header "Indexing to Collection: $COLLECTION"
echo

for path in "${ABS_PATHS[@]}"; do
    echo -e "  ${BLUE}○${NC} $path"
done
echo

# Build JSON payload
paths_json=$(printf '%s\n' "${ABS_PATHS[@]}" | jq -R . | jq -s .)
payload=$(jq -n --arg col "$COLLECTION" --argjson paths "$paths_json" \
    '{collection: $col, paths: $paths}')

start_spinner "Indexing documents"

response=$(curl -sf -X POST "$RAG_URL/index" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1) || {
    stop_spinner false "Indexing failed"
    echo "$response"
    exit 1
}

stop_spinner true "Indexing complete"

# Show results
if command -v jq &>/dev/null; then
    files_found=$(echo "$response" | jq -r '.files_found // 0')
    files_processed=$(echo "$response" | jq -r '.files_processed // 0')
    chunks=$(echo "$response" | jq -r '.chunks_indexed // 0')
    message=$(echo "$response" | jq -r '.message // ""')
    
    echo
    echo -e "  ${BOLD}Files found:${NC}     $files_found"
    echo -e "  ${BOLD}Files processed:${NC} $files_processed"
    echo -e "  ${BOLD}Chunks indexed:${NC}  $chunks"
    echo
    
    if [[ -n "$message" ]]; then
        print_success "$message"
    fi
else
    echo "$response"
fi
