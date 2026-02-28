import asyncio
import os
import json
from dotenv import load_dotenv

# Set up environment
load_dotenv()

# Add the current directory to sys.path to handle relative imports if running directly
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.spec_generator import SpecGeneratorAgent
from backend.agents.data_extraction import DataExtractionAgent

async def test_pipeline():
    # Sample user prompt for a hackathon project
    sample_prompt = "I want to build an automated plant watering system using an ESP32, a capacitive soil moisture sensor, and a 5V relay to control a water pump."
    
    print(f"--- TESTING PIPELINE WITH PROMPT ---{sample_prompt}")

    # Initialize agents
    spec_agent = SpecGeneratorAgent()
    data_agent = DataExtractionAgent()

    # 1. Test Spec Generator Agent
    print("--- Testing Spec Generator Agent ---")
    try:
        spec_output = await spec_agent.generate_spec(sample_prompt)
        print("Spec Generator Output:")
        print(json.dumps(spec_output.dict(), indent=2))
    except Exception as e:
        print(f"Spec Generator Error: {e}")

    print("\n" + "="*50 + "\n")

    # 2. Test Data Extraction Agent
    print("--- Testing Data Extraction Agent ---")
    try:
        # This will perform web searches and attempt downloads/uploads
        data_output = await data_agent.extract_and_fetch(sample_prompt)
        print("Data Extraction Output:")
        print(json.dumps(data_output.dict(), indent=2))
    except Exception as e:
        print(f"Data Extraction Error: {e}")

if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("CRITICAL: Please set ANTHROPIC_API_KEY in backend/.env before running this test.")
    else:
        asyncio.run(test_pipeline())
