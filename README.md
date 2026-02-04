# llama-cpp-setup

Run local LLMs with GPU acceleration using llama.cpp.

## Platform Support

| Platform | GPU | Backend |
|----------|-----|---------|
| **Linux** | NVIDIA (CUDA) | llama.cpp (CUDA) |
| **Linux** | AMD (ROCm) | llama.cpp (ROCm/HIP) |
| **macOS** | Apple Silicon (Metal) | llama.cpp (Metal) |

## Quick Start

### Linux (NVIDIA or AMD GPU)

```bash
# 1. Clone the repository
git clone https://github.com/oopsallbugs/llama-cpp-setup.git
cd llama-cpp-setup

# 2. Run setup (auto-detects GPU, builds llama.cpp, downloads models)
./setup.sh

# 3. Start the server
./start-server.sh qwen3

# 4. Use with OpenCode
cd /your/project
opencode
# Use /models to select llama.cpp provider
```

### macOS (Apple Silicon)

```bash
# 1. Clone the repository
git clone https://github.com/oopsallbugs/llama-cpp-setup.git
cd llama-cpp-setup

# 2. Run setup (builds llama.cpp with Metal, downloads models)
./setup-macos.sh

# 3. Start the server
./start-server.sh qwen3

# 4. Use with OpenCode
cd /your/project
opencode
# Use /models to select llama.cpp provider
```

### OpenHands (Autonomous AI Agent)

