# Local LLM Setup

Run local LLMs with GPU acceleration. This repository provides two backends:

| Backend | Best For | Tool Calling | Setup Complexity |
|---------|----------|--------------|------------------|
| **llama.cpp** (recommended) | AI coding assistants, agentic workflows | Excellent | Medium |
| **Ollama** | Simple chat, quick experiments | Limited | Easy |

## Platform Support

| Platform | GPU | Backend |
|----------|-----|---------|
| **Linux** | AMD (ROCm) | llama.cpp, Ollama |
| **macOS** | Apple Silicon (Metal) | llama.cpp, Ollama |

## Quick Start

### Linux (AMD GPU)

```bash
# 1. Clone the repository
git clone https://github.com/oopsallbugs/local-llm-rocm.git
cd local-llm-rocm

# 2. Run setup (builds llama.cpp with ROCm, downloads models)
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
git clone https://github.com/oopsallbugs/local-llm-rocm.git
cd local-llm-rocm

# 2. Run setup (builds llama.cpp with Metal, downloads models)
./setup-macos.sh

# 3. Start the server
./start-server.sh qwen3

# 4. Use with OpenCode
cd /your/project
opencode
# Use /models to select llama.cpp provider
```

## Alternative: Ollama

For simpler use cases (chat, experimentation), Ollama offers an easier setup experience. See [ollama/README.md](ollama/README.md).

```bash
cd ollama
./setup.sh        # Linux with Docker
./setup-macos.sh  # macOS with Homebrew
```

## Requirements

### Linux with AMD GPU

| Requirement | Notes |
|-------------|-------|
| **Linux** | ROCm only supports Linux |
| **AMD GPU** | RDNA1, RDNA2, or RDNA3 (RX 5000/6000/7000 series) |
| **ROCm/HIP** | `rocminfo` and `hipcc` must be available |
| **Disk space** | 20-100GB depending on model choices |
| **GPU Memory (VRAM)** | 8GB minimum, 16-24GB recommended |

### macOS with Apple Silicon

| Requirement | Notes |
|-------------|-------|
| **macOS 11.0+** | Big Sur or later |
| **Apple Silicon** | M1, M2, M3, M4 (any variant) |
| **Xcode CLI Tools** | `xcode-select --install` |
| **Homebrew** | For cmake and gum |
| **Disk space** | 20-100GB depending on model choices |
| **Unified Memory** | 16GB minimum, 32GB+ recommended |

> **Note:** Intel Macs can run llama.cpp but without Metal GPU acceleration. Performance will be significantly slower.

### Supported GPUs

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
local-llm-rocm/
├── setup.sh                  # llama.cpp setup (Linux/ROCm)
├── setup-macos.sh            # llama.cpp setup (macOS/Metal)
├── start-server.sh           # Start llama-server (cross-platform)
├── download-model.sh         # Download models from HuggingFace
├── sync-opencode.sh          # Sync models and agents to OpenCode
├── uninstall.sh              # Clean removal
├── models.conf               # GGUF model definitions with context limits
├── .env.example              # Configuration template
│
├── agent/                    # OpenCode agent templates
│   ├── AGENTS.md             # System prompt template (copied to ~/.config/opencode/)
│   ├── plan.md               # Read-only planning agent
│   ├── review.md             # Code review agent
│   └── debug.md              # Debugging agent
│
├── lib/
│   └── common.sh             # Shared functions for setup scripts
│
├── ollama/                   # Alternative: Ollama backend
│   ├── README.md             # Ollama-specific documentation
│   ├── setup.sh              # Linux setup (Docker)
│   ├── setup-macos.sh        # macOS setup (Homebrew)
│   └── ...
│
├── llama.cpp/                # Cloned llama.cpp repo (created by setup)
└── models/                   # Downloaded GGUF files (created by setup)
```

## llama.cpp vs Ollama

### Why llama.cpp?

Ollama's OpenAI-compatible API (`/v1` endpoints) doesn't properly translate tool calls for many local models. This causes issues with AI coding assistants - models output malformed XML-style tags instead of proper JSON tool calls.

**llama.cpp's native server handles tool calling correctly**, making it the better choice for:
- OpenCode and other AI coding assistants
- Agentic workflows requiring function calling
- Any application using the OpenAI API format

### When to use Ollama

Ollama is still great for:
- Simple chat interactions
- Quick experimentation with different models
- Users who don't need tool calling

Both can run side-by-side:
- llama.cpp on port 8080 (for tool calling)
- Ollama on port 11434 (for simple chat)

### Other Tools

The llama.cpp server provides an OpenAI-compatible API at `http://localhost:8080/v1`. This may work with other coding assistants (Continue, Cursor, Aider, etc.) but these configurations are untested. Contributions welcome!

## Scripts Reference

### llama.cpp (root)

