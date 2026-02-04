#!/usr/bin/env bash
# =============================================================================
# RAG Search CLI
# Search RAG collections for similar documents
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
    echo "Search a RAG collection for documents similar to your query."
    echo
    echo "Options:"
    echo "  -c, --collection NAME   Collection to search (required)"
    echo "  -k, --top-k NUM         Number of results (default: 5)"
    echo "  --all                   Search all collections"
    echo "  --list                  List all collections and their stats"
    echo "  --json                  Output raw JSON"
    echo "  -h, --help              Show this help"
    echo
    echo "Examples:"
    echo "  $0 --collection coding \"how does authentication work\""
    echo "  $0 --collection notes -k 10 \"meeting notes about project X\""
    echo "  $0 --all \"error handling patterns\""
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
TOP_K=5
SEARCH_ALL=false
LIST_COLLECTIONS=false
OUTPUT_JSON=false
QUERY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--collection)
            COLLECTION="$2"
            shift 2
            ;;
        -k|--top-k)
            TOP_K="$2"
            shift 2
            ;;
        --all)
            SEARCH_ALL=true
            shift
            ;;
        --list)
            LIST_COLLECTIONS=true
            shift
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

if [[ -z "$QUERY" ]]; then
    print_error "Search query is required"
    show_help
    exit 1
fi

if [[ -z "$COLLECTION" && "$SEARCH_ALL" == false ]]; then
    print_error "Collection name is required (use --collection NAME or --all)"
    exit 1
fi

check_server

# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------

if [[ "$SEARCH_ALL" == true ]]; then
    # Search all collections
    payload=$(jq -n --arg q "$QUERY" --argjson k "$TOP_K" \
        '{query: $q, k: $k}')
    
    response=$(curl -sf -X POST "$RAG_URL/search/all" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>&1) || {
        print_error "Search failed"
        echo "$response"
        exit 1
    }
    
    if [[ "$OUTPUT_JSON" == true ]]; then
        echo "$response" | jq .
        exit 0
    fi
    
    # Format results
    if command -v jq &>/dev/null; then
        collections=$(echo "$response" | jq -r 'keys[]')
        
        if [[ -z "$collections" ]]; then
            print_warning "No results found"
            exit 0
        fi
        
        for col in $collections; do
            print_header "Collection: $col"
            echo
            
            echo "$response" | jq -r --arg c "$col" '.[$c][] | 
                "  [\(.similarity)] \(.filename)\n  \(.text[0:200])...\n"'
        done
    else
        echo "$response"
    fi
else
    # Search single collection
    payload=$(jq -n --arg c "$COLLECTION" --arg q "$QUERY" --argjson k "$TOP_K" \
        '{collection: $c, query: $q, k: $k}')
    
    response=$(curl -sf -X POST "$RAG_URL/search" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>&1) || {
        print_error "Search failed"
        echo "$response"
        exit 1
    }
    
    if [[ "$OUTPUT_JSON" == true ]]; then
        echo "$response" | jq .
        exit 0
    fi
    
    # Format results
    if command -v jq &>/dev/null; then
        count=$(echo "$response" | jq 'length')
        
        if [[ "$count" == "0" ]]; then
            print_warning "No results found in collection '$COLLECTION'"
            exit 0
        fi
        
        print_header "Search Results ($count matches)"
        echo
        
        echo "$response" | jq -r '.[] | 
            "  [\(.similarity)] \(.filename)\n  Source: \(.source)\n  \(.text[0:300])...\n"'
    else
        echo "$response"
    fi
fi
