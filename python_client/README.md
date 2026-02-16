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
server-stop = "ai_stack.cli:stop_server_cli" # Stops llama.cpp server
download-model = "ai_stack.cli:download_model_cli" # Download model from url (hugging face etc)
check-deps = "ai_stack.cli:check_deps_cli"
```