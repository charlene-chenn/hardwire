from fastapi import FastAPI, HTTPException, Body
from dotenv import load_dotenv
import os
import asyncio
from typing import Dict, Any

from backend.schemas.agent_schemas import DataExtractionOutput, SpecGeneratorOutput
from backend.agents.data_extraction import DataExtractionAgent
from backend.agents.spec_generator import SpecGeneratorAgent
from backend.agents.electronics_agent import ElectronicsAgent
from backend.services.supabase_service import SupabaseService

load_dotenv()

app = FastAPI(title="HARDWIRE Multi-Agent Pipeline")

# In-memory agent instances
data_extraction_agent = DataExtractionAgent()
spec_generator_agent = SpecGeneratorAgent()
electronics_agent = ElectronicsAgent()
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

        # 3. Electronics Design (Schematic, Instructions, Code)
        electronics_result = await electronics_agent.generate_design(
            spec_result, 
            extraction_result
        )

        combined_payload = {
            "prompt": prompt,
            "extraction": extraction_result.dict(),
            "spec": spec_result.dict(),
            "design": electronics_result.dict()
        }

        # Save to Supabase (Mocked if no credentials)
        supabase_service.save_data("pipeline_results", combined_payload)

        return combined_payload

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
