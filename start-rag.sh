#!/usr/bin/env bash
# =============================================================================
# RAG Server Start Script
# Starts the FastAPI RAG server on port 8081
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common library
source "$SCRIPT_DIR/lib/common.sh"

# RAG-specific paths
RAG_DIR="$SCRIPT_DIR/rag"
RAG_VENV="$RAG_DIR/.venv"
RAG_PORT="${RAG_PORT:-8081}"
RAG_LOG="$RAG_DIR/data/server.log"

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo
    echo "Start the RAG server (FastAPI on port $RAG_PORT)"
    echo
    echo "Options:"
    echo "  -p, --port PORT    Port to run on (default: $RAG_PORT)"
    echo "  -b, --background   Run in background"
    echo "  --stop             Stop the running RAG server"
    echo "  --status           Check if RAG server is running"
    echo "  -h, --help         Show this help"
    echo
}

# -----------------------------------------------------------------------------
# Parse Arguments
# -----------------------------------------------------------------------------

BACKGROUND=false
STOP_SERVER=false
CHECK_STATUS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--port)
            RAG_PORT="$2"
            shift 2
            ;;
        -b|--background)
            BACKGROUND=true
            shift
            ;;
        --stop)
            STOP_SERVER=true
            shift
            ;;
        --status)
            CHECK_STATUS=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Stop Server
# -----------------------------------------------------------------------------

if [[ "$STOP_SERVER" == true ]]; then
    pid=$(lsof -ti:$RAG_PORT 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        kill "$pid" 2>/dev/null || true
        print_success "RAG server stopped (PID: $pid)"
    else
        print_status "RAG server is not running"
    fi
    exit 0
fi

# -----------------------------------------------------------------------------
# Check Status
# -----------------------------------------------------------------------------

if [[ "$CHECK_STATUS" == true ]]; then
    if curl -sf "http://127.0.0.1:$RAG_PORT/health" &>/dev/null; then
        print_success "RAG server is running on port $RAG_PORT"
        curl -s "http://127.0.0.1:$RAG_PORT/health" | jq . 2>/dev/null || true
    else
        print_status "RAG server is not running"
    fi
    exit 0
fi

# -----------------------------------------------------------------------------
# Check Prerequisites
# -----------------------------------------------------------------------------

if [[ ! -d "$RAG_VENV" ]]; then
    print_error "RAG virtual environment not found"
    echo "Run './setup-rag.sh' first to set up the RAG system"
    exit 1
fi

if [[ ! -f "$RAG_VENV/bin/python" ]]; then
    print_error "Python not found in virtual environment"
    echo "Run './setup-rag.sh' to recreate the environment"
    exit 1
fi

# Check if port is already in use
existing_pid=$(lsof -ti:$RAG_PORT 2>/dev/null || true)
if [[ -n "$existing_pid" ]]; then
    # Check if it's our RAG server
    if curl -sf "http://127.0.0.1:$RAG_PORT/health" 2>/dev/null | grep -q "rag-server"; then
        print_status "RAG server is already running on port $RAG_PORT"
        exit 0
    else
        print_error "Port $RAG_PORT is already in use by another process (PID: $existing_pid)"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Start Server
# -----------------------------------------------------------------------------

# Ensure data directory exists
mkdir -p "$RAG_DIR/data"

if [[ "$BACKGROUND" == true ]]; then
    print_status "Starting RAG server in background on port $RAG_PORT..."
    
    nohup "$RAG_VENV/bin/python" -m uvicorn rag.server:app \
        --host 127.0.0.1 \
        --port "$RAG_PORT" \
        --log-level info \
        > "$RAG_LOG" 2>&1 &
    
    server_pid=$!
    
    # Wait for server to be ready
    for _ in {1..30}; do
        if curl -sf "http://127.0.0.1:$RAG_PORT/health" &>/dev/null; then
            print_success "RAG server started (PID: $server_pid)"
            echo -e "  ${BOLD}URL:${NC} http://127.0.0.1:$RAG_PORT"
            echo -e "  ${BOLD}Log:${NC} $RAG_LOG"
            echo -e "  ${BOLD}API docs:${NC} http://127.0.0.1:$RAG_PORT/docs"
            exit 0
        fi
        sleep 0.5
    done
    
    print_error "Server failed to start within 15 seconds"
    echo "Check log: $RAG_LOG"
    tail -10 "$RAG_LOG" 2>/dev/null || true
    exit 1
else
    print_banner "RAG Server"
    echo -e "${BOLD}Starting server on port $RAG_PORT${NC}"
    echo -e "${DIM}Press Ctrl+C to stop${NC}"
    echo
    
    exec "$RAG_VENV/bin/python" -m uvicorn rag.server:app \
        --host 127.0.0.1 \
        --port "$RAG_PORT" \
        --log-level info
fi
