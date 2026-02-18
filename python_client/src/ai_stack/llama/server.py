"""llama.cpp server runtime helpers."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from ai_stack.core.exceptions import ServerError


def start_llama_server(
    config,
    registry,
    model_path: Optional[str] = None,
    mmproj_path: Optional[str] = None,
    stdout=None,
    stderr=None,
) -> subprocess.Popen:
    """Start llama.cpp server with configured runtime options."""
    if not config.is_llama_built:
        raise ServerError("llama.cpp is not built. Run setup() first.")

    if not model_path:
        raise ServerError(
            "No model specified. You must provide a model path.\n"
            "Example: manager.start_server('models/my-model.gguf')"
        )

    resolved_model_path = Path(model_path)
    if not resolved_model_path.exists():
        alt_path = config.paths.models_dir / resolved_model_path
        if alt_path.exists():
            resolved_model_path = alt_path
        else:
            registry.scan_models_dir()
            model_names = [model["name"] for model in registry.manifest.get("models", [])]
            if model_names:
                model_list = "\n  • ".join(model_names[:5])
                msg = (
                    f"Model not found: {resolved_model_path}\n"
                    f"Available models in {config.paths.models_dir}:\n  • {model_list}"
                )
                if len(model_names) > 5:
                    msg += f"\n  ... and {len(model_names) - 5} more"
            else:
                msg = (
                    f"Model not found: {resolved_model_path}\n"
                    f"No models available in {config.paths.models_dir}"
                )
            raise ServerError(msg)

    if not mmproj_path:
        mmproj = registry.get_mmproj_for_model(resolved_model_path)
        if mmproj:
            print(f"📎 Auto-detected MMproj: {mmproj.name}")
            mmproj_path = str(mmproj)

    cmd = [
        str(config.llama_server_binary),
        "-m",
        str(resolved_model_path),
        "--host",
        config.server.host,
        "--port",
        str(config.server.port),
        "-c",
        str(config.model.context_size),
        "-ngl",
        str(config.gpu.layers),
    ]

    if mmproj_path and Path(mmproj_path).exists():
        cmd.extend(["--mmproj", mmproj_path])

    print(f"Starting server: {' '.join(cmd)}")

    env = os.environ.copy()
    if config.gpu.vendor == "amd" and config.gpu.hsa_override_gfx_version:
        env["HSA_OVERRIDE_GFX_VERSION"] = config.gpu.hsa_override_gfx_version

    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=stdout,
        stderr=stderr,
    )

    print("Waiting for server to start...", end="", flush=True)
    for _ in range(30):
        try:
            response = requests.get(f"{config.server.llama_url}/health", timeout=1)
            if response.status_code == 200:
                print(" ✓")
                print(f"Server started on {config.server.llama_url}")
                return process
        except requests.RequestException:
            pass
        print(".", end="", flush=True)
        time.sleep(1)

    print(" ✗")
    process.terminate()
    raise ServerError("Server failed to start within 30 seconds")
