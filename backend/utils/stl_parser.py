"""
Utilities for reading STL files and extracting geometric metadata
used by the Assembly Agent.
"""

import os
from typing import List, Dict, Any, Tuple
from stl import mesh  # numpy-stl
import numpy as np

from schemas.agent_schemas import ComponentBounds


def flat_rotation_for(bounds: ComponentBounds) -> Dict[str, Any]:
    """Return the rotation needed to lay a component flat (smallest dim → Z-axis)
    and the resulting bounding-box dimensions after that rotation.

    OpenSCAD rotation rules (applied BEFORE the normalising translate):
      thickness on X → rotate([0, 90, 0]):  x'= z,  y'= y,  z'=-x
      thickness on Y → rotate([90, 0, 0]):  x'= x,  y'=-z,  z'= y
      thickness on Z → no rotation:          x'= x,  y'= y,  z'= z

    Returns a dict with:
        rotation        – [rx, ry, rz] degrees
        rotated_dims    – [rX, rY, rZ] bounding-box size after rotation
        origin_cancel   – [tx, ty, tz] translate to put rotated min at [0,0,0]
    """
    mn = np.array(bounds.min_point)
    mx = np.array(bounds.max_point)
    dims = np.array([bounds.width, bounds.depth, bounds.height])
    thickness_axis = int(np.argmin(dims))

    if thickness_axis == 0:              # X is thickness → rotate([0,90,0])
        # x'=z, y'=y, z'=-x
        rot_min = np.array([mn[2], mn[1], -mx[0]])
        rot_max = np.array([mx[2], mx[1], -mn[0]])
        rotation = [0, 90, 0]
    elif thickness_axis == 1:            # Y is thickness → rotate([90,0,0])
        # x'=x, y'=-z, z'=y
        rot_min = np.array([mn[0], -mx[2], mn[1]])
        rot_max = np.array([mx[0], -mn[2], mx[1]])
        rotation = [90, 0, 0]
    else:                                # Z already smallest
        rot_min = mn
        rot_max = mx
        rotation = [0, 0, 0]

    rotated_dims = (rot_max - rot_min).tolist()
    origin_cancel = (-rot_min).tolist()

    return {
        "rotation": rotation,
        "rotated_dims": [round(v, 3) for v in rotated_dims],
        "origin_cancel": [round(v, 3) for v in origin_cancel],
    }


def parse_stl(filepath: str) -> ComponentBounds:
    """
    Load an STL file and return its bounding-box dimensions.
    All values are in the same unit as the STL (typically mm).
    """
    stl_mesh = mesh.Mesh.from_file(filepath)

    min_point = stl_mesh.vectors.reshape(-1, 3).min(axis=0)
    max_point = stl_mesh.vectors.reshape(-1, 3).max(axis=0)
    dims = max_point - min_point

    return ComponentBounds(
        filename=os.path.basename(filepath),
        width=float(dims[0]),
        depth=float(dims[1]),
        height=float(dims[2]),
        min_point=min_point.tolist(),
        max_point=max_point.tolist(),
    )


def load_all_components(components_dir: str) -> List[ComponentBounds]:
    """
    Scan a directory for .stl files and return bounding-box info for each.
    """
    bounds: List[ComponentBounds] = []
    for fname in sorted(os.listdir(components_dir)):
        if fname.lower().endswith(".stl"):
            filepath = os.path.join(components_dir, fname)
            bounds.append(parse_stl(filepath))
    return bounds


def check_overlap(placements: List[Dict[str, Any]], bounds_map: Dict[str, ComponentBounds]) -> bool:
    """Return True when NO bounding-box overlaps exist.

    ``position`` is treated as the **min corner** of the placed, normalised
    component.  ``rotated_dims`` (if present in the placement) is used as the
    component size; otherwise the raw STL dims are used as a conservative
    over-estimate.
    """
    boxes = []
    for p in placements:
        bounds = bounds_map.get(p["component_file"])
        if bounds is None:
            continue
        pos = np.array(p["position"])
        rdims = p.get("rotated_dims")
        if rdims:
            size = np.array(rdims)
        else:
            size = np.array([bounds.width, bounds.depth, bounds.height])
        box_min = pos
        box_max = pos + size
        boxes.append((box_min, box_max))

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a_min, a_max = boxes[i]
            b_min, b_max = boxes[j]
            if (
                a_min[0] < b_max[0] and a_max[0] > b_min[0]
                and a_min[1] < b_max[1] and a_max[1] > b_min[1]
                and a_min[2] < b_max[2] and a_max[2] > b_min[2]
            ):
                return False
    return True


