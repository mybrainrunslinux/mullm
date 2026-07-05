import wave
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from router.backends.protocol import BackendResponse
from router.main import app
from router.models import PipelineResult, TierLabel


def _pipeline_result(response: str = "ok") -> PipelineResult:
    return PipelineResult(
        response=response,
        tier=TierLabel.GROUNDTRUTH,
        cost=0.0,
        tokens_used=0,
        latency_ms=1.0,
        model_used="groundtruth-lut",
        groundtruth_category="test",
    )


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_discovery_manifests_are_machine_callable(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        agent = await client.get("/.well-known/agent.json")
        plugin = await client.get("/.well-known/ai-plugin.json")

    assert agent.status_code == 200
    assert plugin.status_code == 200
    assert {skill["id"] for skill in agent.json()["skills"]} >= {"query", "classify", "split"}
    assert plugin.json()["name_for_model"] == "mullm"


@pytest.mark.asyncio
async def test_mcp_tools_list_and_query_wrapper(transport, monkeypatch):
    import router.main as main_module

    monkeypatch.setattr(main_module, "_execute_query_body", AsyncMock(return_value=_pipeline_result("wrapped")))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tools = await client.get("/mcp/tools")
        query = await client.post("/mcp/tools/query", json={"content": "What is HTTP 400?"})

    assert tools.status_code == 200
    assert "mullm_query" in {tool["name"] for tool in tools.json()["tools"]}
    assert query.status_code == 200
    assert query.json()["text"] == "wrapped"
    assert query.json()["metadata"]["tier"] == "groundtruth"


@pytest.mark.asyncio
async def test_mcp_call_supports_jsonrpc_tools_call(transport, monkeypatch):
    import router.main as main_module

    monkeypatch.setattr(main_module, "_execute_query_body", AsyncMock(return_value=_pipeline_result("called")))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/mcp/call",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "mullm_query",
                    "arguments": {"content": "What is HTTP 400?"},
                },
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 7
    assert data["result"]["text"] == "called"


@pytest.mark.asyncio
async def test_rpc_query_and_batch(transport, monkeypatch):
    import router.main as main_module

    monkeypatch.setattr(main_module, "_execute_query_body", AsyncMock(return_value=_pipeline_result("rpc answer")))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        single = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "q1",
                "method": "query",
                "params": {"content": "What is HTTP 400?"},
            },
        )
        batch = await client.post(
            "/rpc",
            json=[
                {"jsonrpc": "2.0", "id": 1, "method": "query", "params": {"content": "a"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ],
        )

    assert single.status_code == 200
    assert single.json()["result"]["response"] == "rpc answer"
    assert batch.status_code == 200
    assert [item["id"] for item in batch.json()] == [1, 2]
    assert batch.json()[1]["result"]["tools"][0]["name"] == "mullm_query"


@pytest.mark.asyncio
async def test_rpc_unknown_method_returns_jsonrpc_error(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 99, "method": "missing.method", "params": {}},
        )

    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_rpc_docs_route_is_available(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/rpc/docs")

    assert resp.status_code == 200
    assert "JSON-RPC 2.0" in resp.text


@pytest.mark.asyncio
async def test_rpc_supports_documented_cache_methods(transport, monkeypatch):
    import router.main as main_module

    async def fake_lookup(params):
        return {"hit": True, "response": "cached", "metadata": {"source": "test"}}

    async def fake_store(params):
        return {"stored": True}

    monkeypatch.setattr(main_module, "_rpc_cache_lookup", fake_lookup)
    monkeypatch.setattr(main_module, "_rpc_cache_store", fake_store)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        lookup = await client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 10, "method": "cache.lookup", "params": {"query": "q"}},
        )
        search = await client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 11, "method": "cache.search", "params": {"query": "q"}},
        )
        store = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 12,
                "method": "cache.store",
                "params": {"query": "q", "response": "r"},
            },
        )

    assert lookup.json()["result"]["response"] == "cached"
    assert search.json()["result"]["hit"] is True
    assert store.json()["result"]["stored"] is True


