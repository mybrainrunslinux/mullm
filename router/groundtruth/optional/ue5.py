"""
Optional groundtruth category: ue5.

Covers Unreal Engine 5 specific patterns:
  - GLB/GLTF import workflow
  - Best practices (Nanite, Lumen, World Partition)
  - Blueprint quick reference
  - Performance profiling console commands

Extracted from oldcode/groundtruth_ue5.py.
Enable via mullm.toml: enabled_categories = [..., "ue5"]
"""
from __future__ import annotations

import re

from ..registry import CategoryPlugin, register_category

# ---------------------------------------------------------------------------
# UE5 topic strings
# ---------------------------------------------------------------------------

_GLB_IMPORT = (
    "**Importing GLB/GLTF into Unreal Engine 5**\n\n"
    "**Method 1 — Interchange (UE5.3+, recommended):**\n"
    "- Drag .glb into Content Browser — Interchange pipeline auto-runs\n"
    "- Imports meshes, materials, animations, skeletons in one step\n\n"
    "**Method 2 — glTF Importer plugin (UE5.0-5.2):**\n"
    "- Enable: Edit -> Plugins -> search 'glTF Importer' -> Enable -> Restart\n"
    "- Supports PBR materials (metallic/roughness), embedded textures\n\n"
    "**Common GLB import issues:**\n"
    "| Issue | Fix |\n"
    "|---|---|\n"
    "| Black normals | Re-export GLB with correct winding order |\n"
    "| Wrong scale | UE5 uses cm; GLB uses m -> set Scale to 100 on import |\n"
    "| Missing textures | Embed textures in GLB (not separate PNG files) |\n"
    "| Animation not showing | Enable Import Animations in import dialog |\n"
    "| Y-up vs Z-up | UE5 is Z-up; GLB is Y-up -> Interchange handles this automatically |"
)

_UE5_BEST_PRACTICES = (
    "**UE5 Best Practices (5.4/5.5/5.6)**\n\n"
    "**Nanite (virtualized geometry):**\n"
    "- Enable per-mesh: SM Details -> Nanite -> Enable Nanite Support\n"
    "- Best for: static meshes >100K triangles, foliage, architecture\n"
    "- Avoid for: skeletal meshes (not supported), translucent materials\n"
    "- LODs become unnecessary for Nanite meshes\n\n"
    "**Lumen (dynamic GI):**\n"
    "- Enable: Project Settings -> Rendering -> Global Illumination -> Lumen\n"
    "- Software Lumen: cheaper, less accurate\n"
    "- Hardware Lumen: requires DXR/ray tracing GPU\n\n"
    "**World Partition (large open worlds):**\n"
    "- Replaces World Composition in UE5\n"
    "- Auto-streams level cells based on camera proximity\n\n"
    "**C++ vs Blueprint performance:**\n"
    "- Blueprint = ~10x slower than C++ for heavy tick logic\n"
    "- Rule: AI/physics/math in C++; designers iterate in Blueprint"
)

_UE5_GLB_PIPELINE = (
    "**muLLM -> UE5 GLB Pipeline (Meshy -> Blender -> UE5)**\n\n"
    "1. **Meshy output:** Download as .glb (PBR textures)\n"
    "2. **Blender decimation (if needed):**\n"
    "   - Import GLB -> select mesh -> Modifier Properties -> Decimate (ratio 0.1-0.3)\n"
    "   - Apply -> Export as GLB with Selected Objects only\n"
    "3. **UE5 Interchange import settings:**\n"
    "   - Scale: 100 (meters -> centimeters)\n"
    "   - Import as: Static Mesh or Skeletal Mesh (if rigged)\n"
    "   - Material Import: Create New Materials\n"
    "   - Normal Import: Import Normals and Tangents\n"
    "4. **Collision generation:**\n"
    "   - For physics objects: SM Details -> Collision -> Auto Convex Collision\n"
    "   - For walkable ground: Collision -> Box Simplified Collision"
)

