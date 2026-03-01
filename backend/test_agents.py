import asyncio
import os
import json
from dotenv import load_dotenv

# Set up environment
load_dotenv()

# Add the current directory to sys.path to handle relative imports if running directly
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.data_extraction import DataExtractionAgent
from backend.agents.electronics_agent import ElectronicsAgent
from backend.agents.spec_generator import SpecGeneratorAgent

async def test_pipeline():
    sample_prompt = "I want to build an automated plant watering system using an ESP32, a capacitive soil moisture sensor, and a 5V relay to control a water pump."

    print(f"--- TESTING DATA EXTRACTION ---\n{sample_prompt}\n")

    data_agent = DataExtractionAgent()
    spec_agent = SpecGeneratorAgent()
    electronics_agent = ElectronicsAgent()

    # 1. Data extraction
    try:
        data_output = await data_agent.extract_and_fetch(sample_prompt)
        print("\nData Extraction Output:")
        print(f"  Datasheets fetched : {len(data_output.datasheet_pdfs)}")
        print(f"  STLs fetched       : {len(data_output.component_stls)}")
        print(f"  Components found   : {data_output.metadata.get('extracted_components')}")
        print(f"  Recommendations    : {[r.name for r in data_output.recommendations]}")
        for url in data_output.datasheet_pdfs:
            print(f"  PDF URL: {url}")
        for url in data_output.component_stls:
            print(f"  STL URL: {url}")
    except Exception as e:
        import traceback
        print(f"Data Extraction Error: {e}")
        traceback.print_exc()
        return

    print("\n" + "="*50 + "\n")

    # 2. Spec generation (needed as input to electronics agent)
    try:
        spec_output = await spec_agent.generate_spec(sample_prompt)
        print("Spec generated.")
    except Exception as e:
        import traceback
        print(f"Spec Generator Error: {e}")
        traceback.print_exc()
        return

    print("\n" + "="*50 + "\n")

    # 3. Electronics agent — datasheet fetch only
    print("--- TESTING ELECTRONICS AGENT (datasheet fetch) ---")
    try:
        electronics_output = await electronics_agent.generate_design(spec_output, data_output)
        print(f"  Fetched components: {electronics_output.metadata.get('fetched_components')}")
    except Exception as e:
        import traceback
        print(f"Electronics Agent Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("CRITICAL: Please set ANTHROPIC_API_KEY in backend/.env before running this test.")
    else:
        asyncio.run(test_pipeline())
