# Ollama Local AI Setup

Run local AI models with GPU acceleration. Supports:

- **Linux + AMD GPU**: ROCm-accelerated Docker setup (full GPU support)
- **macOS**: Native Homebrew installation (Metal on Apple Silicon, CPU on Intel)

## Quick Start

### Linux Setup

```bash
# 1. Clone the repository
git clone https://github.com/oopsallbugs/ollama-rocm.git
cd ollama-rocm

# 2. Run setup
./setup.sh
```

> **Important**: The setup script auto-generates a `.env` file with your GPU-specific settings. Do not run `docker compose up` directly without first running `./setup.sh` — it will fail without the generated `.env` file.

### macOS Setup

```bash
# 1. Clone the repository
git clone https://github.com/oopsallbugs/ollama-rocm.git
cd ollama-rocm

# 2. Run macOS setup (installs via Homebrew)
./setup-macos.sh
```

> **Note**: macOS ships with Bash 3.2 which is too old for this script. If you see a version error, install a newer Bash with `brew install bash`, then run: `/opt/homebrew/bin/bash ./setup-macos.sh`

The setup scripts will:

1. Check all dependencies (and help you install missing ones)
2. Detect your GPU and configure the correct settings
3. Install and start Ollama (Docker on Linux, native on macOS)
4. Show an interactive menu to select which models to install
5. Configure OpenCode integration

**Estimated time**: 10-30 minutes depending on your internet speed and model choices.

## Requirements

### Linux with AMD GPU

