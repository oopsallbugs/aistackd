# AI Stack

Local LLM setup and management with auto-detected GPU support.

## Installation

```bash
# Install in development mode
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Usage

```bash
# project.scripts
setup-stack = "ai_stack.cli:setup_cli" # Auto detect system hw config & check deps, download and builds llama.cpp
server-start = "ai_stack.cli:start_server_cli" # Starts llama.cpp server 
server-status = "ai_stack.cli:status_cli" # Shows status of llama.cpp server
server-stop = "ai_stack.cli:stop_server_cli" # Stops managed detached llama.cpp server
download-model = "ai_stack.cli:download_model_cli" # Download model from namespace/repo or huggingface.co URL
check-deps = "ai_stack.cli:check_deps_cli"
```

### Download model examples

```bash
download-model TheBloke/Llama-2-7B-GGUF
download-model https://huggingface.co/TheBloke/Llama-2-7B-GGUF --list --cache-diagnostics
download-model Qwen/Qwen2.5-7B-Instruct-GGUF --quant Q5_K_M
```

### Detection controls

```bash
AI_STACK_VERBOSE_DETECT=1 server-status
AI_STACK_AMD_TARGET=gfx1100 setup-stack
```

### Internal layout

- `ai_stack/cli/`: CLI entrypoints and command wrappers
- `ai_stack/stack/manager.py`: `SetupManager` orchestration
- `ai_stack/core/config.py`: runtime config and path/model discovery
- `ai_stack/llama/`: llama.cpp build/runtime helpers
- `ai_stack/huggingface/`: HF transport + resolver + cache
- `ai_stack/models/registry.py`: manifest ownership and model registry
