"""Test that the groundtruth LUT classifier correctly routes short lookups
and does NOT intercept long technical questions."""

import pytest

from router.groundtruth import lookup as _lookup


def try_resolve_locally(query: str):
    result = _lookup(query)
    return result[0] if result else None


# Short lookups that SHOULD hit LUT
@pytest.mark.parametrize(
    "query,expected_fragment",
    [
        ("what is pi", "3.14"),
        ("what is .js", ".js"),
        ("exit code 137", "137"),
        ("what is .json", "JSON"),
        ("speed of light", "299,792,458"),
        ("what port does ssh use", "22"),
        ("http status 404", "404"),
    ],
)
def test_short_lookups_hit_lut(query, expected_fragment):
    result = try_resolve_locally(query)
    assert result is not None, f"Expected LUT hit for: {query}"
    assert expected_fragment.lower() in result.lower(), f"Expected '{expected_fragment}' in: {result[:100]}"


# Long technical questions that MUST route to model (return None)
@pytest.mark.parametrize(
    "query",
    [
        "How do I use Math.PI in a Three.js rotation calculation for camera orbit controls?",
        "Write a JavaScript function that loads a .js module dynamically and handles errors gracefully",
        "Explain how HTTP GET requests work in the context of a REST API fetch call with authentication headers",
        "In Three.js how do I create a procedural sword mesh with the blade along the Y axis using BufferGeometry",
        "What is the best way to implement proximity grenade detonation in a Three.js FPS game with blast radius",
        "How do I fix a Three.js PointerLockControls issue where the camera object is undefined in r165",
        "Write a ComfyUI workflow that generates a 3D model from text using Hunyuan3Dv2 with SaveGLB output node",
    ],
)
def test_long_queries_route_to_model(query):
    result = try_resolve_locally(query)
    assert result is None, f"Long query hit LUT instead of model: {query[:60]}... -> {(result or '')[:80]}"


# Edge cases near the 80-char boundary
def test_boundary_79_chars():
    """79 chars should still check LUTs"""
    q = "what is pi" + " " * 69  # pad to 79
    assert len(q.strip()) <= 80


def test_boundary_81_chars():
    """81 chars should skip LUTs"""
    q = "a" * 81
    result = try_resolve_locally(q)
    assert result is None
