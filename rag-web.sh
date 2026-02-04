#!/usr/bin/env bash
# =============================================================================
# RAG Web Search CLI
# Search the web via SearXNG
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
    echo "Usage: $0 [OPTIONS] QUERY"
    echo
    echo "Search the web via SearXNG metasearch engine."
    echo
    echo "Options:"
    echo "  -k, --top-k NUM    Number of results (default: 5)"
    echo "  --json             Output raw JSON"
    echo "  -h, --help         Show this help"
    echo
    echo "Examples:"
    echo "  $0 \"python async await tutorial\""
    echo "  $0 -k 10 \"llama.cpp ROCm setup\""
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

TOP_K=5
OUTPUT_JSON=false
QUERY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -k|--top-k)
            TOP_K="$2"
            shift 2
            ;;
        --json)
            OUTPUT_JSON=true
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
            QUERY="$1"
            shift
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Validate Arguments
# -----------------------------------------------------------------------------

if [[ -z "$QUERY" ]]; then
    print_error "Search query is required"
    show_help
    exit 1
fi

check_server

# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------

payload=$(jq -n --arg q "$QUERY" --argjson k "$TOP_K" \
    '{query: $q, k: $k}')

start_spinner "Searching the web"

response=$(curl -sf -X POST "$RAG_URL/web" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>&1) || {
    stop_spinner false "Search failed"
    echo "$response"
    exit 1
}

stop_spinner

# Check for errors
if echo "$response" | jq -e '.[0].error' &>/dev/null; then
    error_msg=$(echo "$response" | jq -r '.[0].error')
    print_error "$error_msg"
    echo
    echo "Make sure SearXNG is running:"
    echo "  docker compose up -d searxng"
    exit 1
fi

if [[ "$OUTPUT_JSON" == true ]]; then
    echo "$response" | jq .
    exit 0
fi

# Format results
if command -v jq &>/dev/null; then
    count=$(echo "$response" | jq 'length')
    
    if [[ "$count" == "0" ]]; then
        print_warning "No results found"
        exit 0
    fi
    
    print_header "Web Search Results ($count)"
    echo
    
    echo "$response" | jq -r '.[] | 
        "  \(.title)\n  \u001b[34m\(.url)\u001b[0m\n  \(.snippet)\n"'
else
    echo "$response"
fi
