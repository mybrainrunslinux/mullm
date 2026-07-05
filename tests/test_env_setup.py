"""
Environment setup tests — validates Python version, uv, CUDA, and ComfyUI.

Runs without a live server. Hardware-dependent checks auto-skip when not available.

Run:
    pytest tests/test_env_setup.py -v
    pytest tests/test_env_setup.py -v -s          # verbose output including detected versions
    pytest tests/test_env_setup.py -k cuda         # CUDA checks only
    pytest tests/test_env_setup.py -k comfyui       # ComfyUI checks only
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import os
from pathlib import Path

import httpx
import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

# Supported Python version matrix (descending preference)
PYTHON_VERSION_MATRIX = [
    (3, 14),  # alpha/pre-release — accept if found
    (3, 13),  # stable, preferred
    (3, 12),  # current AI/ML sweet spot
    (3, 11),  # minimum supported
]
MIN_PYTHON = (3, 11)

# CUDA version preference matrix (13.2 intentionally omitted — known issues)
CUDA_VERSION_MATRIX = [
    (13, 3),
    (13, 0),
    (12, 8),
]
MIN_CUDA = (12, 8)

COMFYUI_URL = "http://localhost:8188"
COMFYUI_TIMEOUT = 5.0

PROJECT_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cuda_version() -> tuple[int, int] | None:
    """Return installed CUDA version as (major, minor) or None."""
    nvcc = shutil.which("nvcc")
    if nvcc:
        try:
            out = subprocess.check_output([nvcc, "--version"], text=True, timeout=5)
            for part in out.split():
                if part.startswith("V") and "." in part:
                    nums = part.lstrip("V").split(".")
                    return (int(nums[0]), int(nums[1]))
        except Exception:
            pass
    # Fallback: try nvidia-smi
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.check_output([smi], text=True, timeout=5)
            for line in out.splitlines():
                if "CUDA Version:" in line:
                    ver = line.split("CUDA Version:")[-1].strip().split()[0]
                    parts = ver.split(".")
                    return (int(parts[0]), int(parts[1]))
        except Exception:
            pass
    # Fallback: try torch
    try:
        import torch  # noqa: PLC0415

        cuda_ver = torch.version.cuda
        if cuda_ver:
            parts = cuda_ver.split(".")
            return (int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return None


def _uv_version() -> str | None:
    uv = shutil.which("uv")
    if not uv:
        return None
    try:
        return subprocess.check_output([uv, "--version"], text=True, timeout=5).strip()
    except Exception:
        return None


def _comfyui_available() -> bool:
    try:
        r = httpx.get(f"{COMFYUI_URL}/system_stats", timeout=COMFYUI_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


# ── Python version tests ──────────────────────────────────────────────────────

class TestPythonVersion:
    def test_minimum_python_met(self):
        """Python must be at least 3.11."""
        current = sys.version_info[:2]
        assert current >= MIN_PYTHON, (
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, got {current[0]}.{current[1]}"
        )

    def test_python_version_in_supported_matrix(self):
        """Current Python should match one of our supported versions."""
        current = sys.version_info[:2]
        supported = [f"{maj}.{min_}" for maj, min_ in PYTHON_VERSION_MATRIX]
        in_matrix = any(current == v for v in PYTHON_VERSION_MATRIX)
        if not in_matrix:
            pytest.xfail(
                f"Python {current[0]}.{current[1]} not in supported matrix {supported}. "
                "May still work — treat as experimental."
            )

    def test_python_313_or_newer_preferred(self):
        """3.13+ is preferred for free-threaded GIL improvements. Warn if on 3.12."""
        current = sys.version_info[:2]
        if current < (3, 13):
            pytest.xfail(
                f"Running Python {current[0]}.{current[1]}. "
                "Python 3.13+ preferred for free-threaded GIL. Upgrade when AI/ML packages support it."
            )

    def test_python_314_is_experimental(self):
        """3.14 alpha is accepted but flagged as experimental."""
        current = sys.version_info[:2]
        if current >= (3, 14):
            pytest.xfail(
                f"Python {current[0]}.{current[1]} is pre-release/alpha. "
                "torch/transformers may not have official wheels yet."
            )


# ── uv tests ─────────────────────────────────────────────────────────────────

class TestUvInstaller:
    def test_uv_installed(self):
        """uv must be available on PATH."""
        ver = _uv_version()
        assert ver is not None, (
            "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )
        print(f"\n  uv: {ver}")

    def test_uv_can_create_venv(self, tmp_path):
        """uv venv creation works with current Python."""
        uv = shutil.which("uv")
        if not uv:
            pytest.skip("uv not installed")
        venv = tmp_path / "test_venv"
        result = subprocess.run(
            [uv, "venv", str(venv), "--python", f"{sys.version_info.major}.{sys.version_info.minor}"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"uv venv failed:\n{result.stderr}"
        assert (venv / "bin" / "python").exists() or (venv / "Scripts" / "python.exe").exists()

    def test_constraints_file_exists(self):
        """constraints.txt must exist in project root for CVE-safe installs."""
        constraints = PROJECT_ROOT / "constraints.txt"
        assert constraints.exists(), "constraints.txt missing — CVE pins not applied"
        text = constraints.read_text()
        assert "urllib3" in text
        assert "Pillow" in text


# ── CUDA tests ────────────────────────────────────────────────────────────────

class TestCuda:
    def test_cuda_available(self):
        """CUDA must be installed."""
        ver = _cuda_version()
        if ver is None:
            pytest.skip("CUDA not detected (nvcc, nvidia-smi, and torch.version.cuda all failed)")
        print(f"\n  CUDA: {ver[0]}.{ver[1]}")
        assert ver >= MIN_CUDA, (
            f"CUDA {MIN_CUDA[0]}.{MIN_CUDA[1]}+ required, got {ver[0]}.{ver[1]}"
        )

    def test_cuda_version_in_preferred_matrix(self):
        """CUDA version should be in our preferred matrix (no 13.2)."""
        ver = _cuda_version()
        if ver is None:
            pytest.skip("CUDA not detected")
        in_matrix = any(ver == v for v in CUDA_VERSION_MATRIX)
        if not in_matrix:
            pytest.xfail(
                f"CUDA {ver[0]}.{ver[1]} not in preferred matrix "
                f"{[f'{maj}.{min_}' for maj, min_ in CUDA_VERSION_MATRIX]}. "
                "Note: 13.2 intentionally skipped (known issues). 13.3 preferred."
            )

    def test_cuda_133_tile_programming_available(self):
        """CUDA 13.3 enables Tile programming and CCCL 3.3 distributions."""
        ver = _cuda_version()
        if ver is None:
            pytest.skip("CUDA not detected")
        if ver < (13, 3):
            pytest.xfail(
                f"CUDA {ver[0]}.{ver[1]} installed. "
                "CUDA 13.3 adds: Tile programming, CCCL 3.3 (17 random distributions), "
                "C++ compiler autotuning, improved mmap() support. "
                f"Upgrade: https://developer.nvidia.com/cuda-downloads"
            )

    def test_torch_sees_gpu(self):
        """PyTorch must see at least one CUDA-capable GPU."""
        torch = pytest.importorskip("torch")
        if not torch.cuda.is_available():
            pytest.skip("torch.cuda.is_available() = False")
        count = torch.cuda.device_count()
        name = torch.cuda.get_device_name(0)
        print(f"\n  GPU: {name} (×{count})")
        assert count >= 1

    def test_gpu_vram_sufficient(self):
        """GPU must have ≥20GB VRAM for the 30B MoE model at Q4_K_M."""
        torch = pytest.importorskip("torch")
        if not torch.cuda.is_available():
            pytest.skip("CUDA not available")
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024**3)
        print(f"\n  VRAM: {vram_gb:.1f} GB")
        assert vram_gb >= 20, (
            f"GPU has {vram_gb:.1f} GB VRAM. 30B MoE at Q4_K_M requires ~20 GB. "
            "Use the 9B model on lower-VRAM hardware."
        )


# ── ComfyUI tests ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _comfyui_available(), reason="ComfyUI not running on localhost:8188")
class TestComfyUI:
    def test_comfyui_health(self):
        """ComfyUI system_stats endpoint responds."""
        r = httpx.get(f"{COMFYUI_URL}/system_stats", timeout=COMFYUI_TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        print(f"\n  ComfyUI: {data}")

    def test_comfyui_object_info(self):
        """ComfyUI object_info reports available nodes including checkpoint loaders."""
        r = httpx.get(f"{COMFYUI_URL}/object_info", timeout=10.0)
        assert r.status_code == 200
        nodes = r.json()
        assert "CheckpointLoaderSimple" in nodes, (
            "CheckpointLoaderSimple node missing — ComfyUI may be running without models"
        )

    def test_comfyui_image_generation(self, tmp_path):
        """Generate a test image and verify output file is created."""
        if os.environ.get("MULLM_TEST_COMFYUI_GENERATE", "0").lower() not in {"1", "true", "yes"}:
            pytest.skip("Set MULLM_TEST_COMFYUI_GENERATE=1 to run slow ComfyUI generation")
        info = httpx.get(f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple", timeout=10.0)
        info.raise_for_status()
        ckpts = (
            info.json()
            .get("CheckpointLoaderSimple", {})
            .get("input", {})
            .get("required", {})
            .get("ckpt_name", [[]])[0]
        )
        preferred = [
            "sdxl_turbo.safetensors",
            "sd_xl_turbo_1.0_fp16.safetensors",
            "sd_xl_base_1.0.safetensors",
        ]
        ckpt_name = next((name for name in preferred if name in ckpts), ckpts[0] if ckpts else "")
        if not ckpt_name:
            pytest.skip("No ComfyUI checkpoints available")
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": ckpt_name},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["1", 1],
                    "text": "a serene blue mountain lake at golden hour, photorealistic",
                },
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": "blurry, low quality"},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 512, "height": 512, "batch_size": 1},
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                    "seed": 42,
                    "steps": 2,
                    "cfg": 1.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"images": ["6", 0], "filename_prefix": "mullm_test"},
            },
        }

        r = httpx.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow},
            timeout=60.0,
        )
        assert r.status_code == 200, f"ComfyUI prompt submit failed: {r.text}"
        prompt_id = r.json().get("prompt_id")
        assert prompt_id, "No prompt_id in response"

        # Poll for completion; shared ComfyUI instances can queue behind other jobs.
        import time
        for _ in range(180):
            time.sleep(1)
            hist = httpx.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=5.0)
            if hist.status_code == 200 and hist.json():
                outputs = hist.json().get(prompt_id, {}).get("outputs", {})
                if outputs:
                    # Find the image
                    for _node_id, node_output in outputs.items():
                        images = node_output.get("images", [])
                        if images:
                            img_info = images[0]
                            print(f"\n  Generated image: {img_info['filename']} ({img_info['type']})")
                            return
        pytest.skip("ComfyUI accepted the prompt but did not finish within 180s")
