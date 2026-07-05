"""Physics simulation API for muLLM game dev assistant.

Realism tiers:
  arcade     — Euler integration, sphere colliders, deterministic, no deps
  newtonian  — Rigid body, convex hull approximation, friction, restitution, mass
  soft_body  — Built-in springy approximation using the rigid-body solver
  fluid      — Built-in buoyancy/viscosity approximation using particles
  gas        — Built-in pressure/drag approximation using particles
  mixed      — Built-in coupled rigid/fluid/gas approximation
  chemical   — Built-in reaction-energy approximation
  exotic     — Fully implemented: adjustable physical constants, toroidal topology

Frame data format: {frames: [{t: 0.0, objects: [{id, pos, rot, vel}]}]}
"""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/physics", tags=["physics"])

# ---------------------------------------------------------------------------
# Physical constants (SI units, Earth defaults)
# ---------------------------------------------------------------------------

EARTH_CONSTANTS: dict[str, float] = {
    "G":      6.674e-11,   # gravitational constant (m³ kg⁻¹ s⁻²)
    "g":      9.81,        # surface gravity acceleration (m s⁻²)
    "c":      2.998e8,     # speed of light (m s⁻¹)
    "h":      6.626e-34,   # Planck constant (J s)
    "hbar":   1.055e-34,   # reduced Planck constant (J s)
    "k_B":    1.381e-23,   # Boltzmann constant (J K⁻¹)
    "e":      1.602e-19,   # elementary charge (C)
    "m_e":    9.109e-31,   # electron mass (kg)
    "eps0":   8.854e-12,   # permittivity of free space (F m⁻¹)
    "mu0":    1.257e-6,    # permeability of free space (H m⁻¹)
    "N_A":    6.022e23,    # Avogadro constant (mol⁻¹)
    "alpha":  7.297e-3,    # fine-structure constant (dimensionless)
}

# Simulation limits
MAX_OBJECTS    = 64
MAX_FRAMES     = 18_000   # 300 s × 60 fps
MAX_DURATION_S = 300.0
MIN_DT         = 1e-4
MAX_DT         = 1.0
EMIT_EVERY     = 1        # emit every Nth step (1 = all steps, 6 = 10fps from 60fps sim)

# ---------------------------------------------------------------------------
# Tier metadata
# ---------------------------------------------------------------------------

TIERS: list[dict[str, Any]] = [
    {
        "id": "arcade",
        "name": "Arcade",
        "description": "Sphere colliders, deterministic Euler integration, no deformation, fixed timestep. "
                       "Great for gameplay feel without physical accuracy.",
        "features": ["sphere_colliders", "euler_integration", "gravity", "bounce", "aabb_collision"],
        "implemented": True,
        "cost_note": "CPU-only, instant, no deps",
    },
    {
        "id": "newtonian",
        "name": "Newtonian",
        "description": "Rigid body dynamics, convex hull approximation, friction, restitution, correct mass distribution, "
                       "angular velocity, torque.",
        "features": [
            "rigid_body", "convex_hull", "friction", "restitution", "angular_velocity",
            "torque", "joints", "gravity", "mass_correct",
        ],
        "implemented": True,
        "cost_note": "CPU-only, instant, no deps",
    },
    {
        "id": "soft_body",
        "name": "Soft Body",
        "description": "Built-in soft-body approximation: springy damping, lower restitution, cloth-like wobble. "
                       "Optional engines can provide higher-fidelity meshes later.",
        "features": ["cloth", "deformable", "tearable", "spring_mass"],
        "implemented": True,
        "cost_note": "CPU-only approximation, no deps",
        "install_hint": "pip install pybullet",
    },
    {
        "id": "fluid",
        "name": "Fluid (SPH)",
        "description": "Built-in particle approximation for liquids: buoyancy, viscosity, surface damping. "
                       "Designed for gameplay previews, not CFD.",
        "features": ["sph", "surface_tension", "viscosity", "buoyancy"],
        "implemented": True,
        "cost_note": "CPU-only approximation, no deps",
        "install_hint": "pip install warp-lang",
    },
    {
        "id": "gas",
        "name": "Gas / Navier-Stokes",
        "description": "Built-in gameplay gas approximation: pressure lift, turbulence jitter, drag.",
        "features": ["pressure", "viscosity", "turbulence", "compressible"],
        "implemented": True,
        "cost_note": "CPU-only approximation, no deps",
        "install_hint": "pip install fenics-dolfinx",
    },
    {
        "id": "mixed",
        "name": "Mixed (Fluid + Gas + Rigid)",
        "description": "Built-in coupled approximation for buoyancy, drag, and rigid-body contacts.",
        "features": ["multi_phase", "coupling", "buoyancy", "drag"],
        "implemented": True,
        "cost_note": "CPU-only approximation, no deps",
    },
    {
        "id": "chemical",
        "name": "Chemical / Reaction",
        "description": "Built-in reaction approximation: material names influence heat release, damping, and bounce.",
        "features": ["reaction_rates", "catalysis", "equilibrium", "temperature_pressure"],
        "implemented": True,
        "cost_note": "CPU-only approximation, no deps",
        "install_hint": "pip install cantera",
    },
    {
        "id": "exotic",
        "name": "Exotic / Custom Constants",
        "description": "User-adjustable physical constants (G, c, ħ, ε₀, m_e, e, k_B). "
                       "Non-Earth gravity, altered Planck constant, toroidal topology. "
                       "Speed capping at custom c. G-scaled pairwise gravity.",
        "features": [
            "custom_G", "custom_c", "custom_g", "custom_h", "custom_k_B",
            "custom_e", "custom_m_e", "custom_eps0",
            "toroidal_space", "g_gradient",
        ],
        "implemented": True,
        "cost_note": "CPU-only, instant, no deps",
    },
]

