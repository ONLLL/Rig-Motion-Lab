"""Planar math: fixed lengths, explicit reach error, affine transforms.
Adapted from the conversation motion-core reference. No external calls.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable

Vec2 = tuple[float, float]


def finite(*values: float) -> None:
    if not all(math.isfinite(v) for v in values):
        raise ValueError("All numeric inputs must be finite.")


@dataclass(frozen=True)
class IKResult:
    joint: Vec2
    end: Vec2
    requested_end: Vec2
    residual: float
    projected: bool


def two_bone_ik(
    root: Vec2, target: Vec2, upper: float, lower: float,
    bend: int = 1, fallback_direction: Vec2 = (1.0, 0.0),
) -> IKResult:
    """Solve a two-link planar chain without stretching either link.

    bend is the sign of the joint's perpendicular offset from root->target.
    Preserve it across frames unless an authored pose explicitly changes it.
    For a coincident root/target, supply the prior/rest direction as fallback.
    Unreachable targets are projected; callers MUST inspect residual/projected.
    No body correction, anatomical limits, collisions or artistic styling here.
    """
    finite(*root, *target, upper, lower, *fallback_direction)
    if upper <= 0 or lower <= 0 or bend not in (-1, 1):
        raise ValueError("Lengths must be positive; bend must be -1 or +1.")
    total = upper + lower
    finite(total)
    vx, vy = target[0] - root[0], target[1] - root[1]
    distance = math.hypot(vx, vy)
    epsilon = total * 1e-12
    if distance <= epsilon:
        magnitude = math.hypot(*fallback_direction)
        if magnitude <= epsilon:
            raise ValueError("A nonzero fallback direction is required.")
        ux, uy = fallback_direction[0] / magnitude, fallback_direction[1] / magnitude
    else:
        ux, uy = vx / distance, vy / distance
    reach = min(total, max(abs(upper - lower), epsilon, distance))
    # Intersect circles: radius upper around root and lower around projected target.
    along = (upper * upper - lower * lower + reach * reach) / (2.0 * reach)
    height = math.sqrt(max(0.0, upper * upper - along * along))
    knee = (root[0] + along * ux - bend * height * uy,
            root[1] + along * uy + bend * height * ux)
    end = (root[0] + reach * ux, root[1] + reach * uy)
    error = math.hypot(end[0] - target[0], end[1] - target[1])
    return IKResult(knee, end, target, error, error > total * 1e-10)


def hermite(u: float, start: float, end: float,
            start_velocity: float, end_velocity: float, duration: float) -> float:
    """Cubic Hermite segment; velocities are units/second, not units/phase."""
    finite(u, start, end, start_velocity, end_velocity, duration)
    if not 0 <= u <= 1 or duration <= 0:
        raise ValueError("Require 0<=u<=1 and duration>0.")
    u2, u3 = u * u, u * u * u
    return ((2*u3 - 3*u2 + 1)*start + (u3 - 2*u2 + u)*duration*start_velocity
            + (-2*u3 + 3*u2)*end + (u3 - u2)*duration*end_velocity)


@dataclass(frozen=True)
class FootTarget:
    local_ankle: Vec2
    world_ankle: Vec2
    contact: bool
    contact_id: int | None
    root_x: float
    speed: float


def walking_foot(
    time: float, *, period: float = 1.0, stance_fraction: float = 0.6,
    stance_travel: float = 0.18, lift: float = 0.06,
    ankle_height: float = 0.04, phase_offset: float = 0.0,
) -> FootTarget:
    """Basic flat-foot gait target with stationary WORLD-space stance contacts.

    stance_travel is the root-relative travel during stance, not stride length.
    root speed = stance_travel / (stance_fraction * period).
    Swing Hermite end velocities match stance velocity to avoid a velocity jump.
    This is a kinematic template, NOT a learned or biomechanical motion model.
    """
    finite(time, period, stance_fraction, stance_travel, lift, ankle_height, phase_offset)
    if period <= 0 or not 0 < stance_fraction < 1 or stance_travel <= 0 or lift < 0 or ankle_height < 0:
        raise ValueError("Invalid gait parameters.")
    phase_total = time / period + phase_offset
    phase = phase_total % 1.0
    speed = stance_travel / (stance_fraction * period)
    root_x = time * speed
    contact = phase < stance_fraction
    if contact:
        x = stance_travel / 2 - stance_travel * phase / stance_fraction
        y = ankle_height
    else:
        u = (phase - stance_fraction) / (1 - stance_fraction)
        swing_duration = period * (1 - stance_fraction)
        x = hermite(u, -stance_travel / 2, stance_travel / 2,
                    -speed, -speed, swing_duration)
        y = ankle_height + lift * math.sin(math.pi * u)**2
    return FootTarget((x, y), (root_x + x, y), contact,
                      math.floor(phase_total) if contact else None, root_x, speed)


def unwrap_angles(values: Iterable[float]) -> list[float]:
    """Remove +/-pi branch jumps; adjacent true rotations must be below pi."""
    source = list(values)
    finite(*source)
    if not source:
        return []
    output = [source[0]]
    for previous, current in zip(source, source[1:]):
        delta = math.atan2(math.sin(current - previous), math.cos(current - previous))
        output.append(output[-1] + delta)
    return output


def retarget_angles(values: Iterable[float], source_bind: float, target_bind: float) -> list[float]:
    """Transfer local angular change; source_bind is an explicit calibration pose."""
    finite(source_bind, target_bind)
    return [target_bind + angle - source_bind for angle in unwrap_angles(values)]


@dataclass(frozen=True)
class Affine:
    """x'=a*x+c*y+tx, y'=b*x+d*y+ty, using column vectors."""
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def __post_init__(self) -> None:
        finite(self.a, self.b, self.c, self.d, self.tx, self.ty)

    def apply(self, point: Vec2) -> Vec2:
        x, y = point
        finite(x, y)
        return (self.a*x + self.c*y + self.tx, self.b*x + self.d*y + self.ty)

    def __matmul__(self, other: Affine) -> Affine:
        return Affine(self.a*other.a + self.c*other.b,
                      self.b*other.a + self.d*other.b,
                      self.a*other.c + self.c*other.d,
                      self.b*other.c + self.d*other.d,
                      self.a*other.tx + self.c*other.ty + self.tx,
                      self.b*other.tx + self.d*other.ty + self.ty)

    def inverse(self) -> Affine:
        det = self.a*self.d - self.b*self.c
        if abs(det) < 1e-15:
            raise ValueError("Singular or numerically unsafe transform.")
        return Affine(self.d/det, -self.b/det, -self.c/det, self.a/det,
                      (self.c*self.ty - self.d*self.tx)/det,
                      (self.b*self.tx - self.a*self.ty)/det)

    @staticmethod
    def translation(x: float, y: float) -> Affine:
        return Affine(tx=x, ty=y)

    @staticmethod
    def rotation(angle: float) -> Affine:
        finite(angle)
        c, s = math.cos(angle), math.sin(angle)
        return Affine(c, s, -s, c)

    @staticmethod
    def scale(x: float, y: float | None = None) -> Affine:
        return Affine(a=x, d=x if y is None else y)


def attachment_to_canvas(camera: Affine, bone_now: Affine,
                         bone_bind: Affine, image_to_bind_world: Affine) -> Affine:
    """One fixed texture -> rest world -> bone delta -> fixed output canvas.

    image_to_bind_world includes placement/scale and image-Y-down conversion.
    Nothing here measures an alpha bounding box or rescales from current pose.
    For Pillow affine rasterization, use this matrix's INVERSE as the sampler map.
    """
    return camera @ bone_now @ bone_bind.inverse() @ image_to_bind_world
