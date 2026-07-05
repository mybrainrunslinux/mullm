import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from router.config import settings
from router.main import app


class MockComfyTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"name": "Mock GPU", "vram_total": 8_000_000_000}]})
        if request.url.path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(
                200,
                json={
                    "CheckpointLoaderSimple": {
                        "input": {"required": {"ckpt_name": [["sd_xl_base_1.0.safetensors"]]}}
                    }
                },
            )
        if request.url.path == "/object_info/UnetLoaderGGUF":
            return httpx.Response(200, json={"UnetLoaderGGUF": {"input": {"required": {"unet_name": [[]]}}}})
        if request.url.path == "/object_info/LoraLoader":
            return httpx.Response(
                200,
                json={
                    "LoraLoader": {
                        "input": {
                            "required": {
                                "lora_name": [[
                                    "Hyper-SDXL-4steps-lora.safetensors",
                                    "Touch-of-Realism-SDXL.safetensors",
                                ]]
                            }
                        }
                    }
                },
            )
        if request.url.path == "/object_info/VAELoader":
            return httpx.Response(
                200,
                json={"VAELoader": {"input": {"required": {"vae_name": [["sdxl_vae.safetensors"]]}}}},
            )
        if request.url.path == "/object_info/UNETLoader":
            return httpx.Response(
                200,
                json={
                    "UNETLoader": {
                        "input": {
                            "required": {
                                "unet_name": [[
                                    "hunyuan3d-dit-v2-mini-fp16.safetensors",
                                    "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
                                ]]
                            }
                        }
                    }
                },
            )
        if request.url.path == "/object_info/LoadImage":
            return httpx.Response(200, json={"LoadImage": {"input": {"required": {"image": [["ref.png"]]}}}})
        if request.url.path == "/object_info/CLIPVisionLoader":
            return httpx.Response(
                200,
                json={"CLIPVisionLoader": {"input": {"required": {"clip_name": [["clip_vision_g.safetensors"]]}}}},
            )
        if request.url.path == "/object_info/CLIPVisionEncode":
            return httpx.Response(200, json={"CLIPVisionEncode": {"input": {"required": {}}}})
        if request.url.path == "/object_info/Hunyuan3Dv2Conditioning":
            return httpx.Response(200, json={"Hunyuan3Dv2Conditioning": {"input": {"required": {}}}})
        if request.url.path == "/object_info/EmptyLatentHunyuan3Dv2":
            return httpx.Response(200, json={"EmptyLatentHunyuan3Dv2": {"input": {"required": {}}}})
        if request.url.path == "/object_info/KSampler":
            return httpx.Response(200, json={"KSampler": {"input": {"required": {}}}})
        if request.url.path == "/object_info/VAEDecodeHunyuan3D":
            return httpx.Response(200, json={"VAEDecodeHunyuan3D": {"input": {"required": {}}}})
        if request.url.path == "/object_info/VoxelToMesh":
            return httpx.Response(200, json={"VoxelToMesh": {"input": {"required": {}}}})
        if request.url.path == "/object_info/SaveGLB":
            return httpx.Response(200, json={"SaveGLB": {"input": {"required": {}}}})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "prompt-123"})
        if request.url.path == "/history/prompt-123":
            return httpx.Response(
                200,
                json={
                    "prompt-123": {
                        "status": {"completed": True},
                        "outputs": {"7": {"images": [{"filename": "frame.png"}]}},
                    }
                },
            )
        if request.url.path == "/view":
            return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "ref.png", "subfolder": "", "type": "input"})
        return httpx.Response(404, text="missing")


@pytest.fixture
def comfy_mock(monkeypatch):
    class MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = MockComfyTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("router.comfyui_api.httpx.AsyncClient", MockClient)
    monkeypatch.setattr(settings, "comfyui_base_url", "http://127.0.0.1:8189")


