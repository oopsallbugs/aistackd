# OpenHands Integration

[OpenHands](https://github.com/All-Hands-AI/OpenHands) is an autonomous AI software engineer that can understand your codebase, write code, run tests, and execute shell commands.

This guide covers integrating OpenHands with your local llama.cpp server.

## Quick Start

1. **Start the LLM server** (if running locally):
   ```bash
   ./start-server.sh qwen2.5-coder:32b
   ```

2. **Start OpenHands**:
   ```bash
   ./start-openhands.sh
   ```

3. **Open the web UI** at http://localhost:3000

## Architecture Options

### Option A: Local Setup (Single Machine)

Run both llama.cpp and OpenHands on the same machine:

```
┌─────────────────────────────────────────────┐
│              Your Machine                    │
│                                              │
│  ┌─────────────┐     ┌─────────────────┐    │
│  │ OpenHands   │────▶│ llama.cpp       │    │
│  │ (Docker)    │     │ (GPU-accelerated)│    │
│  │ :3000       │     │ :8080           │    │
│  └─────────────┘     └─────────────────┘    │
└─────────────────────────────────────────────┘
```

This is the default configuration. Just run `./start-openhands.sh`.

### Option B: Remote LLM Server

Run llama.cpp on a powerful GPU server, OpenHands on your local machine:

```
┌─────────────────┐          ┌─────────────────┐
│  Local Machine  │          │   GPU Server    │
│                 │   HTTP   │                 │
│  ┌───────────┐  │  ───────▶│  ┌───────────┐  │
│  │ OpenHands │  │          │  │ llama.cpp │  │
│  │ (Docker)  │  │          │  │ (GPU)     │  │
│  │ :3000     │  │          │  │ :8080     │  │
│  └───────────┘  │          │  └───────────┘  │
└─────────────────┘          └─────────────────┘
```

**On the GPU server**, start llama.cpp with network access:

```bash
# Edit .env to bind to all interfaces
LLAMA_HOST=0.0.0.0

# Start the server
./start-server.sh qwen2.5-coder:32b
```

**On your local machine**, configure the remote URL:

```bash
# In .env
REMOTE_LLM_URL=http://gpu-server.local:8080

# Or pass it directly
./start-openhands.sh --llm-url http://gpu-server.local:8080
```

## Configuration

### Environment Variables

Add these to your `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENHANDS_VERSION` | Docker image version | `1.3.0` |
| `OPENHANDS_WORKSPACE` | Workspace directory | Current directory |
| `OPENHANDS_PORT` | Web UI port | `3000` |
| `REMOTE_LLM_URL` | Remote LLM server URL | (empty = local) |

### Command Line Options

```bash
./start-openhands.sh [OPTIONS]

Options:
  --workspace PATH   Set workspace directory
  --llm-url URL      Override LLM server URL
  --model MODEL      Specify model name
  --stop             Stop OpenHands
  --status           Show status
  --logs             View logs
```

## Model Recommendations

OpenHands works best with coding-focused models.

## Troubleshooting

### OpenHands can't connect to LLM

1. **Check if llama.cpp is running**:
   ```bash
   curl http://localhost:8080/health
   ```

2. **Check if it's accessible from Docker**:
   ```bash
   docker run --rm --add-host host.docker.internal:host-gateway \
     curlimages/curl curl -s http://host.docker.internal:8080/health
   ```

3. **For remote servers**, ensure the firewall allows connections on port 8080.

### Slow Response Times

- Use a smaller model (7B instead of 32B)
- Increase GPU layers: `GPU_LAYERS=99`
- For remote servers, check network latency

### Container Won't Start

```bash
# Check for existing containers
docker ps -a | grep openhands

# Remove old container
docker rm openhands-app

# Try again
./start-openhands.sh
```

### Permission Errors

OpenHands needs access to the Docker socket:

```bash
# Add your user to docker group
sudo usermod -aG docker $USER

# Log out and back in, or:
newgrp docker
```

## Using Docker Compose

If you prefer docker-compose:

```bash
cd openhands/
docker-compose up -d
docker-compose logs -f
docker-compose down
```

## Security Considerations

- **Workspace access**: OpenHands can read/write files in the workspace directory
- **Docker access**: OpenHands creates sandbox containers via the Docker socket
- **Network access**: The sandbox containers can make network requests
- **LLM access**: If using a remote LLM, ensure the connection is secured (HTTPS) in production

For sensitive projects, consider:
- Using a dedicated workspace directory
- Running OpenHands in an isolated network
- Using HTTPS for remote LLM connections

## More Information

- [OpenHands Documentation](https://docs.all-hands.dev/)
- [OpenHands GitHub](https://github.com/All-Hands-AI/OpenHands)
- [llama.cpp GitHub](https://github.com/ggerganov/llama.cpp)