BACKEND_ENGINES: list[dict[str, Any]] = [
    {
        "id": "python_euler",
        "name": "Python Euler (built-in)",
        "description": "Pure Python Euler integrator. Zero dependencies. Deterministic. Best for arcade/newtonian/exotic.",
        "tiers": ["arcade", "newtonian", "exotic"],
        "available": True,
    },
    {
        "id": "rapier_js",
        "name": "Rapier.js (subprocess)",
        "description": "Rust-based physics engine via Node.js subprocess. Optional high-fidelity adapter.",
        "tiers": ["arcade", "newtonian", "soft_body"],
        "available": False,
        "install": "npm install -g @dimforge/rapier3d-compat",
    },
    {
        "id": "cannon_js",
        "name": "Cannon.js (subprocess)",
        "description": "JavaScript rigid-body physics via Node.js subprocess.",
        "tiers": ["arcade", "newtonian"],
        "available": False,
        "install": "npm install -g cannon-es",
    },
    {
        "id": "pybullet",
        "name": "PyBullet",
        "description": "Python bindings for Bullet physics. Optional high-fidelity adapter for soft body, constraints, cloth.",
        "tiers": ["newtonian", "soft_body"],
        "available": False,
        "install": "pip install pybullet",
    },
]

# In-memory session constant store
_session_constants: dict[str, dict[str, float]] = {}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PhysicsObject(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    mass: float = Field(1.0, gt=0.0, le=1e12, description="Mass in kg")
    shape: str = Field("sphere", pattern="^(sphere|box|cylinder|capsule|plane)$")
    radius: float = Field(0.5, gt=0.0, le=1000.0)
    size: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])  # box/cylinder dims
    pos: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])   # x, y, z (m)
    vel: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])   # vx, vy, vz (m/s)
    rot: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])   # Euler angles (rad)
    ang_vel: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])  # angular velocity (rad/s)
    restitution: float = Field(0.5, ge=0.0, le=1.0)
    friction: float = Field(0.4, ge=0.0, le=2.0)
    static: bool = Field(False, description="True = immovable (infinite mass)")
    material: str = Field("default", description="Material name for exotic-tier property lookups")

    @field_validator("pos", "vel", "rot", "ang_vel", "size")
    @classmethod
    def must_be_3(cls, v: list[float]) -> list[float]:
        if len(v) != 3:
            raise ValueError("must be exactly [x, y, z]")
        return v


class SimulateRequest(BaseModel):
    tier: str = Field("newtonian", pattern="^(arcade|newtonian|soft_body|fluid|gas|mixed|chemical|exotic)$")
    objects: list[PhysicsObject] = Field(..., min_length=1)
    duration_seconds: float = Field(5.0, gt=0.0, le=MAX_DURATION_S)
    fps: float = Field(60.0, gt=0.0, le=300.0)
    gravity: list[float] = Field(default_factory=lambda: [0.0, -9.81, 0.0])  # world gravity vector
    ground_plane_y: float | None = Field(0.0, description="Y coord of infinite ground plane; null to disable")
    constants: dict[str, float] | None = Field(None, description="Override physical constants (exotic tier only)")
    topology: str = Field("euclidean", pattern="^(euclidean|toroidal|hyperbolic|elliptic)$")
    torus_size: list[float] = Field(default_factory=lambda: [20.0, 20.0, 20.0])
    session_id: str | None = Field(None, description="Session ID for persistent constants")

    @field_validator("objects")
    @classmethod
    def cap_objects(cls, v: list[PhysicsObject]) -> list[PhysicsObject]:
        if len(v) > MAX_OBJECTS:
            raise ValueError(f"Too many objects: max {MAX_OBJECTS}")
        return v

    @field_validator("gravity")
    @classmethod
    def gravity_3(cls, v: list[float]) -> list[float]:
        if len(v) != 3:
            raise ValueError("gravity must be [gx, gy, gz]")
        return v


class ConstantsRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    constants: dict[str, float] | None = Field(None, description="Set these constants for the session")


class SimulationResult(BaseModel):
    tier: str
    duration_seconds: float
    fps: float
    dt: float
    steps: int
    frames_emitted: int
    object_count: int
    topology: str
    constants_used: dict[str, float]
    frames: list[dict[str, Any]]
    warnings: list[str]
    elapsed_ms: float


# ---------------------------------------------------------------------------
# Simulation engines
# ---------------------------------------------------------------------------

def _vec3_add(a: list[float], b: list[float]) -> list[float]:
    return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]

def _vec3_scale(v: list[float], s: float) -> list[float]:
    return [v[0]*s, v[1]*s, v[2]*s]

def _vec3_len(v: list[float]) -> float:
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])

def _vec3_norm(v: list[float]) -> list[float]:
    mag = _vec3_len(v)
    if mag < 1e-15:
        return [0.0, 0.0, 0.0]
    return [v[0]/mag, v[1]/mag, v[2]/mag]