@pytest.mark.asyncio
async def test_a2a_agent_registration_and_task_routes(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        registered = await client.post(
            "/api/agents/register",
            json={
                "agent_id": "reviewer-demo",
                "endpoint": "http://127.0.0.1:9999/agent",
                "capabilities": ["code", "review"],
            },
        )
        listed = await client.get("/api/agents?capability=code")
        heartbeat = await client.post("/api/agents/reviewer-demo/heartbeat")
        task = await client.post(
            "/api/agents/reviewer-demo/task",
            json={"content": "Review the protocol endpoints."},
        )
        tasks = await client.get("/api/agents/reviewer-demo/tasks")
        deleted = await client.delete("/api/agents/reviewer-demo")

    assert registered.status_code == 200
    assert registered.json()["agent"]["agent_id"] == "reviewer-demo"
    assert listed.json()["count"] >= 1
    assert heartbeat.json()["ok"] is True
    assert task.json()["status"] == "accepted"
    assert tasks.json()["count"] == 1
    assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_rpc_agents_register_matches_documented_method(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "agent-register",
                "method": "agents.register",
                "params": {
                    "agent_id": "rpc-demo",
                    "endpoint": "http://127.0.0.1:9998/agent",
                    "capabilities": ["classify"],
                },
            },
        )
        listed = await client.get("/api/agents?capability=classify")
        await client.delete("/api/agents/rpc-demo")

    assert resp.status_code == 200
    assert resp.json()["result"]["registered"] is True
    assert any(agent["agent_id"] == "rpc-demo" for agent in listed.json()["agents"])


def test_plugin_manifest_endpoints_are_registered():
    from router.main import _iter_app_routes
    from router.plugin_manifest import capability_manifests

    routes = {getattr(route, "path", "") for route in _iter_app_routes()}
    failures = []
    for plugin in capability_manifests():
        for endpoint in plugin.get("endpoints", []):
            if endpoint.endswith("/*"):
                prefix = endpoint[:-1]
                if not any(path.startswith(prefix) for path in routes):
                    failures.append(f"{plugin['id']}: {endpoint}")
            elif endpoint not in routes:
                failures.append(f"{plugin['id']}: {endpoint}")

    assert failures == []