_UE5_BLUEPRINT_TIPS = (
    "**UE5 Blueprint Quick Reference**\n\n"
    "| Task | Node / Method |\n"
    "|---|---|\n"
    "| Spawn actor | Spawn Actor from Class |\n"
    "| Play sound | Play Sound at Location / Play Sound 2D (UI) |\n"
    "| Delay | Delay node (async) or Set Timer by Function Name |\n"
    "| Line trace | Line Trace by Channel -> Break Hit Result |\n"
    "| Move actor | Set Actor Location (teleport) or Add Actor World Offset (delta) |\n"
    "| Get player | Get Player Character / Get Player Controller (index 0) |\n"
    "| Save game | Create Save Game Object -> cast -> fill fields -> Save Game to Slot |\n"
    "| Widget | Create Widget -> Add to Viewport |\n"
    "| Physics | Set Simulate Physics (on Static Mesh Component) |\n\n"
    "**Enhanced Input System (UE5.1+, replaces legacy input):**\n"
    "- Create Input Action (IA_Jump, IA_Move) + Input Mapping Context (IMC_Default)\n"
    "- In PlayerController/Character: Add Mapping Context on BeginPlay"
)

_UE5_PERF = (
    "**UE5 Performance / Profiling**\n\n"
    "**Console commands (in-editor or PIE):**\n"
    "```\nstat fps           — FPS + frame time\nstat unit          — Game/Draw/GPU breakdown\n"
    "stat scenerendering — draw calls\nr.ScreenPercentage 50 — render at 50% resolution\n"
    "ProfileGPU         — one-frame GPU capture\nt.MaxFPS 60        — cap framerate\n```\n\n"
    "**Draw call budget (mid-range GPU):**\n"
    "| Target | Draw Calls | Triangles |\n"
    "|---|---|---|\n"
    "| Mobile | <200 | <500K |\n"
    "| Desktop 60fps | <2,000 | <2M |\n"
    "| Desktop 30fps | <5,000 | <5M |\n\n"
    "**Nanite eliminates triangle budget** — use freely for static meshes."
)


# ---------------------------------------------------------------------------
# Pattern list and resolver
# ---------------------------------------------------------------------------

_UE5_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(import|load|bring in|add)\b.{0,30}\b(glb|gltf)\b.{0,30}\b(unreal|ue5|ue4|engine)\b", re.I), _GLB_IMPORT),
    (re.compile(r"\b(glb|gltf).{0,30}\b(import|ue5|unreal|engine)\b", re.I), _GLB_IMPORT),
    (re.compile(r"\bue5\b.{0,40}\b(best practice|tip|trick|how to|workflow)\b", re.I), _UE5_BEST_PRACTICES),
    (re.compile(r"\bunreal engine 5\b.{0,40}\b(tip|trick|best practice)\b", re.I), _UE5_BEST_PRACTICES),
    (re.compile(r"\b(nanite|lumen)\b.{0,40}\b(enable|setup|how|use|config)\b", re.I), _UE5_BEST_PRACTICES),
    (re.compile(r"\b(meshy|blender).{0,40}\b(ue5|unreal)\b", re.I), _UE5_GLB_PIPELINE),
    (re.compile(r"\bue5\b.{0,40}\b(glb|gltf|meshy|blender|pipeline)\b", re.I), _UE5_GLB_PIPELINE),
    (re.compile(r"\bblueprint\b.{0,40}\b(spawn|delay|timer|widget|save|input|quick ref)\b", re.I), _UE5_BLUEPRINT_TIPS),
    (re.compile(r"\bue5\b.{0,30}\b(spawn actor|add to viewport|line trace|enhanced input)\b", re.I), _UE5_BLUEPRINT_TIPS),
    (re.compile(r"\bue5\b.{0,40}\b(perf|fps|draw call|profil|optim)\b", re.I), _UE5_PERF),
    (re.compile(r"\b(stat fps|stat unit|profilegpu)\b", re.I), _UE5_PERF),
]


def _resolve_ue5(q: str) -> str | None:
    for pattern, answer in _UE5_PATTERNS:
        if pattern.search(q):
            return answer
    return None


def register_ue5() -> None:
    register_category(CategoryPlugin(
        name="ue5",
        patterns=[],
        resolver=_resolve_ue5,
    ))
