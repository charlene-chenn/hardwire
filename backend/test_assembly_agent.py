import asyncio
import os
import json
from dotenv import load_dotenv

# Set up environment
load_dotenv()

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.assembly_agent import AssemblyAgent

async def test_assembly_agent():
    # Sample prompt and (optionally) schematic
    sample_prompt = "Design a compact enclosure for a ESP-32 and a dh22 temperature sensor. The enclosure should have ventilation slots."
    # Place a few sample STL files in cad_library/components/ before running this test
    agent = AssemblyAgent()

    print("--- Testing AssemblyAgent ---")
    try:
        result = await agent.design_assembly(
            user_prompt=sample_prompt,
            schematic_paths=None,  # Or provide a list of image paths
            component_files=None,  # Or filter specific STL filenames
            wall_thickness=2.5,
            clearance=1.5,
        )
        print("AssemblyAgent Output:")
        print(json.dumps(result.model_dump(), indent=2))
        # Basic assertions
        assert result.openscad_code.strip() != ""
        assert result.scad_file_path.endswith(".scad")
        assert len(result.placements) > 0

        # Report validation
        if not result.overlap_free:
            print("⚠️  Warning: Component overlaps detected!")
        if not result.components_inside:
            print("⚠️  WARNING: Components are OUTSIDE the housing!")
        if not result.physically_feasible:
            print("⚠️  WARNING: Physical feasibility issues (floating/unsupported parts)!")
        if result.overlap_free and result.components_inside and result.physically_feasible:
            print("✅ All validation checks passed!")

        print(f"\n📦 Housing dimensions: {result.housing_dimensions} mm")
        print(f"📍 Components placed: {len(result.placements)}")
        print(f"📄 File: {result.scad_file_path}")
        print("Test passed!")
    except Exception as e:
        print(f"AssemblyAgent Error: {e}")

if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("CRITICAL: Please set ANTHROPIC_API_KEY in backend/.env before running this test.")
    else:
        asyncio.run(test_assembly_agent())
