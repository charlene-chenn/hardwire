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
