"""
Assembly Agent
==============
Takes component STL files, optional schematics, and a text prompt, then
generates an OpenSCAD assembly with a housing/enclosure where all
components are placed without overlap.
"""

import os
import json
import re
import base64
import shutil
import subprocess
from typing import List, Optional
from datetime import datetime

import anthropic
import httpx
from dotenv import load_dotenv

from schemas.agent_schemas import (
    AssemblyOutput,
    ComponentBounds,
    ComponentPlacement,
)
from utils.stl_parser import (
    load_all_components, check_overlap, check_components_in_bounds,
    check_physical_feasibility, flat_rotation_for
)

load_dotenv()

# Directories (relative to project root)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENTS_DIR = os.path.join(_BACKEND_DIR, "cad_library", "components")
ASSEMBLED_DIR = os.path.join(_BACKEND_DIR, "cad_library", "assembled")


class AssemblyAgent:
    """
    Uses Claude to design an OpenSCAD assembly/housing that integrates
    component STL files from cad_library/components.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-6"

    # ── public entry point ──────────────────────────────────────────

    async def design_assembly(
        self,
        user_prompt: str,
        schematic_paths: Optional[List[str]] = None,
        component_files: Optional[List[str]] = None,
        component_stl_urls: Optional[List[str]] = None,
        wall_thickness: float = 2.0,
        clearance: float = 1.0,
    ) -> AssemblyOutput:
        """
        Parameters
        ----------
        user_prompt : str
            Free-text description of the desired assembly / housing.
        schematic_paths : list[str] | None
            Paths to schematic images (PNG/JPG) to include as visual context.
        component_files : list[str] | None
            Explicit list of STL filenames inside cad_library/components.
            If None, every STL in the directory is used.
        component_stl_urls : list[str] | None
            Public URLs of STL files stored in Supabase (data_output.component_stls).
            Each file is downloaded into cad_library/components before assembly
            and removed afterwards.
        wall_thickness : float
            Default enclosure wall thickness in mm.
        clearance : float
            Minimum clearance between components in mm.
        """

        # 1a. Download STLs from Supabase URLs into COMPONENTS_DIR
        downloaded_files: List[str] = []
        if component_stl_urls:
            downloaded_files = await self._download_stls_from_urls(component_stl_urls)

        try:
            # 1b. Discover and measure components
            all_bounds = load_all_components(COMPONENTS_DIR)
            if component_files:
                # Fuzzy match: accept a component if its filename stem appears
                # anywhere in any requested name, or vice-versa.  This handles
                # LLM variants like "ESP32 DevKit" matching "esp32.stl" and
                # "Arduino Uno R3" matching "arduino_uno.stl".
                normalised_requests = [a.lower().replace(" ", "_") for a in component_files]
                def _fuzzy_match(filename_stem: str) -> bool:
                    for req in normalised_requests:
                        if filename_stem in req or req in filename_stem:
                            return True
                    return False
                all_bounds = [
                    b for b in all_bounds
                    if _fuzzy_match(b.filename.lower().replace(".stl", ""))
                ]
            print("all_bounds:", all_bounds)

            # if not all_bounds:
            #     raise ValueError("No STL components found in cad_library/components/")

            bounds_map = {b.filename: b for b in all_bounds}

            # 2. Build the messages payload
            messages = self._build_messages(
                user_prompt=user_prompt,
                bounds=all_bounds,
                schematic_paths=schematic_paths or [],
                wall_thickness=wall_thickness,
                clearance=clearance,
            )

            # 3. Call Claude with tool use
            response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=self._system_prompt(),
            messages=messages,
                tools=[self._assembly_tool_schema()],
                tool_choice={"type": "tool", "name": "output_assembly"},
            )

            tool_use = next(b for b in response.content if b.type == "tool_use")
            data = tool_use.input

            # 4. Extract placements and run all geometry checks
            placements_raw = data.get("placements", [])
            housing_dims = data.get("housing_dimensions", [0, 0, 0])
            standoff_h = data.get("standoff_height", 4.0)
            overlap_free = check_overlap(placements_raw, bounds_map)

            # 4b. Check components are inside the housing
            components_inside, bound_violations = check_components_in_bounds(
                placements_raw, bounds_map, housing_dims, wall_thickness
            )

            # 4c. Physical feasibility — no floating parts
            physically_feasible, feasibility_violations = check_physical_feasibility(
                placements_raw, bounds_map, housing_dims, wall_thickness,
                standoff_height=standoff_h,
            )

            # Retry once if any check fails
            violations = bound_violations + feasibility_violations
            if not overlap_free or not components_inside or not physically_feasible:
                data, overlap_free, components_inside, physically_feasible = await self._retry_fix_issues(
                    data, all_bounds, bounds_map, user_prompt,
                    wall_thickness, clearance, overlap_free,
                    components_inside, physically_feasible, violations,
                )
                placements_raw = data.get("placements", [])
                housing_dims = data.get("housing_dimensions", [0, 0, 0])

            # 5. Build the full OpenSCAD script (Claude provides it, but we
            #    ensure import paths are absolute so openscad can resolve them)
            openscad_code = self._fixup_import_paths(data.get("openscad_code", ""))

            # 6. Save .scad file
            os.makedirs(ASSEMBLED_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            scad_filename = f"assembly_{timestamp}.scad"
            scad_path = os.path.join(ASSEMBLED_DIR, scad_filename)
            with open(scad_path, "w") as f:
                f.write(openscad_code)

            # 7. Export STLs (full assembly + housing-only) and render preview
            stl_full_path, stl_housing_path = self._export_stls(scad_path)
            preview_path = self._render_preview(scad_path)

            # 7b. Encode exported STLs as base64 for API response
            stl_full_base64 = None
            stl_housing_base64 = None
            if stl_full_path and os.path.isfile(stl_full_path):
                with open(stl_full_path, "rb") as f:
                    stl_full_base64 = base64.b64encode(f.read()).decode("utf-8")
            if stl_housing_path and os.path.isfile(stl_housing_path):
                with open(stl_housing_path, "rb") as f:
                    stl_housing_base64 = base64.b64encode(f.read()).decode("utf-8")

            # 8. Assemble output
            placements = [ComponentPlacement(**p) for p in placements_raw]
            housing_dims = data.get("housing_dimensions", [0, 0, 0])

            return AssemblyOutput(
                openscad_code=openscad_code,
                scad_file_path=scad_path,
                stl_full_path=stl_full_path,
                stl_housing_path=stl_housing_path,
                stl_full_base64=stl_full_base64,
                stl_housing_base64=stl_housing_base64,
                placements=placements,
                housing_dimensions=housing_dims,
                overlap_free=overlap_free,
                components_inside=components_inside,
                physically_feasible=physically_feasible,
                preview_png_path=preview_path,
                design_notes=data.get("design_notes", ""),
            )

        finally:
            # Clean up any STLs that were downloaded from Supabase URLs
            for fpath in downloaded_files:
                if os.path.isfile(fpath):
                    os.remove(fpath)

    # ── STL downloader ──────────────────────────────────────────────

    @staticmethod
    async def _download_stls_from_urls(urls: List[str]) -> List[str]:
        """
        Fetch STL files from Supabase public URLs into COMPONENTS_DIR.
        Supabase returns base64-encoded content, so each response body is
        decoded before writing the binary STL to disk.
        Returns a list of local file paths that were written so they can
        be cleaned up after assembly.
        """
        os.makedirs(COMPONENTS_DIR, exist_ok=True)
        downloaded: List[str] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for url in urls:
                try:
                    filename = os.path.basename(url.split("?")[0])  # strip query params
                    if not filename.lower().endswith(".stl"):
                        filename += ".stl"
                    dest = os.path.join(COMPONENTS_DIR, filename)
                    response = await client.get(url)
                    response.raise_for_status()
                    # Supabase returns base64-encoded data — decode to raw bytes
                    raw = base64.b64decode(response.content)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    print(f"Downloaded + decoded STL from Supabase: {url} → {dest}")
                    downloaded.append(dest)
                except Exception as e:
                    print(f"Warning: could not download STL from {url}: {e}")
        return downloaded

    # ── prompts & tool schema ───────────────────────────────────────

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are an expert mechanical / enclosure design engineer. "
            "Given a set of electronic components (with pre-computed flat orientations "
            "and rotated dimensions), a user's design intent, and optional schematics, "
            "you produce a complete OpenSCAD script that:\n"
            "1. Imports each component STL via `import()`.\n"
            "2. Places every component INSIDE the housing with no overlaps and at least "
            "the requested clearance between each pair.\n"
            "3. Generates a housing/enclosure (box, rounded, or custom shape) around all "
            "components with mounting standoffs, screw holes, and alignment features.\n"
            "4. Separates lid and base into individual OpenSCAD modules.\n"
            "5. Adds ventilation slots when requested.\n\n"

            "ORIENTATION — LARGEST FACE AT BOTTOM:\n"
            "- Each component comes with a pre-computed rotation and rotated_dims.\n"
            "- USE THEM EXACTLY. Do NOT re-derive orientation.\n"
            "- The rotation places the component so its LARGEST face is on the XY plane "
            "(i.e. it lies flat, smallest dimension becomes Z-height).\n"
            "- Each component module must first apply the rotation, then translate to "
            "cancel the STL origin so the component's min-corner is at [0,0,0]:\n"
            "    module comp_X() { translate(origin_cancel) rotate(rotation) import(...); }\n\n"

            "PLACEMENT — POSITION IS THE MIN CORNER:\n"
            "- `position` [x,y,z] is the MIN corner of the placed component in world space.\n"
            "- Component occupies: [position] to [position + rotated_dims].\n"
            "- DO NOT divide dims by 2. Place min corner at position.\n"
            "- In OpenSCAD: translate([px, py, pz]) comp_module();\n\n"

            "HOUSING SIZING (size the box FIRST):\n"
            "1. Layout: components side-by-side along X.\n"
            "   interior_X = sum(rotated_dims[0]) + clearance × (n-1) + 2×clearance\n"
            "   interior_Y = max(rotated_dims[1]) + 2×clearance\n"
            "   interior_Z = standoff_h + max(rotated_dims[2]) + clearance\n"
            "2. housing_W = interior_X + 2×wall\n"
            "   housing_D = interior_Y + 2×wall\n"
            "   housing_H = interior_Z + wall\n"
            "3. Component base Z: z_base = wall + standoff_h\n"
            "4. First component X: x0 = wall + clearance\n"
            "   Next component X: x0_prev + rotated_dims_prev[0] + clearance\n"
            "5. VERIFY: for every component, "
            "position[i] + rotated_dims[i] ≤ housing_dim[i] - wall (for i in X,Y,Z).\n\n"

            "EXPLODED VIEW:\n"
            "- Base at origin. Components inside base at their positions.\n"
            "- Lid: translate([0, housing_depth * 1.35, 0]) lid();\n\n"

            "Use ONLY `import()` for STL references. All dimensions in mm."
        )

    def _build_messages(
        self,
        user_prompt: str,
        bounds: List[ComponentBounds],
        schematic_paths: List[str],
        wall_thickness: float,
        clearance: float,
        standoff_h: float = 4.0,
    ) -> list:
        """Build the messages array, embedding pre-computed flat orientations."""

        # Pre-compute flat orientation for every component
        orientations = [flat_rotation_for(b) for b in bounds]

        # Pre-compute housing and placement positions deterministically
        rdims_list = [o["rotated_dims"] for o in orientations]
        interior_x = sum(r[0] for r in rdims_list) + clearance * (len(rdims_list) - 1) + 2 * clearance
        interior_y = max(r[1] for r in rdims_list) + 2 * clearance
        interior_z = standoff_h + max(r[2] for r in rdims_list) + clearance
        hw = round(interior_x + 2 * wall_thickness, 2)
        hd = round(interior_y + 2 * wall_thickness, 2)
        hh = round(interior_z + wall_thickness, 2)
        z_base = round(wall_thickness + standoff_h, 2)

        comp_lines = []
        cur_x = wall_thickness + clearance
        for b, o in zip(bounds, orientations):
            rx, ry, rz = o["rotated_dims"]
            oc = o["origin_cancel"]
            rot = o["rotation"]
            px = round(cur_x, 2)
            py = round(wall_thickness + clearance + (max(r[1] for r in rdims_list) - ry) / 2, 2)
            comp_lines.append(
                f"- **{b.filename}**\n"
                f"  - Original dims (X×Y×Z): {b.width:.2f} × {b.depth:.2f} × {b.height:.2f} mm\n"
                f"  - STL min_point: {[round(v,2) for v in b.min_point]}\n"
                f"  - **rotation**: {rot}  (largest face flat on XY)\n"
                f"  - **origin_cancel translate**: {[round(v,2) for v in oc]}\n"
                f"  - **rotated_dims** (X×Y×Z after rotation): {round(rx,2)} × {round(ry,2)} × {round(rz,2)} mm\n"
                f"  - **position** (min corner in housing): [{px}, {py}, {z_base}]\n"
                f"  - Component occupies: X=[{px} → {round(px+rx,2)}], "
                f"Y=[{py} → {round(py+ry,2)}], Z=[{z_base} → {round(z_base+rz,2)}]"
            )
            cur_x += rx + clearance

        text_block = (
            f"## Design Request\n{user_prompt}\n\n"
            f"## Components (pre-computed flat orientations)\n" +
            "\n".join(comp_lines) + "\n\n"
            f"## Pre-computed Housing Dimensions\n"
            f"- housing_width  = {hw} mm  (X)\n"
            f"- housing_depth  = {hd} mm  (Y)\n"
            f"- housing_height = {hh} mm  (Z, base only)\n"
            f"- Interior: [{wall_thickness}, {wall_thickness}, {wall_thickness}] "
            f"to [{hw-wall_thickness}, {hd-wall_thickness}, {hh}]\n"
            f"- z_base (top of standoffs) = {z_base} mm\n\n"
            f"## Enclosure Parameters\n"
            f"- Wall thickness: {wall_thickness} mm\n"
            f"- Clearance: {clearance} mm\n"
            f"- Standoff height: {standoff_h} mm\n\n"
            f"**USE the pre-computed positions and housing dims above exactly.**\n"
            f"Each component module: translate(origin_cancel) rotate(rotation) import(...)\n"
            f"Placement: translate([px, py, z_base]) comp_module();\n\n"
            f"## Component STL directory\n`{COMPONENTS_DIR}`\n\n"
            "Generate the full OpenSCAD assembly."
        )

        content: list = []
        for spath in schematic_paths:
            if os.path.isfile(spath):
                ext = os.path.splitext(spath)[1].lower().lstrip(".")
                media = f"image/{ext}" if ext in ("png", "gif", "webp") else "image/jpeg"
                with open(spath, "rb") as img:
                    b64 = base64.standard_b64encode(img.read()).decode()
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media, "data": b64},
                })
        content.append({"type": "text", "text": text_block})
        return [{"role": "user", "content": content}]

    @staticmethod
    def _assembly_tool_schema() -> dict:
        return {
            "name": "output_assembly",
            "description": (
                "Output the OpenSCAD assembly code, component placement "
                "details, housing dimensions, and design notes."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "openscad_code": {
                        "type": "string",
                        "description": (
                            "Complete, runnable OpenSCAD script. Use import() "
                            "with the absolute path for each component STL."
                        ),
                    },
                    "placements": {
                        "type": "array",
                        "description": "One entry per component.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "component_file": {"type": "string"},
                                "position": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "[x, y, z] MIN CORNER of the placed normalised component in world space",
                                },
                                "rotated_dims": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "[rX, rY, rZ] bounding-box size after rotation",
                                },
                                "rotation": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "[rx, ry, rz] rotation in degrees applied to lay flat",
                                },
                                "label": {"type": "string"},
                            },
                            "required": ["component_file", "position", "rotated_dims"],
                        },
                    },
                    "housing_dimensions": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[width, depth, height] of the enclosure in mm",
                    },
                    "design_notes": {
                        "type": "string",
                        "description": "Reasoning and design decisions.",
                    },
                },
                "required": [
                    "openscad_code",
                    "placements",
                    "housing_dimensions",
                    "design_notes",
                ],
            },
        }

    # ── issue retry ──────────────────────────────────────────────────

    async def _retry_fix_issues(
        self, prev_data, bounds, bounds_map, user_prompt,
        wall_thickness, clearance, overlap_free,
        components_inside, physically_feasible, violations,
    ):
        """Ask Claude to revise placements that overlap, are out of bounds, or are floating."""
        issues = []
        if not overlap_free:
            issues.append("- Component bounding-box OVERLAPS detected.")
        if not components_inside:
            issues.append("- Components are OUTSIDE the housing interior:")
        if not physically_feasible:
            issues.append("- PHYSICAL FEASIBILITY VIOLATIONS (floating/unsupported parts):")
        for v in violations:
            issues.append(f"  • {v}")

        if not components_inside or not physically_feasible:
            issues.append(
                f"  FIX: Ensure every component Z-min equals wall_thickness({wall_thickness}) "
                f"(floor) or wall_thickness + standoff_height (on standoffs). "
                f"INCREASE housing dimensions if component Z-max exceeds housing height."
            )

        fix_prompt = (
            "The placement you generated has these issues:\n"
            + "\n".join(issues) + "\n\n"
            f"Current housing: {prev_data.get('housing_dimensions', [0,0,0])} mm\n"
            f"Current placements:\n```json\n{json.dumps(prev_data['placements'], indent=2)}\n```\n\n"
            "Return a corrected assembly. All components must:\n"
            "  1. Have Z-min = wall_thickness OR wall_thickness + standoff_height (no floating).\n"
            "  2. Fit entirely inside the housing (increase housing dims if needed).\n"
            "  3. Not overlap each other.\n"
        )

        messages = self._build_messages(
            user_prompt=user_prompt,
            bounds=bounds,
            schematic_paths=[],
            wall_thickness=wall_thickness,
            clearance=clearance,
        )
        messages.append({"role": "assistant", "content": json.dumps(prev_data)})
        messages.append({"role": "user", "content": fix_prompt})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=self._system_prompt(),
            messages=messages,
            tools=[self._assembly_tool_schema()],
            tool_choice={"type": "tool", "name": "output_assembly"},
        )

        tool_use = next(b for b in response.content if b.type == "tool_use")
        data = tool_use.input
        housing_dims = data.get("housing_dimensions", [0, 0, 0])
        standoff_h = data.get("standoff_height", 4.0)
        overlap_free = check_overlap(data.get("placements", []), bounds_map)
        components_inside, _ = check_components_in_bounds(
            data.get("placements", []), bounds_map, housing_dims, wall_thickness
        )
        physically_feasible, _ = check_physical_feasibility(
            data.get("placements", []), bounds_map, housing_dims, wall_thickness,
            standoff_height=standoff_h,
        )
        return data, overlap_free, components_inside, physically_feasible

    # ── helpers ─────────────────────────────────────────────────────

    def _fixup_import_paths(self, code: str) -> str:
        """
        Ensure that import() calls reference the absolute path to
        cad_library/components so OpenSCAD can find the STLs.
        Handles both single- and double-quoted paths, relative paths,
        and cases where Claude already wrote an absolute or partial path.
        """
        def _rewrite(match: re.Match) -> str:
            quote = match.group(1)   # ' or "
            inner = match.group(2)   # original path string
            # Keep only the basename so we always resolve from COMPONENTS_DIR
            basename = os.path.basename(inner)
            return f'import({quote}{COMPONENTS_DIR}/{basename}{quote})'

        # Match import('...') and import("...") — any path content
        code = re.sub(r'import\(([\'"])(.*?)[\'"]\)', _rewrite, code)
        return code

    @staticmethod
    def _render_preview(scad_path: str) -> Optional[str]:
        """
        If the `openscad` CLI is available, render an isometric PNG preview.
        Returns the path to the PNG or None.
        """
        if not shutil.which("openscad"):
            return None
        png_path = scad_path.replace(".scad", ".png")
        try:
            subprocess.run(
                [
                    "openscad",
                    "-o", png_path,
                    "--autocenter",
                    "--viewall",
                    "--imgsize=1024,768",
                    scad_path,
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            return png_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _export_stl(scad_path: str) -> Optional[str]:
        """Export the .scad file to STL. Returns path or None."""
        if not shutil.which("openscad"):
            print("  [openscad] not found on PATH — skipping STL export")
            return None
        stl_path = scad_path.replace(".scad", ".stl")
        try:
            result = subprocess.run(
                ["openscad", "-o", stl_path, scad_path],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"  [openscad] export failed (rc={result.returncode}):\n{result.stderr}")
                return None
            return stl_path if os.path.exists(stl_path) else None
        except subprocess.TimeoutExpired:
            print("  [openscad] export timed out")
            return None
        except Exception as e:
            print(f"  [openscad] unexpected error: {e}")
            return None

    @classmethod
    def _export_stls(cls, scad_path: str) -> tuple:
        """Export two STL files from a .scad assembly:

        1. **full assembly** — housing + electronics (everything)
        2. **housing only** — enclosure geometry without any imported STL components

        Returns ``(full_stl_path, housing_stl_path)``; either may be ``None``.
        """
        if not shutil.which("openscad"):
            return None, None

        # ── Full assembly STL ──
        full_stl = cls._export_stl(scad_path)

        # ── Housing-only STL ──
        # Create a modified .scad that comments out every import() call
        # and every line that references the normalised component modules,
        # leaving only the housing/lid geometry.
        try:
            with open(scad_path, "r") as f:
                original = f.read()

            # Replace every import("...") call with cube(0) — a valid no-op geometry
            # so the translate/rotate chains above them don't cause parse errors.
            housing_code = re.sub(
                r'import\s*\([^)]*\)',
                'cube(0)',
                original,
            )

            housing_scad = scad_path.replace(".scad", "_housing.scad")
            with open(housing_scad, "w") as f:
                f.write(housing_code)

            housing_stl = scad_path.replace(".scad", "_housing.stl")
            subprocess.run(
                ["openscad", "-o", housing_stl, housing_scad],
                check=True, capture_output=True, timeout=120,
            )
            # Clean up temp scad
            os.remove(housing_scad)

            housing_stl_result = housing_stl if os.path.exists(housing_stl) else None
        except Exception:
            housing_stl_result = None

        return full_stl, housing_stl_result
