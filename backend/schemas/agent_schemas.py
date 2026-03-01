from pydantic import BaseModel, Field
from typing import List, Optional

class DatasheetInfo(BaseModel):
    name: str
    url: str
    pdf_path: Optional[str] = None
    description: Optional[str] = None

class ComponentRecommendation(BaseModel):
    name: str
    reason: str
    datasheet_url: Optional[str] = None

class DataExtractionOutput(BaseModel):
    datasheet_pdfs: List[str]  # URLs or storage paths
    component_stls: List[str]  # URLs or storage paths
    datasheet_contents: List[str] = []  # base64-encoded PDF contents
    stl_contents: List[str] = []  # base64-encoded STL contents
    recommendations: List[ComponentRecommendation]
    metadata: dict

class SpecGeneratorOutput(BaseModel):
    design_spec_summary: str
    parts_required: List[str]
    viable: bool
    reasoning: str

class ElectronicsOutput(BaseModel):
    schematic_pdf_url: str
    instructions: str
    code: str
    firmware_code: str = ""
    metadata: dict


# ── Assembly Agent Schemas ──────────────────────────────────────────

class ComponentBounds(BaseModel):
    """Bounding-box dimensions extracted from an STL file."""
    filename: str
    width: float = Field(description="X-axis extent in mm")
    depth: float = Field(description="Y-axis extent in mm")
    height: float = Field(description="Z-axis extent in mm")
    min_point: List[float] = Field(description="[x, y, z] min corner")
    max_point: List[float] = Field(description="[x, y, z] max corner")


class ComponentPlacement(BaseModel):
    """Where and how a single component is placed inside the assembly."""
    component_file: str = Field(description="STL filename from cad_library/components")
    position: List[float] = Field(description="[x, y, z] translation in mm")
    rotation: List[float] = Field(default=[0, 0, 0], description="[rx, ry, rz] rotation in degrees")
    label: str = Field(default="", description="Human-readable label for this placement")


class AssemblyOutput(BaseModel):
    """Full output of the Assembly Agent."""
    openscad_code: str = Field(description="Complete OpenSCAD script for the assembly")
    scad_file_path: str = Field(description="Path where the .scad file was saved")
    stl_full_path: Optional[str] = Field(default=None, description="STL of full assembly (housing + electronics)")
    stl_housing_path: Optional[str] = Field(default=None, description="STL of housing only (no electronics)")
    stl_full_base64: Optional[str] = Field(default=None, description="Base64-encoded STL of full assembly")
    stl_housing_base64: Optional[str] = Field(default=None, description="Base64-encoded STL of housing only")
    placements: List[ComponentPlacement] = Field(description="Placement details for every component")
    housing_dimensions: List[float] = Field(description="[width, depth, height] of the generated housing in mm")
    overlap_free: bool = Field(description="Whether all placements passed the overlap check")
    components_inside: bool = Field(description="Whether all components are within the housing interior")
    physically_feasible: bool = Field(description="Whether all components are properly supported (not floating)")
    preview_png_path: Optional[str] = Field(default=None, description="Path to rendered preview image, if available")
    design_notes: str = Field(default="", description="Agent reasoning / design notes")