After setting up llama.cpp, you can also run [OpenHands](https://github.com/All-Hands-AI/OpenHands) for autonomous AI coding tasks:

```bash
# Start OpenHands (connects to your llama.cpp server)
./start-openhands.sh

# Open http://localhost:3000
```

See [docs/OPENHANDS.md](docs/OPENHANDS.md) for remote LLM server setup and more options.

## Requirements

### Linux with NVIDIA GPU

| Requirement | Notes |
|-------------|-------|
| **Linux** | Any modern distribution |
| **NVIDIA GPU** | GTX 10xx, RTX 20xx/30xx/40xx/50xx series |
| **NVIDIA Driver** | `nvidia-smi` must work |
| **CUDA Toolkit** | `nvcc --version` must be available |
| **Build tools** | `git`, `cmake`, `make` or `ninja` |
| **gum** | Required for interactive mode ([install](https://github.com/charmbracelet/gum#installation)) |
| **curl** | For model downloads (or `huggingface-cli`) |
| **Disk space** | 20-100GB depending on model choices |
| **GPU Memory (VRAM)** | 8GB minimum, 16-24GB+ recommended |

### Linux with AMD GPU

| Requirement | Notes |
|-------------|-------|
| **Linux** | ROCm only supports Linux |
| **AMD GPU** | RDNA1, RDNA2, or RDNA3 (RX 5000/6000/7000 series) |
| **ROCm/HIP** | `rocminfo` and `hipcc` must be available |
| **Build tools** | `git`, `cmake`, `make` or `ninja` |
| **gum** | Required for interactive mode ([install](https://github.com/charmbracelet/gum#installation)) |
| **curl** | For model downloads (or `huggingface-cli`) |
| **Disk space** | 20-100GB depending on model choices |
| **GPU Memory (VRAM)** | 8GB minimum, 16-24GB recommended |

### macOS with Apple Silicon

| Requirement | Notes |
|-------------|-------|
| **macOS 11.0+** | Big Sur or later |
| **Apple Silicon** | M1, M2, M3, M4 (any variant) |
| **Xcode CLI Tools** | `xcode-select --install` |
| **Homebrew** | For installing dependencies |
| **Build tools** | `git`, `cmake` (via Homebrew) |
| **gum** | Required for interactive mode (`brew install gum`) |
| **curl** | For model downloads (or `huggingface-cli`) |
| **Disk space** | 20-100GB depending on model choices |
| **Unified Memory** | 16GB minimum, 32GB+ recommended |

> **Note:** Intel Macs can run llama.cpp but without Metal GPU acceleration. Performance will be significantly slower.

### Supported GPUs

#### NVIDIA (Linux)

| GPU Family | Examples | Notes |
|------------|----------|-------|
| RTX 50xx | RTX 5090, 5080, 5070 Ti | Blackwell, newest |
| RTX 40xx | RTX 4090, 4080, 4070 Ti | Ada Lovelace |
| RTX 30xx | RTX 3090, 3080, 3070 | Ampere |
| RTX 20xx | RTX 2080 Ti, 2080, 2070 | Turing |
| GTX 16xx | GTX 1660 Ti, 1650 | Turing (no RT cores) |
| GTX 10xx | GTX 1080 Ti, 1080, 1070 | Pascal |

#### AMD (Linux)

| GPU | Architecture | Target |
|-----|--------------|--------|
| RX 7900 XTX/XT/GRE | RDNA3 | gfx1100 |
| RX 7800/7700 XT | RDNA3 | gfx1101 |
| RX 7600 | RDNA3 | gfx1102 |
| RX 6900/6800 XT | RDNA2 | gfx1030 |
| RX 6700 XT | RDNA2 | gfx1031 |
| RX 6600 XT/6600 | RDNA2 | gfx1032 |
| RX 5700 XT/5700 | RDNA1 | gfx1010 |

#### Apple Silicon (macOS)

| Chip | Notes |
|------|-------|
| M1 / M1 Pro / M1 Max / M1 Ultra | Fully supported |
| M2 / M2 Pro / M2 Max / M2 Ultra | Fully supported |
| M3 / M3 Pro / M3 Max | Fully supported |
| M4 / M4 Pro / M4 Max | Fully supported |

## Project Structure

```text
llama-cpp-setup/
├── setup.sh                  # llama.cpp setup (Linux - auto-detects NVIDIA/AMD)
├── setup-macos.sh            # llama.cpp setup (macOS/Metal)
├── setup-rag.sh              # RAG system setup
├── start-server.sh           # Start llama-server (cross-platform)
├── start-openhands.sh        # Start OpenHands AI assistant
├── start-rag.sh              # Start RAG server standalone
├── download-model.sh         # Download models from HuggingFace
├── sync-opencode.sh          # Sync models and agents to OpenCode
├── uninstall.sh              # Clean removal
├── rag-index.sh              # Index documents to RAG collections
├── rag-search.sh             # Search RAG collections
├── rag-web.sh                # Web search via SearXNG
├── docker-compose.yml        # SearXNG container definition
├── models.conf               # GGUF model definitions with context limits
├── .env.example              # Server configuration example
│
├── openhands/                # OpenHands integration
│   └── docker-compose.yml    # OpenHands container definition
│
├── rag/                      # RAG subsystem
│   ├── requirements.txt      # Python dependencies
│   ├── collections.yml       # Collection definitions
│   ├── config.py             # Configuration
│   ├── embeddings.py         # Embedding model wrapper
│   ├── indexer.py            # Document chunking and indexing
│   ├── retriever.py          # Vector search
│   ├── web_search.py         # SearXNG client
│   ├── server.py             # FastAPI application
│   └── searxng/              # SearXNG configuration
│
├── agent/                    # OpenCode agent templates
│   ├── AGENTS.md             # System prompt template (copied to ~/.config/opencode/)
│   ├── plan.md               # Read-only planning agent
│   ├── review.md             # Code review agent
│   └── debug.md              # Debugging agent
│
├── docs/                     # Documentation
│   └── OPENHANDS.md          # OpenHands integration guide
│
├── lib/
│   └── common.sh             # Shared functions for setup scripts
│
├── llama.cpp/                # Cloned llama.cpp repo (created by setup)
└── models/                   # Downloaded GGUF files (created by setup)
```

## Why llama.cpp?

llama.cpp's native server handles tool calling correctly, making it the best choice for:
- OpenCode and other AI coding assistants
- Agentic workflows requiring function calling
- Any application using the OpenAI API format

The llama.cpp server provides an OpenAI-compatible API at `http://localhost:8080/v1`. This may work with other coding assistants (Continue, Cursor, Aider, etc.) but these configurations are untested. Contributions welcome!

## Scripts Reference

| Script | Platform | Description |
|--------|----------|-------------|
| `setup.sh` | Linux | Build llama.cpp (auto-detects NVIDIA/AMD), download models |
| `setup-macos.sh` | macOS | Build llama.cpp with Metal, download models |
| `setup-rag.sh` | Both | Set up RAG system (venv, embeddings, SearXNG) |
| `start-server.sh` | Both | Start llama-server with a model |
| `start-openhands.sh` | Both | Start OpenHands AI assistant (Docker) |
| `start-rag.sh` | Both | Start RAG server standalone |
| `download-model.sh` | Both | Download individual GGUF models |
| `sync-opencode.sh` | Both | Sync models and agents to OpenCode |
| `rag-index.sh` | Both | Index files to RAG collections |
| `rag-search.sh` | Both | Search RAG collections |
| `rag-web.sh` | Both | Web search via SearXNG |
| `uninstall.sh` | Both | Remove llama.cpp build, models, config |

## Vision Models

Vision models (VLMs) can process images alongside text. These are useful for:

- **Frigate NVR** - AI-powered camera event descriptions
- **Image analysis** - Describing, captioning, or analyzing images
- **Document understanding** - Reading text from images

### Vision Model Setup

Vision models require an additional "mmproj" (multimodal projector) file. The download script automatically prompts you to download mmproj files when downloading a vision model:

```bash
# Download vision model - will prompt for mmproj file selection
./download-model.sh qwen3vl-8b-q4km

# Add a new vision model from HuggingFace - also prompts for mmproj
./download-model.sh --add Qwen/Qwen3-VL-8B-Instruct-GGUF

# Skip mmproj download (download model only)
./download-model.sh --no-mmproj qwen3vl-8b-q4km
```

When prompted, select an mmproj file:
- **F16** - Higher quality (recommended)
- **Q8_0** - Smaller size

### Starting Vision Server

```bash
# Auto-detects mmproj file
./start-server.sh vision
```

For Frigate or other integrations, configure `LLAMA_PORT=11434` and `LLAMA_HOST=0.0.0.0` in your `.env` file.

### Frigate Integration

Configure Frigate to use the local vision model via OpenAI-compatible API:

```yaml
# Frigate config.yaml
genai:
  enabled: true
  provider: openai
  base_url: http://your-server-ip:11434/v1
  model: qwen3vl-8b-q4km
  prompt: "Describe what you see in this image."
```

## Usage Examples

### Start Server

```bash
# Start with a model alias
./start-server.sh qwen3

# Start with specific model
./start-server.sh qwen3-30b-q4km

# Use second GPU (for multi-GPU systems)
./start-server.sh --gpu 1 qwen3-30b-q4km

# List available models
./start-server.sh --list

# Check server health
./start-server.sh --health
```

### Download Models

```bash
# List available models
./download-model.sh --list

# Download a specific model
./download-model.sh qwen3-30b-q4km

# Download vision model (prompts for mmproj file)
./download-model.sh qwen3vl-8b-q4km

# Download vision model without mmproj
./download-model.sh --no-mmproj qwen3vl-8b-q4km

# Search HuggingFace
./download-model.sh --search "qwen gguf"
```

### Setup Options

```bash
# Linux
./setup.sh                    # Interactive setup
./setup.sh --status           # Check current status
./setup.sh --update           # Update llama.cpp
./setup.sh --fix-permissions  # Fix GPU permissions
./setup.sh --verify           # Verify downloaded models
./setup.sh --reset-agents     # Reset ~/.config/opencode agents to defaults
./setup.sh --skip-build       # Skip building llama.cpp
./setup.sh --skip-models      # Skip model selection
./setup.sh --force-rebuild    # Force rebuild even if exists
./setup.sh --force-env        # Regenerate .env file
./setup.sh --non-interactive  # Automated setup

# macOS (same options, different script)
./setup-macos.sh              # Interactive setup
./setup-macos.sh --status     # Check current status
./setup-macos.sh --update     # Update llama.cpp
./setup-macos.sh --verify     # Verify downloaded models
./setup-macos.sh --reset-agents  # Reset ~/.config/opencode agents to defaults
```

## Troubleshooting

### Linux: NVIDIA Issues

```bash
# Check NVIDIA driver
nvidia-smi

# Check CUDA installation
nvcc --version

# If nvcc not found, install CUDA toolkit:
# Arch: sudo pacman -S cuda
# Ubuntu: sudo apt install nvidia-cuda-toolkit
```

### Linux: AMD GPU Permission Denied

```bash
./setup.sh --fix-permissions
# Then log out and back in
```

### Linux: AMD ROCm Issues

```bash
# Check ROCm installation
rocminfo
HSA_OVERRIDE_GFX_VERSION=11.0.0 rocminfo

# Check HIP
hipconfig --version
```

### macOS: Xcode CLI Tools

```bash
# Install Xcode Command Line Tools
xcode-select --install

# Verify installation
xcode-select -p
```

### Server Won't Start

```bash
# Check status
./setup.sh --status        # Linux
./setup-macos.sh --status  # macOS

# Verify models
./setup.sh --verify        # Linux
./setup-macos.sh --verify  # macOS
```

### Out of Memory

1. Use a smaller model: `./start-server.sh qwen3-8b-q4km`
2. Reduce context in `models.conf` (field 7) for the model
3. Use a more aggressive quantization (e.g., Q3_K_M instead of Q4_K_M)

### Tool Calls Not Working

1. Ensure you're using llama.cpp provider in OpenCode
2. Verify server is running: `curl http://127.0.0.1:8080/health`
3. Use a model that supports tool calling (Qwen3, Qwen2.5-Coder recommended)

## Configuration Files

| File | Description |
|------|-------------|
| `models.conf` | Model definitions and per-model settings (context/output limits) |
| `agent/AGENTS.md` | OpenCode system prompt template (copied to ~/.config/opencode/) |
| `agent/*.md` | Custom agent templates (plan, review, debug) |
| `.env` | Server/hardware configuration (generated by setup) |
| `.env.example` | Server configuration example |
| `lib/common.sh` | Shared functions for setup scripts |

## OpenCode Optimization

This repository includes several features to improve local model performance with OpenCode.

### AGENTS.md (System Prompt)

The `agent/AGENTS.md` file provides instructions to the model for better behavior:

- **Tool usage patterns** - When to use Read, Edit, Glob, Grep, Bash, Task
- **Error recovery** - How to handle failed operations
- **Context efficiency** - Tips for working within limited context windows
- **Model-specific guidance** - Tips for reasoning vs coding models

The setup script copies this to `~/.config/opencode/AGENTS.md`. Reset to default with:

```bash
./setup.sh --reset-agents
```

### Custom Agents

The `agent/` directory contains specialized agent templates that are automatically synced during setup:

| Agent | Mode | Description |
|-------|------|-------------|
| `plan.md` | Primary | Read-only analysis and planning (no edits) |
| `review.md` | Subagent | Code review with quality/security focus |
| `debug.md` | Subagent | Systematic debugging and issue investigation |

Setup syncs these files to:
- `~/.config/opencode/AGENTS.md` - Main system prompt
- `~/.config/opencode/agent/plan.md` - Planning agent
- `~/.config/opencode/agent/review.md` - Review agent  
- `~/.config/opencode/agent/debug.md` - Debug agent

To reset all agent files to defaults:

```bash
./setup.sh --reset-agents
```

In OpenCode:
- **Tab** key to switch to Plan mode
- **@review** to invoke the review agent
- **@debug** to invoke the debug agent

### Instructions Config

The generated `opencode.json` includes an `instructions` field that tells OpenCode to include project documentation in the context:

```json
{
  "instructions": [
    "CONTRIBUTING.md",
    "docs/*.md"
  ]
}
```

Edit this to include your project's relevant documentation files.

### Temperature Settings

Temperature controls response randomness. OpenCode supports per-agent temperature configuration:

| Temperature | Best For | Notes |
|-------------|----------|-------|
| 0.0 - 0.2 | Code analysis, planning | Deterministic, focused |
| 0.3 - 0.5 | General coding | Balanced (default for most models) |
| 0.55 | Qwen models | Default for Qwen series |
| 0.6 - 1.0 | Brainstorming | More creative, varied |

Configure in agent files:

```yaml
---
temperature: 0.1
---
```

Or in `opencode.json`:

```json
{
  "agent": {
    "plan": {
      "temperature": 0.1
    }
  }
}
```

## RAG Support

The project includes an optional RAG (Retrieval-Augmented Generation) system for document search and web search capabilities.

### RAG Features

- **Document indexing** - Index code and documents into searchable collections
- **Semantic search** - Find relevant documents using vector similarity
- **Web search** - Search the web via SearXNG metasearch engine
- **Auto-start** - RAG server starts automatically with llama.cpp (optional)

### RAG Setup

```bash
# One-time setup (creates venv, downloads embedding model, starts SearXNG)
./setup-rag.sh
```

### Using RAG

```bash
# Start llama.cpp with RAG (default behavior after setup)
./start-server.sh qwen3

# Start without RAG
./start-server.sh --no-rag qwen3

# Or disable in .env: AUTO_START_RAG_SERVER=false

# Index documents to a collection
./rag-index.sh --collection coding ~/projects/my-app/
./rag-index.sh --collection notes ~/notes/

# Search your documents
./rag-search.sh --collection coding "how does authentication work"

# Search the web
./rag-web.sh "python async await tutorial"

# List collections
./rag-search.sh --list
```

### RAG Architecture

| Component | Port | Description |
|-----------|------|-------------|
| RAG Server | 8081 | FastAPI server for indexing and search |
| SearXNG | 8888 | Metasearch engine for web search (Docker) |
| LanceDB | - | Vector database (embedded) |
| nomic-embed-text | - | Embedding model (CPU, ~500MB RAM) |

### Collections

Documents are organized into collections. Default collections:

- **coding** - Code and technical documentation (`.py`, `.js`, `.ts`, `.md`, etc.)
- **notes** - General notes (`.md`, `.txt`, `.org`)

Add custom collections in `rag/collections.yml`:

```yaml
collections:
  work:
    description: "Work projects"
    file_types: [".py", ".md", ".txt"]
```

### RAG API Endpoints

The RAG server exposes a REST API at `http://127.0.0.1:8081`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/collections` | GET | List collections with stats |
| `/collections/{name}` | DELETE | Clear a collection |
| `/index` | POST | Index files to a collection |
| `/search` | POST | Search a collection |
| `/search/all` | POST | Search all collections |
| `/web` | POST | Web search via SearXNG |

## Links

- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [OpenCode](https://opencode.ai)
- [OpenHands](https://github.com/All-Hands-AI/OpenHands)
- [HuggingFace GGUF Models](https://huggingface.co/models?sort=trending&search=gguf)
- [NVIDIA CUDA](https://developer.nvidia.com/cuda-downloads)
- [ROCm Documentation](https://rocm.docs.amd.com)
- [Metal Performance Shaders](https://developer.apple.com/metal/)

## License

MIT