def check_components_in_bounds(
    placements: List[Dict[str, Any]],
    bounds_map: Dict[str, ComponentBounds],
    housing_dims: List[float],
    wall_thickness: float,
) -> Tuple[bool, List[str]]:
    """Check that every component is fully within the housing interior.

    ``position`` is the min corner of the placed, normalised component.
    Returns (all_inside, violations).
    """
    interior_min = np.array([wall_thickness] * 3)
    interior_max = np.array([
        housing_dims[0] - wall_thickness,
        housing_dims[1] - wall_thickness,
        housing_dims[2] - wall_thickness,
    ])

    violations: List[str] = []
    for p in placements:
        bounds = bounds_map.get(p["component_file"])
        if bounds is None:
            continue
        pos = np.array(p["position"])
        rdims = p.get("rotated_dims")
        if rdims:
            size = np.array(rdims)
        else:
            size = np.array([bounds.width, bounds.depth, bounds.height])

        comp_min = pos
        comp_max = pos + size

        if not (np.all(comp_min >= interior_min - 0.1) and np.all(comp_max <= interior_max + 0.1)):
            violations.append(
                f"{bounds.filename}: min={comp_min.tolist()} max={comp_max.tolist()} "
                f"vs interior [{interior_min.tolist()} → {interior_max.tolist()}]"
            )

    return len(violations) == 0, violations


def check_physical_feasibility(
    placements: List[Dict[str, Any]],
    bounds_map: Dict[str, ComponentBounds],
    housing_dims: List[float],
    wall_thickness: float,
    standoff_height: float = 4.0,
    z_tolerance: float = 2.0,
) -> Tuple[bool, List[str]]:
    """Check that the assembly is physically plausible — no floating parts.

    Rules
    -----
    1. **Supported at floor**: component Z-min must be within ``z_tolerance``
       of either ``wall_thickness`` (floor) or ``wall_thickness + standoff_height``
       (resting on standoffs).  If it is higher than that it is floating in mid-air.
    2. **Not below floor**: component Z-min must be ≥ ``wall_thickness - z_tolerance``.
    3. **Fits below housing ceiling**: component Z-max must be ≤
       ``housing_H - wall_thickness + z_tolerance``.
    4. **Non-zero footprint**: rotated_dims (or raw dims) must all be > 0.

    Returns ``(feasible: bool, violations: list[str])``.
    """
    floor_z     = wall_thickness
    standoff_z  = wall_thickness + standoff_height
    ceiling_z   = housing_dims[2] - wall_thickness

    violations: List[str] = []

    for p in placements:
        bounds = bounds_map.get(p["component_file"])
        if bounds is None:
            continue
        filename = bounds.filename
        pos  = np.array(p["position"], dtype=float)
        rdims = p.get("rotated_dims")
        size = np.array(rdims, dtype=float) if rdims else np.array(
            [bounds.width, bounds.depth, bounds.height], dtype=float
        )

        comp_z_min = pos[2]
        comp_z_max = pos[2] + size[2]

        # Rule 1 — floating check
        on_floor    = abs(comp_z_min - floor_z)    <= z_tolerance
        on_standoff = abs(comp_z_min - standoff_z) <= z_tolerance
        if not (on_floor or on_standoff):
            nearest = "floor" if abs(comp_z_min - floor_z) < abs(comp_z_min - standoff_z) else "standoff"
            expected = floor_z if nearest == "floor" else standoff_z
            violations.append(
                f"{filename}: FLOATING — Z-min={comp_z_min:.2f} mm is {abs(comp_z_min - expected):.2f} mm "
                f"away from expected {nearest} level ({expected:.2f} mm). "
                f"Component appears to be suspended in mid-air."
            )

        # Rule 2 — below floor
        if comp_z_min < floor_z - z_tolerance:
            violations.append(
                f"{filename}: BELOW FLOOR — Z-min={comp_z_min:.2f} mm is below the "
                f"inner floor (wall={wall_thickness:.2f} mm)."
            )

        # Rule 3 — above ceiling
        if comp_z_max > ceiling_z + z_tolerance:
            violations.append(
                f"{filename}: EXCEEDS HOUSING — Z-max={comp_z_max:.2f} mm is above "
                f"the housing interior ceiling ({ceiling_z:.2f} mm). "
                f"Lid will not close."
            )

        # Rule 4 — degenerate component
        if np.any(size <= 0):
            violations.append(
                f"{filename}: DEGENERATE — one or more rotated_dims are ≤ 0: {size.tolist()}."
            )

    return len(violations) == 0, violations