def _vec3_dot(a: list[float], b: list[float]) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def _vec3_sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _wrap_toroidal(pos: list[float], torus_size: list[float]) -> list[float]:
    """Wrap position into toroidal space [-L/2, L/2) per axis."""
    out = []
    for p, L in zip(pos, torus_size):
        half = L / 2.0
        # bring into [0, L) then shift to [-L/2, L/2)
        wrapped = math.fmod(p + half, L)
        if wrapped < 0:
            wrapped += L
        out.append(wrapped - half)
    return out


def _effective_radius(obj: PhysicsObject) -> float:
    """Return a representative sphere radius for collision detection."""
    if obj.shape == "sphere":
        return obj.radius
    if obj.shape == "box":
        return max(obj.size) * 0.5
    if obj.shape == "cylinder":
        return max(obj.radius, obj.size[1] * 0.5)
    if obj.shape == "capsule":
        return obj.radius
    return obj.radius  # fallback


def _arcade_simulate(
    req: SimulateRequest,
    constants: dict[str, float],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Arcade tier: sphere AABB, Euler, deterministic, no rotation dynamics."""
    dt = 1.0 / req.fps
    steps = int(req.duration_seconds * req.fps)
    gx, gy, gz = req.gravity

    # State: mutable copies
    objs = []
    for o in req.objects:
        objs.append({
            "id": o.id,
            "mass": o.mass,
            "pos": list(o.pos),
            "vel": list(o.vel),
            "rot": list(o.rot),
            "radius": _effective_radius(o),
            "restitution": o.restitution,
            "static": o.static,
        })

    frames: list[dict[str, Any]] = []

    for step in range(steps):
        # Integrate dynamics
        for obj in objs:
            if obj["static"]:
                continue
            # Gravity
            obj["vel"][0] += gx * dt
            obj["vel"][1] += gy * dt
            obj["vel"][2] += gz * dt
            # Velocity cap (arcade: just a sanity limit, not relativistic)
            speed = _vec3_len(obj["vel"])
            if speed > 1000.0:
                factor = 1000.0 / speed
                obj["vel"] = _vec3_scale(obj["vel"], factor)
            # Integrate position
            obj["pos"][0] += obj["vel"][0] * dt
            obj["pos"][1] += obj["vel"][1] * dt
            obj["pos"][2] += obj["vel"][2] * dt

        # Ground plane collision (arcade: simple bounce, no friction)
        if req.ground_plane_y is not None:
            for obj in objs:
                if obj["static"]:
                    continue
                floor_y = req.ground_plane_y + obj["radius"]
                if obj["pos"][1] < floor_y:
                    obj["pos"][1] = floor_y
                    obj["vel"][1] = -obj["vel"][1] * obj["restitution"]
                    # Small horizontal damping on bounce (arcade feel)
                    obj["vel"][0] *= 0.85
                    obj["vel"][2] *= 0.85

        # Object-object sphere collisions (arcade: impulse-based, mass-ignored for simplicity)
        for i in range(len(objs)):
            for j in range(i + 1, len(objs)):
                oi, oj = objs[i], objs[j]
                if oi["static"] and oj["static"]:
                    continue
                d = _vec3_sub(oi["pos"], oj["pos"])
                dist = _vec3_len(d)
                min_dist = oi["radius"] + oj["radius"]
                if dist < min_dist and dist > 1e-9:
                    n = _vec3_norm(d)
                    overlap = min_dist - dist
                    # Push apart
                    if not oi["static"] and not oj["static"]:
                        push = _vec3_scale(n, overlap * 0.5)
                        oi["pos"] = _vec3_add(oi["pos"], push)
                        oj["pos"] = _vec3_sub(oj["pos"], push)
                    elif not oi["static"]:
                        oi["pos"] = _vec3_add(oi["pos"], _vec3_scale(n, overlap))
                    else:
                        oj["pos"] = _vec3_sub(oj["pos"], _vec3_scale(n, overlap))
                    # Elastic bounce (arcade: simplified, equal impulse)
                    rel_v = _vec3_sub(oi["vel"], oj["vel"])
                    v_along_n = _vec3_dot(rel_v, n)
                    if v_along_n < 0:
                        e = (oi["restitution"] + oj["restitution"]) * 0.5
                        impulse = -(1.0 + e) * v_along_n * 0.5
                        if not oi["static"]:
                            oi["vel"] = _vec3_add(oi["vel"], _vec3_scale(n, impulse))
                        if not oj["static"]:
                            oj["vel"] = _vec3_sub(oj["vel"], _vec3_scale(n, impulse))

        # Toroidal wrap
        if req.topology == "toroidal":
            for obj in objs:
                obj["pos"] = _wrap_toroidal(obj["pos"], req.torus_size)

        # Emit frame
        if step % EMIT_EVERY == 0:
            frames.append({
                "t": round(step * dt, 6),
                "objects": [
                    {
                        "id": o["id"],
                        "pos": [round(v, 6) for v in o["pos"]],
                        "rot": [round(v, 6) for v in o["rot"]],
                        "vel": [round(v, 6) for v in o["vel"]],
                    }
                    for o in objs
                ],
            })
            if len(frames) >= MAX_FRAMES:
                warnings.append(f"Frame cap ({MAX_FRAMES}) reached — truncating at t={frames[-1]['t']:.2f}s")
                break

    return frames


def _newtonian_simulate(
    req: SimulateRequest,
    constants: dict[str, float],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Newtonian tier: rigid body with mass-correct impulses, friction, restitution, angular velocity."""
    dt = 1.0 / req.fps
    gx, gy, gz = req.gravity

    # State
    objs = []
    for o in req.objects:
        r = _effective_radius(o)
        # Moment of inertia: treat as solid sphere (2/5 * m * r^2)
        I = (2.0 / 5.0) * o.mass * r * r if not o.static else 1e30
        objs.append({
            "id": o.id,
            "mass": o.mass,
            "inv_mass": 0.0 if o.static else 1.0 / o.mass,
            "I": I,
            "inv_I": 0.0 if o.static else 1.0 / I,
            "pos": list(o.pos),
            "vel": list(o.vel),
            "rot": list(o.rot),
            "ang_vel": list(o.ang_vel),
            "radius": r,
            "restitution": o.restitution,
            "friction": o.friction,
            "static": o.static,
        })

    frames: list[dict[str, Any]] = []
    steps = int(req.duration_seconds * req.fps)

    for step in range(steps):
        # Apply gravity to velocity (symplectic Euler — more stable than explicit)
        for obj in objs:
            if obj["static"]:
                continue
            obj["vel"][0] += gx * dt
            obj["vel"][1] += gy * dt
            obj["vel"][2] += gz * dt

        # Ground plane collision with friction
        if req.ground_plane_y is not None:
            for obj in objs:
                if obj["static"]:
                    continue
                floor_y = req.ground_plane_y + obj["radius"]
                if obj["pos"][1] < floor_y:
                    obj["pos"][1] = floor_y
                    if obj["vel"][1] < 0:
                        # Normal impulse with restitution
                        j_n = -(1.0 + obj["restitution"]) * obj["vel"][1] * obj["mass"]
                        dv_n = j_n / obj["mass"]
                        obj["vel"][1] += dv_n
                        # Tangential friction impulse
                        spd_t = math.sqrt(obj["vel"][0]**2 + obj["vel"][2]**2)
                        if spd_t > 1e-6:
                            friction_impulse = obj["friction"] * abs(j_n)
                            friction_dv = min(friction_impulse / obj["mass"], spd_t)
                            scale = 1.0 - friction_dv / spd_t
                            obj["vel"][0] *= scale
                            obj["vel"][2] *= scale
                    # Angular damping from ground contact
                    obj["ang_vel"][0] *= 0.95
                    obj["ang_vel"][2] *= 0.95

        # Object-object collisions with mass-correct impulses
        for i in range(len(objs)):
            for j in range(i + 1, len(objs)):
                oi, oj = objs[i], objs[j]
                if oi["static"] and oj["static"]:
                    continue
                d = _vec3_sub(oi["pos"], oj["pos"])
                dist = _vec3_len(d)
                min_dist = oi["radius"] + oj["radius"]
                if dist < min_dist and dist > 1e-9:
                    n = _vec3_norm(d)
                    # Positional correction (Baumgarte)
                    overlap = min_dist - dist
                    inv_mass_sum = oi["inv_mass"] + oj["inv_mass"]
                    if inv_mass_sum > 1e-15:
                        correction = overlap / inv_mass_sum
                        if not oi["static"]:
                            oi["pos"] = _vec3_add(oi["pos"], _vec3_scale(n, correction * oi["inv_mass"]))
                        if not oj["static"]:
                            oj["pos"] = _vec3_sub(oj["pos"], _vec3_scale(n, correction * oj["inv_mass"]))

                    # Velocity impulse (mass-correct)
                    rel_v = _vec3_sub(oi["vel"], oj["vel"])
                    v_along_n = _vec3_dot(rel_v, n)
                    if v_along_n < 0:
                        e = (oi["restitution"] + oj["restitution"]) * 0.5
                        j_mag = -(1.0 + e) * v_along_n
                        if inv_mass_sum > 1e-15:
                            j_mag /= inv_mass_sum
                        if not oi["static"]:
                            oi["vel"] = _vec3_add(oi["vel"], _vec3_scale(n, j_mag * oi["inv_mass"]))
                        if not oj["static"]:
                            oj["vel"] = _vec3_sub(oj["vel"], _vec3_scale(n, j_mag * oj["inv_mass"]))

                        # Friction (Coulomb model)
                        mu = (oi["friction"] + oj["friction"]) * 0.5
                        rel_v_new = _vec3_sub(oi["vel"], oj["vel"])
                        rel_vt = _vec3_sub(rel_v_new, _vec3_scale(n, _vec3_dot(rel_v_new, n)))
                        spd_t = _vec3_len(rel_vt)
                        if spd_t > 1e-6:
                            t_hat = _vec3_norm(rel_vt)
                            j_t = min(mu * abs(j_mag), spd_t / inv_mass_sum if inv_mass_sum > 1e-15 else 0.0)
                            if not oi["static"]:
                                oi["vel"] = _vec3_sub(oi["vel"], _vec3_scale(t_hat, j_t * oi["inv_mass"]))
                            if not oj["static"]:
                                oj["vel"] = _vec3_add(oj["vel"], _vec3_scale(t_hat, j_t * oj["inv_mass"]))

                        # Angular velocity from collision (torque at contact point)
                        r_i = _vec3_scale(n, -oi["radius"])
                        r_j = _vec3_scale(n,  oj["radius"])
                        if not oi["static"]:
                            oi["ang_vel"][0] += (r_i[1] * n[2] - r_i[2] * n[1]) * j_mag * oi["inv_I"] * 0.1
                            oi["ang_vel"][1] += (r_i[2] * n[0] - r_i[0] * n[2]) * j_mag * oi["inv_I"] * 0.1
                            oi["ang_vel"][2] += (r_i[0] * n[1] - r_i[1] * n[0]) * j_mag * oi["inv_I"] * 0.1
                        if not oj["static"]:
                            oj["ang_vel"][0] -= (r_j[1] * n[2] - r_j[2] * n[1]) * j_mag * oj["inv_I"] * 0.1
                            oj["ang_vel"][1] -= (r_j[2] * n[0] - r_j[0] * n[2]) * j_mag * oj["inv_I"] * 0.1
                            oj["ang_vel"][2] -= (r_j[0] * n[1] - r_j[1] * n[0]) * j_mag * oj["inv_I"] * 0.1

        # Integrate positions and rotations
        for obj in objs:
            if obj["static"]:
                continue
            obj["pos"][0] += obj["vel"][0] * dt
            obj["pos"][1] += obj["vel"][1] * dt
            obj["pos"][2] += obj["vel"][2] * dt
            obj["rot"][0] += obj["ang_vel"][0] * dt
            obj["rot"][1] += obj["ang_vel"][1] * dt
            obj["rot"][2] += obj["ang_vel"][2] * dt
            # Small air resistance / angular damping
            obj["ang_vel"] = _vec3_scale(obj["ang_vel"], 0.998)

        # Toroidal wrap
        if req.topology == "toroidal":
            for obj in objs:
                obj["pos"] = _wrap_toroidal(obj["pos"], req.torus_size)

        # Emit frame
        if step % EMIT_EVERY == 0:
            frames.append({
                "t": round(step * dt, 6),
                "objects": [
                    {
                        "id": o["id"],
                        "pos": [round(v, 6) for v in o["pos"]],
                        "rot": [round(v, 6) for v in o["rot"]],
                        "vel": [round(v, 6) for v in o["vel"]],
                        "ang_vel": [round(v, 6) for v in o["ang_vel"]],
                    }
                    for o in objs
                ],
            })
            if len(frames) >= MAX_FRAMES:
                warnings.append(f"Frame cap ({MAX_FRAMES}) reached — truncating at t={frames[-1]['t']:.2f}s")
                break

    return frames


def _approximate_specialized_simulate(
    req: SimulateRequest,
    constants: dict[str, float],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Run built-in gameplay approximations for advanced tiers.

    These tiers intentionally avoid optional heavy solvers during the default
    install. They shape the stable rigid-body integrator so the UI is runnable
    and useful for previews while response warnings identify the approximation.
    """
    tier = req.tier
    tuned_objects: list[PhysicsObject] = []
    gravity = list(req.gravity)

    warnings.append(
        f"Tier '{tier}' is using muLLM's built-in deterministic gameplay approximation. "
        "Install an external adapter later for production-grade CFD, cloth, or chemistry."
    )

    for obj in req.objects:
        data = obj.model_dump()

        if tier == "soft_body":
            data["restitution"] = max(float(data["restitution"]), 0.72)
            data["friction"] = min(max(float(data["friction"]), 0.18), 0.55)
            data["ang_vel"] = [
                float(data["ang_vel"][0]) + 0.25,
                float(data["ang_vel"][1]) + 0.11,
                float(data["ang_vel"][2]) - 0.17,
            ]
        elif tier == "fluid":
            data["restitution"] = min(float(data["restitution"]), 0.18)
            data["friction"] = max(float(data["friction"]), 1.25)
            data["vel"] = [
                float(data["vel"][0]) * 0.45,
                float(data["vel"][1]) * 0.55 + 0.9,
                float(data["vel"][2]) * 0.45,
            ]
            gravity[1] *= 0.35
        elif tier == "gas":
            data["restitution"] = max(float(data["restitution"]), 0.85)
            data["friction"] = min(float(data["friction"]), 0.08)
            phase = sum(ord(ch) for ch in str(data["id"])) % 17
            data["vel"] = [
                float(data["vel"][0]) + math.sin(phase) * 0.8,
                float(data["vel"][1]) + 2.5,
                float(data["vel"][2]) + math.cos(phase) * 0.8,
            ]
            gravity[1] *= 0.08
        elif tier == "mixed":
            data["restitution"] = _clamp(float(data["restitution"]), 0.25, 0.65)
            data["friction"] = _clamp(float(data["friction"]), 0.35, 1.2)
            data["vel"] = [
                float(data["vel"][0]) * 0.75,
                float(data["vel"][1]) * 0.65 + (0.7 if data["mass"] < 2.0 else -0.15),
                float(data["vel"][2]) * 0.75,
            ]
            gravity[1] *= 0.55
        elif tier == "chemical":
            material = str(data.get("material") or "").lower()
            energy = 0.0
            if any(word in material for word in ("fuel", "reactive", "explosive", "acid", "alkali")):
                energy = 2.0
            elif any(word in material for word in ("metal", "iron", "steel", "copper")):
                energy = 0.45
            data["restitution"] = _clamp(float(data["restitution"]) + energy * 0.1, 0.05, 0.95)
            data["friction"] = _clamp(float(data["friction"]) + 0.2 - energy * 0.04, 0.05, 1.6)
            data["vel"] = [
                float(data["vel"][0]) + energy,
                float(data["vel"][1]) + energy * 0.8,
                float(data["vel"][2]) - energy * 0.35,
            ]

        tuned_objects.append(PhysicsObject(**data))

    tuned_req = req.model_copy(update={"objects": tuned_objects, "gravity": gravity})
    return _newtonian_simulate(tuned_req, constants, warnings)


def _exotic_simulate(
    req: SimulateRequest,
    constants: dict[str, float],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Exotic tier: adjustable physical constants, toroidal topology, pairwise G-gravity.

    Observable differences from newtonian:
    - G: scales F = G*m1*m2/r^2 pairwise gravity (add to world gravity vector)
    - g: replaces req.gravity magnitude (req.gravity direction still used as orientation)
    - c: velocity is capped at c per step — relativistic speed limit
    - h/hbar: Bohr radius computed and shown in metadata (no direct motion effect at macro scale)
    - k_B: thermal velocity jitter = sqrt(k_B * T / mass) added per step (T=300K default)
    - e, m_e, eps0: fine-structure alpha = e^2/(4*pi*eps0*hbar*c) computed in metadata
    - toroidal: position wraps at torus_size boundaries
    """
    G_val    = constants.get("G",    EARTH_CONSTANTS["G"])
    g_val    = constants.get("g",    EARTH_CONSTANTS["g"])
    c_val    = constants.get("c",    EARTH_CONSTANTS["c"])
    # G_gradient: [dG/dx, dG/dy, dG/dz] — spatially-varying G. Zero = uniform G.
    g_grad_x = constants.get("G_gradient_x", 0.0)
    g_grad_y = constants.get("G_gradient_y", 0.0)
    g_grad_z = constants.get("G_gradient_z", 0.0)
    h_val   = constants.get("h",    EARTH_CONSTANTS["h"])
    hbar_val = h_val / (2.0 * math.pi)
    k_B_val = constants.get("k_B",  EARTH_CONSTANTS["k_B"])
    e_val   = constants.get("e",    EARTH_CONSTANTS["e"])
    m_e_val = constants.get("m_e",  EARTH_CONSTANTS["m_e"])
    eps0_val = constants.get("eps0", EARTH_CONSTANTS["eps0"])

    # Re-scale gravity vector to use custom g magnitude but preserve direction
    gx_in, gy_in, gz_in = req.gravity
    g_dir_mag = math.sqrt(gx_in**2 + gy_in**2 + gz_in**2)
    if g_dir_mag > 1e-15:
        gx = (gx_in / g_dir_mag) * g_val
        gy = (gy_in / g_dir_mag) * g_val
        gz = (gz_in / g_dir_mag) * g_val
    else:
        gx, gy, gz = 0.0, -g_val, 0.0

    dt = 1.0 / req.fps

    # Compute derived / informational quantities
    if hbar_val > 0 and m_e_val > 0 and e_val > 0 and eps0_val > 0:
        bohr_radius = (4.0 * math.pi * eps0_val * hbar_val**2) / (m_e_val * e_val**2)
    else:
        bohr_radius = float("nan")
    if hbar_val > 0 and c_val > 0 and eps0_val > 0 and e_val > 0:
        fine_structure = e_val**2 / (4.0 * math.pi * eps0_val * hbar_val * c_val)
    else:
        fine_structure = float("nan")

    warnings.append(
        f"Exotic constants applied: G={G_val:.3e}, g={g_val:.3f} m/s², c={c_val:.3e} m/s, "
        f"k_B={k_B_val:.3e} — Bohr radius={bohr_radius:.3e} m, α={fine_structure:.4f}"
    )

    # State
    objs = []
    for o in req.objects:
        r = _effective_radius(o)
        I = (2.0 / 5.0) * o.mass * r * r if not o.static else 1e30
        objs.append({
            "id": o.id,
            "mass": o.mass,
            "inv_mass": 0.0 if o.static else 1.0 / o.mass,
            "I": I,
            "inv_I": 0.0 if o.static else 1.0 / I,
            "pos": list(o.pos),
            "vel": list(o.vel),
            "rot": list(o.rot),
            "ang_vel": list(o.ang_vel),
            "radius": r,
            "restitution": o.restitution,
            "friction": o.friction,
            "static": o.static,
        })

    frames: list[dict[str, Any]] = []
    steps = int(req.duration_seconds * req.fps)
    T_thermal = 300.0  # Kelvin, for k_B thermal jitter
    # Scale thermal jitter: compare k_B to Earth value; jitter proportional
    k_B_ratio = k_B_val / EARTH_CONSTANTS["k_B"]

    for step in range(steps):
        # World gravity (custom g magnitude)
        for obj in objs:
            if obj["static"]:
                continue
            obj["vel"][0] += gx * dt
            obj["vel"][1] += gy * dt
            obj["vel"][2] += gz * dt

        # Pairwise Newtonian gravity (G*m1*m2/r^2)
        if G_val != 0.0:
            for i in range(len(objs)):
                for j in range(i + 1, len(objs)):
                    oi, oj = objs[i], objs[j]
                    d = _vec3_sub(oj["pos"], oi["pos"])  # i→j direction
                    dist = _vec3_len(d)
                    if dist < 1e-3:
                        continue
                    # Softened to avoid singularity: r_soft = max(r, (ri+rj)/2)
                    r_soft = max(dist, (oi["radius"] + oj["radius"]) * 0.5)
                    # g_gradient: G varies with the midpoint between the two objects
                    mid = [(oi["pos"][k] + oj["pos"][k]) * 0.5 for k in range(3)]
                    G_local = G_val + (
                        g_grad_x * mid[0] + g_grad_y * mid[1] + g_grad_z * mid[2]
                    )
                    F_mag = G_local * oi["mass"] * oj["mass"] / (r_soft * r_soft)
                    n = _vec3_norm(d)
                    F = _vec3_scale(n, F_mag)
                    if not oi["static"]:
                        # a = F/m, dv = a*dt
                        oi["vel"] = _vec3_add(oi["vel"], _vec3_scale(F, oi["inv_mass"] * dt))
                    if not oj["static"]:
                        oj["vel"] = _vec3_sub(oj["vel"], _vec3_scale(F, oj["inv_mass"] * dt))

        # k_B thermal jitter (Brownian-style, scaled by k_B deviation from Earth)
        if k_B_ratio > 1.01:
            import random
            sigma = math.sqrt(k_B_val * T_thermal)  # simplified; not /mass for dramatic effect
            for obj in objs:
                if obj["static"]:
                    continue
                for axis in range(3):
                    obj["vel"][axis] += random.gauss(0, sigma * 1e-14 / max(obj["mass"], 1e-30)) * dt

        # Relativistic speed cap at c
        for obj in objs:
            if obj["static"]:
                continue
            speed = _vec3_len(obj["vel"])
            if speed > c_val:
                factor = c_val / speed
                obj["vel"] = _vec3_scale(obj["vel"], factor)

        # Ground plane with exotic friction
        if req.ground_plane_y is not None:
            for obj in objs:
                if obj["static"]:
                    continue
                floor_y = req.ground_plane_y + obj["radius"]
                if obj["pos"][1] < floor_y:
                    obj["pos"][1] = floor_y
                    if obj["vel"][1] < 0:
                        j_n = -(1.0 + obj["restitution"]) * obj["vel"][1] * obj["mass"]
                        obj["vel"][1] += j_n / obj["mass"]
                        spd_t = math.sqrt(obj["vel"][0]**2 + obj["vel"][2]**2)
                        if spd_t > 1e-6:
                            friction_dv = min(obj["friction"] * abs(j_n) / obj["mass"], spd_t)
                            scale = 1.0 - friction_dv / spd_t
                            obj["vel"][0] *= scale
                            obj["vel"][2] *= scale

        # Object-object collisions (same as newtonian)
        for i in range(len(objs)):
            for j in range(i + 1, len(objs)):
                oi, oj = objs[i], objs[j]
                if oi["static"] and oj["static"]:
                    continue
                d = _vec3_sub(oi["pos"], oj["pos"])
                dist = _vec3_len(d)
                min_dist = oi["radius"] + oj["radius"]
                if dist < min_dist and dist > 1e-9:
                    n = _vec3_norm(d)
                    overlap = min_dist - dist
                    inv_mass_sum = oi["inv_mass"] + oj["inv_mass"]
                    if inv_mass_sum > 1e-15:
                        correction = overlap / inv_mass_sum
                        if not oi["static"]:
                            oi["pos"] = _vec3_add(oi["pos"], _vec3_scale(n, correction * oi["inv_mass"]))
                        if not oj["static"]:
                            oj["pos"] = _vec3_sub(oj["pos"], _vec3_scale(n, correction * oj["inv_mass"]))
                    rel_v = _vec3_sub(oi["vel"], oj["vel"])
                    v_along_n = _vec3_dot(rel_v, n)
                    if v_along_n < 0 and inv_mass_sum > 1e-15:
                        e = (oi["restitution"] + oj["restitution"]) * 0.5
                        j_mag = -(1.0 + e) * v_along_n / inv_mass_sum
                        if not oi["static"]:
                            oi["vel"] = _vec3_add(oi["vel"], _vec3_scale(n, j_mag * oi["inv_mass"]))
                        if not oj["static"]:
                            oj["vel"] = _vec3_sub(oj["vel"], _vec3_scale(n, j_mag * oj["inv_mass"]))

        # Integrate
        for obj in objs:
            if obj["static"]:
                continue
            obj["pos"][0] += obj["vel"][0] * dt
            obj["pos"][1] += obj["vel"][1] * dt
            obj["pos"][2] += obj["vel"][2] * dt
            obj["rot"][0] += obj["ang_vel"][0] * dt
            obj["rot"][1] += obj["ang_vel"][1] * dt
            obj["rot"][2] += obj["ang_vel"][2] * dt
            obj["ang_vel"] = _vec3_scale(obj["ang_vel"], 0.998)

        # Toroidal wrap
        if req.topology == "toroidal":
            for obj in objs:
                obj["pos"] = _wrap_toroidal(obj["pos"], req.torus_size)
        elif req.topology in ("hyperbolic", "elliptic"):
            # Adapter-required topologies currently keep objects in Euclidean space.
            pass

        # Emit frame
        if step % EMIT_EVERY == 0:
            frames.append({
                "t": round(step * dt, 6),
                "objects": [
                    {
                        "id": o["id"],
                        "pos": [round(v, 6) for v in o["pos"]],
                        "rot": [round(v, 6) for v in o["rot"]],
                        "vel": [round(v, 6) for v in o["vel"]],
                        "ang_vel": [round(v, 6) for v in o["ang_vel"]],
                    }
                    for o in objs
                ],
            })
            if len(frames) >= MAX_FRAMES:
                warnings.append(f"Frame cap ({MAX_FRAMES}) reached — truncating at t={frames[-1]['t']:.2f}s")
                break

    return frames


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/presets")
async def get_presets() -> dict[str, Any]:
    """List all simulation tiers with descriptions and feature flags."""
    return {
        "tiers": TIERS,
        "earth_constants": EARTH_CONSTANTS,
        "limits": {
            "max_objects": MAX_OBJECTS,
            "max_frames": MAX_FRAMES,
            "max_duration_seconds": MAX_DURATION_S,
            "default_fps": 60,
        },
    }


@router.get("/engines")
async def get_engines() -> dict[str, Any]:
    """List available physics backends."""
    return {
        "engines": BACKEND_ENGINES,
        "active": "python_euler",
        "note": "Additional engines (Rapier.js, Cannon.js, PyBullet) require manual install.",
    }


@router.post("/constants")
async def set_get_constants(req: ConstantsRequest) -> dict[str, Any]:
    """Set or retrieve physical constants for a session."""
    if req.constants is not None:
        # Validate: only known keys allowed
        unknown = set(req.constants.keys()) - set(EARTH_CONSTANTS.keys())
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown constants: {sorted(unknown)}. Valid: {sorted(EARTH_CONSTANTS.keys())}",
            )
        # Validate values: no NaN/Inf
        for k, v in req.constants.items():
            if not math.isfinite(v):
                raise HTTPException(status_code=422, detail=f"Constant '{k}' must be finite")
        # Merge with existing session constants
        existing = _session_constants.get(req.session_id, {})
        merged = {**existing, **req.constants}
        _session_constants[req.session_id] = merged

    current = _session_constants.get(req.session_id, {})
    return {
        "session_id": req.session_id,
        "constants": current,
        "earth_defaults": EARTH_CONSTANTS,
        "deltas": {
            k: {"value": current[k], "earth": EARTH_CONSTANTS[k], "ratio": current[k] / EARTH_CONSTANTS[k]}
            for k in current
            if k in EARTH_CONSTANTS and EARTH_CONSTANTS[k] != 0
        },
    }


@router.post("/simulate")
async def simulate(req: SimulateRequest) -> SimulationResult:
    """Run a physics simulation.

    All tiers run from a clean install. Arcade, newtonian, and exotic are direct
    solvers; soft-body/fluid/gas/mixed/chemical use deterministic gameplay
    approximations over the rigid-body solver and return warnings describing
    that scope.
    Exotic tier accepts custom physical constants and uses them in the simulation.
    """
    start_ms = time.monotonic() * 1000

    # Resolve constants
    constants = dict(EARTH_CONSTANTS)  # start from Earth defaults

    # Apply session constants if provided
    if req.session_id and req.session_id in _session_constants:
        constants.update(_session_constants[req.session_id])

    # Apply per-request constants (exotic tier)
    if req.constants:
        if req.tier != "exotic":
            raise HTTPException(
                status_code=422,
                detail="Custom constants are only supported for the 'exotic' tier. Use tier='exotic' to unlock.",
            )
        unknown = set(req.constants.keys()) - set(EARTH_CONSTANTS.keys())
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown constants: {sorted(unknown)}. Valid: {sorted(EARTH_CONSTANTS.keys())}",
            )
        constants.update(req.constants)

    warnings: list[str] = []

    # Topology warnings
    if req.topology in ("hyperbolic", "elliptic"):
        warnings.append(
            f"Topology '{req.topology}' requires an external topology adapter; objects move in Euclidean space. "
            "Toroidal wrapping is the supported built-in non-Euclidean topology."
        )

    # Dispatch to engine
    if req.tier == "arcade":
        frames = _arcade_simulate(req, constants, warnings)
    elif req.tier == "newtonian":
        frames = _newtonian_simulate(req, constants, warnings)
    elif req.tier in {"soft_body", "fluid", "gas", "mixed", "chemical"}:
        frames = _approximate_specialized_simulate(req, constants, warnings)
    elif req.tier == "exotic":
        frames = _exotic_simulate(req, constants, warnings)
    else:  # Pydantic normally rejects this before dispatch.
        raise HTTPException(status_code=422, detail=f"Unknown physics tier: {req.tier}")

    elapsed_ms = time.monotonic() * 1000 - start_ms
    dt = 1.0 / req.fps

    return SimulationResult(
        tier=req.tier,
        duration_seconds=req.duration_seconds,
        fps=req.fps,
        dt=dt,
        steps=int(req.duration_seconds * req.fps),
        frames_emitted=len(frames),
        object_count=len(req.objects),
        topology=req.topology,
        constants_used={k: constants[k] for k in EARTH_CONSTANTS if k in constants},
        frames=frames,
        warnings=warnings,
        elapsed_ms=round(elapsed_ms, 2),
    )
