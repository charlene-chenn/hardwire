from fastapi import FastAPI, HTTPException, Body, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
import asyncio
import uvicorn
from typing import Dict, Any, List, Optional

from schemas.agent_schemas import DataExtractionOutput, SpecGeneratorOutput, AssemblyOutput
from agents.data_extraction import DataExtractionAgent
from agents.spec_generator import SpecGeneratorAgent
from agents.electronics_agent import ElectronicsAgent
from agents.assembly_agent import AssemblyAgent
from services.supabase_service import SupabaseService

load_dotenv()

app = FastAPI(title="HARDWIRE Multi-Agent Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory agent instances
data_extraction_agent = DataExtractionAgent()
spec_generator_agent = SpecGeneratorAgent()
electronics_agent = ElectronicsAgent()
assembly_agent = AssemblyAgent()
supabase_service = SupabaseService()

@app.get("/")
async def root():
    return {"message": "HARDWIRE API is running."}

@app.post("/process-pipeline")
async def process_pipeline(prompt: str = Body(..., embed=True)) -> Dict[str, Any]:
    """
    Main pipeline entry point.
    Runs Data Extraction and Spec Generation agents in parallel.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set.")

    try:
        # Run agents in parallel
        # Note: In a production environment, you might use a task queue or background tasks.
        results = await asyncio.gather(
            data_extraction_agent.extract_and_fetch(prompt),
            spec_generator_agent.generate_spec(prompt),
        )

        extraction_result = results[0]
        spec_result = results[1]

        # 3. Electronics Design (Schematic, Instructions, Code)
        electronics_result = await electronics_agent.generate_design(
            spec_result, 
            extraction_result
        )

        combined_payload = {
            "prompt": prompt,
            "extraction": extraction_result.dict(),
            "spec": spec_result.dict(),
            "design": electronics_result.dict(),
        }

        # Save to Supabase (Mocked if no credentials)
        supabase_service.save_data("pipeline_results", combined_payload)

        return combined_payload

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/design-assembly")
async def design_assembly(
    prompt: str = Form(...),
    wall_thickness: float = Form(2.0),
    clearance: float = Form(1.0),
    component_files: Optional[str] = Form(None, description="Comma-separated STL filenames, or omit to use all"),
    component_stl_urls: Optional[str] = Form(None, description="Comma-separated Supabase STL URLs (from data_output.component_stls)"),
    schematics: List[UploadFile] = File(default=[]),
) -> Dict[str, Any]:
    """
    Assembly Agent endpoint.
    Reads STLs from cad_library/components or downloads them from Supabase URLs,
    accepts optional schematic uploads and a text prompt, then generates an
    OpenSCAD assembly with housing.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set.")

    try:
        # Save uploaded schematics to a temp location
        schematic_paths: List[str] = []
        temp_dir = os.path.join(os.path.dirname(__file__), "cad_library", "temp_schematics")
        os.makedirs(temp_dir, exist_ok=True)

        for schematic in schematics:
            fpath = os.path.join(temp_dir, schematic.filename)
            with open(fpath, "wb") as f:
                f.write(await schematic.read())
            schematic_paths.append(fpath)

        # Parse optional component filter
        comp_files = None
        if component_files:
            comp_files = [c.strip() for c in component_files.split(",") if c.strip()]

        # Parse optional Supabase STL URLs
        stl_urls = None
        if component_stl_urls:
            stl_urls = [u.strip() for u in component_stl_urls.split(",") if u.strip()]

        result: AssemblyOutput = await assembly_agent.design_assembly(
            user_prompt=prompt,
            schematic_paths=schematic_paths if schematic_paths else None,
            component_files=comp_files,
            component_stl_urls=stl_urls,
            wall_thickness=wall_thickness,
            clearance=clearance,
        )

        # Clean up temp schematics
        for p in schematic_paths:
            if os.path.isfile(p):
                os.remove(p)

        return result.dict()

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/stl-model")
async def stl_model(prompt: str = Body(..., embed=True)) -> Dict[str, Any]:
    """
    STL model generation entry point.
    Returns base64-encoded STL in the JSON response body.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set.")

    try:
        assembly_output: AssemblyOutput = await assembly_agent.design_assembly(
            user_prompt=prompt
        )

        supabase_payload = {
            "prompt": prompt,
            "design_stl_file": assembly_output.stl_housing_base64,
        }
        supabase_service.save_data("pipeline_results_abc", supabase_payload)

        return JSONResponse(content={
            "prompt": prompt,
            "design_stl_file": assembly_output.stl_full_base64,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)