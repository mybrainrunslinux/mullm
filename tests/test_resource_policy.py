from router import resource_policy
from router.models import GpuStats, SystemStats


def test_resource_policy_reports_vram_and_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "entry.bin").write_bytes(b"x" * 1024)
    monkeypatch.setattr(resource_policy.settings, "cache_dir", cache)
    monkeypatch.setattr(resource_policy.settings, "cache_max_gb", 1.0)
    monkeypatch.setattr(resource_policy.settings, "vram_limit_gb", 8.0)
    monkeypatch.setattr(resource_policy.settings, "vram_reserve_gb", 1.0)

    data = resource_policy.status()

    assert data["vram"]["mode"] == "capped"
    assert data["vram"]["limit_gb"] == 8.0
    assert data["cache"]["size_bytes"] == 1024
    assert data["cache"]["max_gb"] == 1.0


def test_gpu_stats_exposes_legacy_dashboard_memory_fields():
    gpu = GpuStats(
        name="Test GPU",
        vram_used_mb=1536,
        vram_total_mb=4096,
        memory_used_mb=1536,
        memory_total_mb=4096,
        memory_pct=37.5,
    )
    payload = gpu.model_dump()

    assert payload["vram_used_mb"] == 1536
    assert payload["vram_total_mb"] == 4096
    assert payload["memory_used_mb"] == 1536
    assert payload["memory_total_mb"] == 4096
    assert payload["memory_pct"] == 37.5


def test_inferred_ollama_gpu_stats_do_not_fake_full_capacity():
    gpu = GpuStats(
        name="Ollama models",
        vram_used_mb=7075,
        vram_total_mb=0,
        memory_used_mb=7075,
        memory_total_mb=0,
        memory_pct=0,
        inferred_only=True,
    )
    payload = SystemStats(
        cpu_pct=0,
        ram_used_gb=1,
        ram_total_gb=2,
        gpu=gpu,
        ollama_loaded_models=["coder:9b"],
    ).model_dump()

    assert payload["gpu"]["inferred_only"] is True
    assert payload["gpu"]["vram_used_mb"] == 7075
    assert payload["gpu"]["vram_total_mb"] == 0
    assert payload["gpu"]["memory_pct"] == 0


def test_system_stats_exposes_legacy_dashboard_aliases():
    payload = SystemStats(
        cpu_pct=1,
        ram_used_gb=2,
        ram_total_gb=8,
        cpu_count=16,
        memory_used_gb=2,
        memory_total_gb=8,
        memory_pct=25,
        uptime_seconds=10,
        ollama_models=[{"name": "coder:9b"}],
    ).model_dump()

    assert payload["cpu_count"] == 16
    assert payload["memory_used_gb"] == 2
    assert payload["memory_total_gb"] == 8
    assert payload["memory_pct"] == 25
    assert payload["uptime_seconds"] == 10
    assert payload["ollama_models"] == [{"name": "coder:9b"}]
