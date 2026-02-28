from fastapi import FastAPI, HTTPException, Body, UploadFile, File, Form
from dotenv import load_dotenv
import os
import asyncio
from typing import Dict, Any, List, Optional

from backend.schemas.agent_schemas import DataExtractionOutput, SpecGeneratorOutput, AssemblyOutput
from backend.agents.data_extraction import DataExtractionAgent
from backend.agents.spec_generator import SpecGeneratorAgent
from backend.agents.assembly_agent import AssemblyAgent
from backend.services.supabase_service import SupabaseService

load_dotenv()

app = FastAPI(title="HARDWIRE Multi-Agent Pipeline")

# In-memory agent instances
data_extraction_agent = DataExtractionAgent()
spec_generator_agent = SpecGeneratorAgent()
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
            spec_generator_agent.generate_spec(prompt)
        )

        extraction_result = results[0]
        spec_result = results[1]

        # For now, we return both. Later, these will be routed to the 'Electronics Guy'.
        # We also want to save the final result to Supabase for record keeping.
        combined_payload = {
            "prompt": prompt,
            "extraction": extraction_result.dict(),
            "spec": spec_result.dict()
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
    schematics: List[UploadFile] = File(default=[]),
) -> Dict[str, Any]:
    """
    Assembly Agent endpoint.
    Reads STLs from cad_library/components, accepts optional schematic uploads
    and a text prompt, then generates an OpenSCAD assembly with housing.
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

        result: AssemblyOutput = await assembly_agent.design_assembly(
            user_prompt=prompt,
            schematic_paths=schematic_paths if schematic_paths else None,
            component_files=comp_files,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