| Requirement | Notes |
|-------------|-------|
| **Linux** | ROCm (AMD's GPU compute software) only supports Linux |
| **AMD GPU** | RDNA1, RDNA2, or RDNA3 (RX 5000/6000/7000 series) |
| **Disk space** | 20-100GB depending on model choices |
| **GPU Memory (VRAM)** | 8GB minimum, 16-24GB recommended for larger models |

**Dependencies** (install before running setup):

| Dependency | Install Command | Notes |
|------------|-----------------|-------|
| **Docker** | `sudo pacman -S docker` (Arch) / `sudo apt install docker.io` (Ubuntu) | Container runtime |
| **Docker Compose** | Usually included with Docker | Container orchestration |
| **curl** | `sudo pacman -S curl` (Arch) / `sudo apt install curl` (Ubuntu) | HTTP client |
| **bc** | `sudo pacman -S bc` (Arch) / `sudo apt install bc` (Ubuntu) | Calculator for size math |
| **gum** | `sudo pacman -S gum` (Arch) / See [gum install guide](https://github.com/charmbracelet/gum#installation) | Interactive menus |

The setup script checks for these and provides install instructions if any are missing. You can skip `gum` by running `./setup.sh --non-interactive`.

### macOS Requirements

| Requirement | Notes |
|-------------|-------|
| **macOS 12+** | Monterey or later |
| **Disk space** | 20-60GB depending on model choices |
| **Apple Silicon** | Recommended - uses Metal for GPU acceleration |
| **Intel Mac** | Supported but slower (CPU only) |

**Dependencies**:

| Dependency | Install Command | Notes |
|------------|-----------------|-------|
| **Bash 4+** | `brew install bash` | macOS ships with Bash 3.2 |
| **Homebrew** | Installed automatically if missing | Package manager |
| **Ollama** | Installed automatically via Homebrew | AI runtime |
| **gum** | `brew install gum` | Optional - improves selection menus |

Run the setup script with the newer Bash: `/opt/homebrew/bin/bash ./setup-macos.sh`

### Supported AMD GPUs

| GPU Series | Example Cards | Notes |
|------------|---------------|-------|
| RX 7000 (RDNA3) | 7900 XTX, 7900 XT, 7800 XT, 7700 XT, 7600 | Best performance |
| RX 6000 (RDNA2) | 6900 XT, 6800 XT, 6700 XT, 6600 XT | Great performance |
| RX 5000 (RDNA1) | 5700 XT, 5700, 5600 XT | Good performance |

## Choosing Models

### During Setup

The setup script shows an interactive menu where you can select which AI models to install. Models are automatically tagged based on your hardware:

- `[✓ recommended]` - Will run well on your GPU/system
- `[⚠ may struggle]` - Might work but could be slow
- `[✗ won't fit]` - Too large for your GPU memory

The first recommended model in each category is pre-selected. You can toggle selections with Space or x, and confirm with Enter.

### Customizing the Model List

Edit `models.conf` before or after running setup to customize the selection menu:

```bash
# Format: category|model:tag|size|description

# Small models for quick testing
small|tinyllama:latest|0.6GB|Tiny but capable - ideal for testing

# IDE autocomplete
autocomplete|qwen2.5-coder:3b|2GB|Fast code completion for IDE

# General purpose models
general|qwen3:14b|9GB|Fast all-rounder with good quality
general|qwen3:8b|5GB|Smaller and faster

# Reasoning models (show their thinking)
reasoning|deepseek-r1:32b|20GB|Deep reasoning with chain of thought

# Coding-focused models
coding|qwen3-coder:30b|18GB|Newest for agentic tasks and coding
```

**Categories**: You can use any category name. Built-in ones are: `small`, `autocomplete`, `general`, `reasoning`, `coding`, `specialized`

**Finding more models**: Browse <https://ollama.com/library>

### Adding More Models Later

After setup, you can pull additional models anytime:

```bash
# Linux (Docker)
docker exec ollama ollama pull codestral:22b
docker exec ollama ollama pull mistral-small:24b
docker exec ollama ollama pull deepseek-coder-v2:16b

# macOS (native)
ollama pull codestral:22b
ollama pull mistral-small:24b
```

After pulling new models, sync your OpenCode configuration:

```bash
./sync-opencode-config.sh
```

### Model Size Guide

| Your GPU Memory | Recommended Model Sizes |
|-----------------|------------------------|
| 8GB | Up to 7B models |
| 12GB | Up to 14B models |
| 16GB | Up to 14B-20B models |
| 24GB+ | 32B+ models work great |

## Using Ollama

### With OpenCode

```bash
# Start OpenCode in any project directory
cd ~/my-project
opencode

# Inside OpenCode, type /models to switch between local models
```

**Note on local models**: Local models (even 32B) are still hit-or-miss compared to cloud models like Claude for complex agentic tasks. They work well for simple queries but struggle with multi-step reasoning, long context, and following system instructions reliably. You may notice models echoing OpenCode's internal `<system-reminder>` tags verbatim - this appears to be an issue with how instructions are passed to local models, causing them to treat system prompts as conversation text. I'm working on a fix for this and will update this note when resolved or an upstream fix is implemented.  

### Command Line Chat

```bash
# Linux (Docker)
docker exec -it ollama ollama run qwen3:14b

# macOS (native)
ollama run qwen3:14b

# Ask a one-off question
docker exec ollama ollama run qwen3:14b "Explain this regex: ^[a-z]+$"
```

### Managing Models

```bash
# List installed models
docker exec ollama ollama list          # Linux
ollama list                              # macOS

# Remove a model
docker exec ollama ollama rm qwen3:14b  # Linux
ollama rm qwen3:14b                      # macOS

# Check what's currently loaded in GPU memory
docker exec ollama ollama ps            # Linux
ollama ps                                # macOS
```

### Starting and Stopping

```bash
# Linux (Docker)
docker compose up -d      # Start
docker compose down       # Stop
docker compose restart    # Restart
docker compose logs -f    # View logs

# macOS (Homebrew)
brew services start ollama   # Start
brew services stop ollama    # Stop
brew services restart ollama # Restart
```

## Troubleshooting

### "Permission denied" or GPU Not Working

This is the most common issue on Linux. Run the permission fix:

```bash
./setup.sh --fix-permissions
```

Then **log out and log back in** (this is required - Linux only checks group membership at login).

After logging back in, run setup again:

```bash
./setup.sh
```

### Docker Not Running

```bash
# Start Docker
sudo systemctl start docker

# Make it start automatically on boot
sudo systemctl enable docker
```

### Model Downloads Failing

```bash
# Check disk space
df -h ~/.ollama

# If download was interrupted, remove and retry
docker exec ollama ollama rm qwen3:14b
docker exec ollama ollama pull qwen3:14b
```

### Slow Performance / Not Using GPU

```bash
# Watch GPU usage during inference (should spike when generating)
watch -n 1 rocm-smi

# Check GPU is accessible inside container
docker exec ollama ls /dev/kfd /dev/dri

# If GPU not accessible, fix permissions and log out/in:
./setup.sh --fix-permissions
```

### Check Status

```bash
# See overall system status
./setup.sh --status

# Check what's loaded in GPU memory
docker exec ollama ollama ps
```

### Upgrading from Older Installation

If you previously ran setup before the non-root container update, your `~/.ollama` directory may be owned by root. The setup script detects this and offers to fix it:

```bash
./setup.sh --force-env
```

If prompted about root-owned files, select "Yes" to fix ownership. This requires sudo once, after which all future operations will work without elevated permissions.

Manual fix:

```bash
sudo chown -R $(id -u):$(id -g) ~/.ollama
```

### More Help

See the [detailed troubleshooting section](#detailed-troubleshooting) below for more specific issues.

## Configuration

### Setup Script Options

```bash
./setup.sh --help              # Show all options
./setup.sh --status            # Check Ollama status
./setup.sh --update            # Update to latest version
./setup.sh --fix-permissions   # Fix GPU access permissions
./setup.sh --skip-models       # Re-run setup without model selection
./setup.sh --force-env         # Regenerate configuration
./setup.sh --non-interactive   # Use defaults, no prompts
./setup.sh --ignore-warnings   # Continue despite permission warnings
```

### Hardware Recommendations Toggle

By default, the setup script auto-selects the first model in each category that fits your hardware. To disable this and always select the first model regardless of size:

Add this line to `models.conf`:

```bash
IGNORE_HARDWARE_RECOMMENDATIONS=true
```

### Environment Variables

The setup script creates a `.env` file with your system's configuration. Key settings you might want to adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_UID` | Your UID | Container user ID (auto-detected) |
| `OLLAMA_GID` | Your GID | Container group ID (auto-detected) |
| `OLLAMA_KEEP_ALIVE` | `10m` | How long to keep models loaded in GPU memory |
| `OLLAMA_NUM_PARALLEL` | `2` | How many requests to handle at once |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Maximum models loaded simultaneously |

### OpenCode Configuration

Located at `~/.config/opencode/opencode.json`. This is automatically generated by setup.

To sync after adding new models:

```bash
./sync-opencode-config.sh              # Replace config with installed models
./sync-opencode-config.sh --merge      # Add new models, keep manual additions
./sync-opencode-config.sh --dry-run    # Preview without writing
./sync-opencode-config.sh --restore    # List and restore from backups
```

### Uninstalling

```bash
./uninstall.sh           # Interactive - choose what to remove
./uninstall.sh --all     # Remove everything
./uninstall.sh --dry-run # Preview what would be removed
```

**What gets removed:**

- Docker container and image (Linux) or Ollama via Homebrew (macOS)
- Downloaded models (`~/.ollama/`)
- OpenCode configuration (`~/.config/opencode/opencode.json`)
- Local `.env` file and backups

> **Note**: The container runs as your user (not root), so model files are owned by you and cleanup typically doesn't require sudo. If you're upgrading from an older installation that ran as root, the setup script will offer to fix file ownership.

**What is NOT removed**:

- System dependencies (Docker, Homebrew, gum, bc, curl)
- User group memberships (video, render, docker)

This is intentional - these tools are often shared with other applications. Remove them manually if no longer needed.

**Verify cleanup:**

```bash
# Linux
docker ps -a | grep ollama           # Should be empty
docker images | grep ollama          # Should be empty
ls ~/.ollama 2>/dev/null || echo "OK"  # Should say "OK"

# macOS
brew list 2>/dev/null | grep ollama || echo "OK"  # Should say "OK"
ls ~/.ollama 2>/dev/null || echo "OK"              # Should say "OK"
```

## Performance Tuning

### VRAM Management

| GPU VRAM | Recommended Settings |
|----------|---------------------|
| 24GB | `NUM_PARALLEL=2-4`, 32B models work great |
| 16GB | `NUM_PARALLEL=1-2`, prefer q4 quantization for 32B models |
| 12GB | `NUM_PARALLEL=1`, prefer 14B or smaller models |
| 8GB | `NUM_PARALLEL=1`, use 7B models or smaller |

### Quantization

Models come in different "quantizations" - smaller quantizations use less memory but may have lower quality:

| Quantization | Quality | Size | When to Use |
|--------------|---------|------|-------------|
| `q8_0` | Best | Largest | When you have plenty of VRAM |
| `q6_K` | Excellent | Large | Good balance for most users |
| `q4_K_M` | Good | Small | **Default** - works for most setups |
| `q3_K_S` | Acceptable | Tiny | When VRAM is very limited |

### Monitor GPU Usage

```bash
# Watch GPU during inference
watch -n 1 rocm-smi

# Inside container
docker exec ollama rocm-smi
```

## Detailed Troubleshooting

### Dependency Check Failed

Run setup to see what's missing:

```bash
./setup.sh
```

Common fixes:

```bash
# Docker not installed
sudo pacman -S docker        # Arch
sudo apt install docker.io   # Ubuntu/Debian
sudo dnf install docker      # Fedora

# Add yourself to docker group
sudo usermod -aG docker $USER
# Then log out and back in
```

### GPU Not Detected

```bash
# Check GPU devices exist
ls -la /dev/kfd /dev/dri

# Check AMD driver is loaded
lsmod | grep amdgpu

# Check GPU is recognized
lspci | grep -i vga
```

### Container Won't Start

```bash
# Check logs
docker compose logs

# Check if port 11434 is already in use
ss -tlnp | grep 11434

# Remove old container and retry
docker rm -f ollama
docker compose up -d
```

### Out of GPU Memory

```bash
# See what's loaded
docker exec ollama ollama ps

# Unload a model
curl http://localhost:11434/api/generate -d '{"model": "qwen3:32b", "keep_alive": 0}'

# Use a smaller model or quantization
docker exec ollama ollama pull qwen3:14b
```

### API Not Responding

```bash
# Check container is running
docker ps | grep ollama

# Test API
curl http://localhost:11434/api/tags

# Restart
docker compose restart
```

### OpenCode Can't Connect

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Check config exists
cat ~/.config/opencode/opencode.json

# Sync config with installed models
./sync-opencode-config.sh
```

## Project Structure

```text
ollama-rocm/
├── setup.sh                  # Main setup script (Linux)
├── setup-macos.sh            # macOS setup script
├── sync-opencode-config.sh   # Sync OpenCode config with installed models
├── uninstall.sh              # Clean removal script
├── docker-compose.yml        # Docker container configuration
├── models.conf               # Model selection menu configuration
├── models-metadata.conf      # Model display names and context limits
├── .env.example              # Template for configuration
├── .env                      # Your local config (generated by setup)
└── README.md                 # This file

~/.ollama/                    # Where models are stored (created by setup)
~/.config/opencode/           # OpenCode configuration (created by setup)
```

## License

MIT