@pytest.mark.asyncio
async def test_demo_research_endpoints_back_advertised_pages(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tasks = await client.get("/api/onnx/tasks")
        task = await client.get("/api/onnx/task/1")
        validate = await client.post("/api/onnx/validate", json={"task_num": 1, "code": "import onnx\ndef build_model():\n    pass"})
        save = await client.post("/api/onnx/save", json={"task_num": 1, "code": "import onnx"})
        compare = await client.post("/api/compare/star", json={"prompt": "x", "preferred_model": "local-9b"})

    assert tasks.status_code == 200
    assert task.status_code == 200
    assert validate.json()["ok"] is True
    assert save.json()["saved"] is True
    assert compare.json()["saved"] is True


@pytest.mark.asyncio
async def test_routerbench_static_is_packaged_and_not_mocked(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        static = await client.get("/api/bench/routerbench-static")
        compare = await client.post(
            "/api/bench/run",
            json={"mode": "routerbench", "type": "compare"},
        )

    assert static.status_code == 200
    static_data = static.json()["result"]
    assert static_data["mode"] == "archive"
    assert static_data["source"] == "builtin:routerbench-static"
    assert static_data["live_rerun"] is False
    assert static_data["winner"] == "mullm"
    assert len(static_data["routers_ranked"]) >= 5

    assert compare.status_code == 200
    compare_data = compare.json()
    assert compare_data["compare"] is True
    assert compare_data["winner"] == "mullm_bon"
    assert any(row["router"] == "mullm_bon" for row in compare_data["routers_ranked"])


class _CompareFakeBackend:
    provider_name = "ollama"

    async def generate(self, messages, model=None, **kwargs):
        return BackendResponse(
            text=f"real compare answer from {model}: {messages[-1]['content']}",
            output_tokens=7,
            cost_usd=0,
            model=model or "fake",
            provider=self.provider_name,
        )

    async def stream(self, messages, model=None, **kwargs):
        yield "unused"

    async def health(self):
        return True


@pytest.mark.asyncio
async def test_compare_stream_uses_registered_backend(monkeypatch, transport):
    from router.backends import protocol

    monkeypatch.setitem(protocol._registry, "ollama", _CompareFakeBackend())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/compare/stream", params={"prompt": "say hi", "models": "local-9b"})

    assert response.status_code == 200
    text = response.text
    assert "real compare answer" in text
    assert "local demo response" not in text
    assert '"done": true' in text


@pytest.mark.asyncio
async def test_compare_stream_reports_unconfigured_provider(monkeypatch, transport):
    from router.backends import protocol

    monkeypatch.setattr(protocol, "_registry", {})

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/compare/stream", params={"prompt": "say hi", "models": "gemini"})

    assert response.status_code == 200
    assert "google is not configured" in response.text
    assert '"error": true' in response.text


@pytest.mark.asyncio
async def test_hyper_query_streams_live_pipeline_results(monkeypatch, transport):
    import router.decomposer as decomposer_module
    import router.tiers as tiers_module

    async def fake_decompose(_prompt):
        return [
            {"task": "explain HTTP 400", "suggested_tier": "local", "depends_on": []},
            {"task": "explain CSS padding", "suggested_tier": "local", "depends_on": []},
        ]

    async def fake_execute(request):
        return PipelineResult(
            response=f"live answer: {request.content}",
            tier=TierLabel.LOCAL,
            cost=0.0,
            tokens_used=3,
            latency_ms=1.0,
            model_used="fake-local",
        )

    monkeypatch.setattr(decomposer_module, "decompose_prompt", fake_decompose)
    monkeypatch.setattr(tiers_module, "execute_pipeline", fake_execute)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/query/hyper", params={"q": "one then two"})

    assert response.status_code == 200
    text = response.text
    assert '"type": "decomposed"' in text
    assert '"type": "result"' in text
    assert '"type": "done"' in text
    assert "live answer: explain HTTP 400" in text
    assert "live answer: explain CSS padding" in text
    assert "asset ready" not in text
    assert "Demo Mode" not in text


@pytest.mark.asyncio
async def test_tts_backends_report_kokoro_cpu_default(monkeypatch, transport):
    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "kokoro":
            return object()
        return real_import_module(name, *args, **kwargs)

    monkeypatch.delenv("MULLM_KOKORO_DEVICE", raising=False)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tts/backends")

    assert response.status_code == 200
    kokoro = next(item for item in response.json()["backends"] if item["name"] == "kokoro")
    assert kokoro["available"] is True
    assert kokoro["device"] == "cpu"
    assert "mp3_available" in kokoro
    assert "ffmpeg" in response.json()["tools"]


@pytest.mark.asyncio
async def test_tts_batch_returns_honest_content_type_and_filename(monkeypatch, transport):
    import router.main as main_module

    async def fake_synth(body):
        assert body["backend"] == "kokoro"
        return b"RIFFfakewav", "audio/wav"

    monkeypatch.setattr(main_module, "_tts_synthesize_bytes", fake_synth)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/tts/batch",
            json={
                "backend": "kokoro",
                "voice": "af_heart",
                "format": "mp3",
                "csv": "name,text\nhello,Hello world",
            },
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["ok"] is True
    assert item["filename"] == "hello.wav"
    assert item["content_type"] == "audio/wav"
    assert item["audio_base64"]


def _tiny_wav_bytes() -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_musaic_upload_library_status_and_process(monkeypatch, tmp_path, transport):
    import router.main as main_module
    from router.config import settings

    monkeypatch.setattr(settings, "asset_root", str(tmp_path))
    monkeypatch.setattr(main_module.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    class FakeCompleted:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        output = cmd[-1]
        assert str(output).endswith(".mp3")
        with open(output, "wb") as fh:
            fh.write(b"ID3fake")
        return FakeCompleted()

    monkeypatch.setattr(main_module.subprocess, "run", fake_run)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/api/musaic/status")
        upload = await client.post(
            "/api/musaic/upload",
            files={"file": ("tone.wav", _tiny_wav_bytes(), "audio/wav")},
        )
        library = await client.get("/api/musaic/library")
        processed = await client.post(
            "/api/musaic/process",
            json={"asset_id": upload.json()["asset_id"], "format": "mp3_128", "normalize": True},
        )
        streamed = await client.get(processed.json()["stream_url"])

    assert status.status_code == 200
    assert status.json()["ffmpeg_available"] is True
    assert upload.status_code == 200
    assert upload.json()["bucket"] == "raw"
    assert library.status_code == 200
    assert any(item["asset_id"] == upload.json()["asset_id"] for item in library.json())
    assert processed.status_code == 200
    assert processed.json()["bucket"] == "processed"
    assert processed.json()["filename"].endswith(".mp3")
    assert streamed.status_code == 200
    assert streamed.content == b"ID3fake"


@pytest.mark.asyncio
async def test_foley_generate_prefers_mp3_and_can_save_to_musaic(monkeypatch, tmp_path, transport):
    import router.main as main_module
    from router.config import settings

    monkeypatch.setattr(settings, "asset_root", str(tmp_path))
    monkeypatch.setattr(main_module.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(main_module, "_transcode_wav_to_mp3", lambda wav: b"ID3foley")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/api/foley/status")
        presets = await client.get("/api/foley/presets")
        generated = await client.post(
            "/api/foley/generate",
            json={"effect": "clang", "prompt": "sword parry", "format": "mp3", "save": True},
        )
        library = await client.get("/api/musaic/library")

    assert status.status_code == 200
    assert status.json()["default_format"] == "mp3"
    assert status.json()["controls"]["pitch_semitones"]["min"] == -24
    assert presets.status_code == 200
    assert "clang" in presets.json()["presets"]
    assert "fire-crackle" in presets.json()["presets"]
    assert generated.status_code == 200
    assert generated.headers["content-type"].startswith("audio/mpeg")
    assert generated.headers["x-foley-effect"] == "clang"
    assert generated.headers["x-foley-pitch-semitones"] == "0.0"
    assert generated.headers["x-musaic-asset-id"].startswith("game:")
    assert generated.content == b"ID3foley"
    assert any(item["asset_id"] == generated.headers["x-musaic-asset-id"] for item in library.json())


@pytest.mark.asyncio
async def test_foley_generate_falls_back_to_wav_when_mp3_unavailable(monkeypatch, tmp_path, transport):
    import router.main as main_module
    from router.config import settings

    monkeypatch.setattr(settings, "asset_root", str(tmp_path))
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        generated = await client.post("/api/foley/generate", json={"effect": "thud", "format": "mp3"})

    assert generated.status_code == 200
    assert generated.headers["content-type"].startswith("audio/wav")
    assert generated.headers["x-foley-format"] == "wav"
    assert generated.content.startswith(b"RIFF")


@pytest.mark.asyncio
async def test_accuracy_leaderboard_and_displacements_do_not_404(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        leaderboard = await client.get("/api/leaderboard")
        displacements = await client.get("/api/displacements?limit=5")

    assert leaderboard.status_code == 200
    assert "models" in leaderboard.json()
    assert "signal_strength" in leaderboard.json()
    assert displacements.status_code == 200
    assert "events" in displacements.json()


@pytest.mark.asyncio
async def test_missing_benchmark_artifacts_return_archive_payloads(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/bench/arc-last-results")
        reload = await client.post("/api/bench/reload")

    assert missing.status_code == 200
    assert missing.json()["mode"] == "archive"
    assert "result" in missing.json()
    assert reload.status_code == 200
    assert reload.json()["ok"] is True


@pytest.mark.asyncio
async def test_public_settings_endpoint_never_returns_secret_values(monkeypatch, transport):
    from router.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "sk-secret")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["providers"]["openai"] is True
    assert "sk-secret" not in str(data)