| Script | Platform | Description |
|--------|----------|-------------|
| `setup.sh` | Linux | Build llama.cpp with ROCm, download models |
| `setup-macos.sh` | macOS | Build llama.cpp with Metal, download models |
| `start-server.sh` | Both | Start llama-server with a model |
| `download-model.sh` | Both | Download individual GGUF models |
| `sync-opencode.sh` | Both | Sync models and agents to OpenCode |
| `uninstall.sh` | Both | Remove llama.cpp build, models, config |

### Ollama (ollama/)

| Script | Platform | Description |
|--------|----------|-------------|
| `setup.sh` | Linux | Setup with Docker |
| `setup-macos.sh` | macOS | Setup with Homebrew |
| `sync-opencode.sh` | Both | Sync Ollama models and agents to OpenCode |
| `uninstall.sh` | Both | Remove Ollama and models |

## Model Recommendations

### By Memory

| Memory | Recommended Models |
|--------|-------------------|
| 8GB | `qwen3-8b-q4km` (5GB), `qwen2.5-coder-3b-q4km` (2GB) |
| 12GB | `qwen3-14b-q4km` (9GB), `qwen2.5-coder-14b-q4km` (9GB) |
| 16GB | `qwen3-32b-q3km` (16GB), `deepseek-r1-14b-q4km` (9GB) |
| 24GB+ | `qwen3-30b-q4km` (18GB), `qwen2.5-coder-32b-q4km` (20GB) |

> **macOS note:** Apple Silicon uses unified memory shared between CPU and GPU. A 32GB Mac can run models that require ~24GB, leaving headroom for the OS.

### By Use Case

| Use Case | Recommended Model |
|----------|------------------|
| Fast code completion | `qwen2.5-coder-3b-q4km` |
| General coding | `qwen3-30b-q4km` (MoE - fast for size) |
| Maximum quality | `qwen2.5-coder-32b-q4km` |
| Reasoning tasks | `deepseek-r1-32b-q4km` |
| Limited memory | `qwen3-8b-q4km` |
| Vision/image analysis | `qwen3vl-8b-q4km` |

## Vision Models

Vision models (VLMs) can process images alongside text. These are useful for:

- **Frigate NVR** - AI-powered camera event descriptions
- **Image analysis** - Describing, captioning, or analyzing images
- **Document understanding** - Reading text from images

### Available Vision Models

| Model | Size | VRAM | Notes |
|-------|------|------|-------|
| `qwen3vl-8b-q8` | 8.7GB | 12-16GB | Best quality |
| `qwen3vl-8b-q4km` | 5GB | 8-12GB | Balanced |
| `qwen3vl-4b-q8` | 4.3GB | 8GB | Smaller, quality |
| `qwen3vl-4b-q4km` | 2.5GB | 6-8GB | Smallest |

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

# Or specify mmproj manually
./start-server.sh --mmproj models/mmproj-Qwen3VL-8B-Instruct-F16.gguf qwen3vl-8b-q4km

# For Frigate (needs port 11434 for Ollama API compatibility)
./start-server.sh -p 11434 --host 0.0.0.0 vision
```

### Frigate Integration

Configure Frigate to use the local vision model:

```yaml
# Frigate config.yaml
genai:
  enabled: true
  provider: ollama
  base_url: http://your-server-ip:11434
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

# Custom port and context
./start-server.sh -p 8081 -c 65536 qwen3-30b-q4km

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

### Linux: GPU Permission Denied

```bash
./setup.sh --fix-permissions
# Then log out and back in
```

### Linux: ROCm Issues

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
2. Reduce context: `./start-server.sh -c 8192 qwen3-32b-q4km`
3. Use partial offload: `./start-server.sh -n 20 qwen3-32b-q4km`

### Tool Calls Not Working

1. Ensure you're using llama.cpp provider in OpenCode (not Ollama)
2. Verify server is running: `curl http://127.0.0.1:8080/health`
3. Use a model that supports tool calling (Qwen3, Qwen2.5-Coder recommended)

## Configuration Files

| File | Description |
|------|-------------|
| `models.conf` | Model definitions (HuggingFace repos, filenames, sizes, context limits) |
| `agent/AGENTS.md` | OpenCode system prompt template (copied to ~/.config/opencode/) |
| `agent/*.md` | Custom agent templates (plan, review, debug) |
| `.env` | Local configuration (generated by setup) |
| `.env.example` | Template with all available settings |
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

## Links

- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [Ollama](https://ollama.com)
- [OpenCode](https://opencode.ai)
- [HuggingFace GGUF Models](https://huggingface.co/models?sort=trending&search=gguf)
- [ROCm Documentation](https://rocm.docs.amd.com)
- [Metal Performance Shaders](https://developer.apple.com/metal/)

## License

MIT