@pytest.mark.asyncio
async def test_comfyui_status_prompt_history_and_view(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/comfyui/status")
        assert status.status_code == 200
        assert status.json()["running"] is True

        prompt = await client.post("/api/comfyui/prompt", json={"prompt": {"1": {"class_type": "Test"}}})
        assert prompt.status_code == 200
        assert prompt.json()["prompt_id"] == "prompt-123"

        history = await client.get("/api/comfyui/history/prompt-123")
        assert history.status_code == 200
        assert history.json()["prompt-123"]["status"]["completed"] is True

        view = await client.get("/api/comfyui/view?filename=test.png")
        assert view.status_code == 200
        assert view.content == b"png"


@pytest.mark.asyncio
async def test_texture_route_queues_comfyui_workflow(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/texture", json={"asset_name": "test-sword", "style": "brushed steel", "seed": 42})

    assert result.status_code == 200
    assert result.json()["job_id"] == "prompt-123"
    assert result.json()["poll_url"] == "/api/comfyui/history/prompt-123"


@pytest.mark.asyncio
async def test_comfyui_models_lists_checkpoints_loras_and_vaes(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/comfyui/models")

    assert result.status_code == 200
    data = result.json()
    assert data["running"] is True
    assert data["preferred_checkpoint"] == "sd_xl_base_1.0.safetensors"
    assert data["checkpoints"] == ["sd_xl_base_1.0.safetensors"]
    assert "Touch-of-Realism-SDXL.safetensors" in data["loras"]
    assert data["vaes"] == ["sdxl_vae.safetensors"]
    assert data["diffusion_models"] == [
        "hunyuan3d-dit-v2-mini-fp16.safetensors",
        "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
    ]
    assert data["counts"]["loras"] == 2


@pytest.mark.asyncio
async def test_image_and_video_routes_queue_comfyui_workflows(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        image = await client.post("/api/image/generate", json={"prompt": "upright sword", "seed": 1})
        video = await client.post("/api/video/generate", json={"prompt": "rotating sword", "seed": 2, "frames": 8})
        video_alias = await client.post("/api/video", json={"prompt": "rotating sword", "seed": 2, "frames": 8})

    assert image.status_code == 200
    assert image.json()["provider"] == "comfyui"
    assert image.json()["poll_url"] == "/api/image/prompt-123"
    assert video.status_code == 200
    assert video.json()["provider"] == "comfyui"
    assert video.json()["poll_url"] == "/api/comfyui/history/prompt-123"
    assert video_alias.status_code == 200
    assert video_alias.json()["provider"] == "comfyui"


@pytest.mark.asyncio
async def test_comfyui_3d_text_queues_reference_image_stage(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(
            "/api/3d/comfyui",
            json={"prompt": "medieval crossbow", "style": "low poly", "name": "crossbow", "seed": 3},
        )

    assert result.status_code == 200
    data = result.json()
    assert data["provider"] == "comfyui"
    assert data["stage"] == "reference_image"
    assert data["poll_url"] == "/api/comfyui/history/prompt-123"
    assert data["reference_prefix"] == "mullm_crossbow_ref"
    assert "/api/3d/comfyui" in data["next_step"]


@pytest.mark.asyncio
async def test_comfyui_3d_asset_type_adds_prompt_hints(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(
            "/api/3d/comfyui",
            json={
                "prompt": "steampunk sword",
                "style": "low poly",
                "name": "steampunk-sword",
                "asset_type": "sword",
                "seed": 5,
            },
        )

    assert result.status_code == 200
    data = result.json()
    assert data["asset_type"] == "weapon"
    assert "clear handle or hilt" in data["prompt_hint"]
    assert "point facing up" in data["prompt_hint"]


@pytest.mark.asyncio
async def test_comfyui_3d_image_queues_hunyuan_mesh_stage(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(
            "/api/3d/comfyui",
            json={"image": "ref.png", "name": "crossbow", "seed": 4},
        )

    assert result.status_code == 200
    data = result.json()
    assert data["provider"] == "comfyui"
    assert data["stage"] == "mesh"
    assert data["poll_url"] == "/api/comfyui/history/prompt-123"
    assert data["expected_output"] == "mullm_3d/crossbow_*.glb"


@pytest.mark.asyncio
async def test_video_editor_compat_routes_return_stable_shapes(comfy_mock):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/video")
        listing = await client.get("/api/video/list")
        job = await client.get("/api/video/prompt-123")
        stitch_single = await client.post("/api/video/stitch", json={"clips": [{"url": "/api/video/demo.mp4"}]})
        stitch_multi = await client.post(
            "/api/video/stitch",
            json={"clips": [{"url": "/a.mp4"}, {"url": "/b.mp4"}]},
        )
        upscale = await client.post("/api/video/upscale", json={"url": "/api/video/demo.mp4"})
        cloud = await client.post("/api/video", json={"prompt": "city flyover", "provider": "kling"})

    assert status.status_code == 200
    assert status.json()["providers"]["comfyui"]["configured"] is True
    assert listing.status_code == 200
    assert listing.json()["videos"] == []
    assert job.status_code == 200
    assert job.json()["status"] == "done"
    assert stitch_single.status_code == 200
    assert stitch_single.json()["output_url"] == "/api/video/demo.mp4"
    assert stitch_multi.status_code == 501
    assert "adapter" in stitch_multi.json()["detail"]
    assert upscale.status_code == 501
    assert "adapter" in upscale.json()["detail"]
    assert cloud.status_code == 412
    assert "not configured" in cloud.json()["detail"]
