import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.data_extraction import DataExtractionAgent
from backend.agents.electronics_agent import ElectronicsAgent
from backend.agents.spec_generator import SpecGeneratorAgent

SAMPLE_PROMPT = "I want to build an automated plant watering system using an ESP32, a capacitive soil moisture sensor, and a 5V relay to control a water pump."

def print_section(title: str):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}\n")

from backend.agents.spec_generator import SpecGeneratorAgent

SAMPLE_PROMPT = "I want to build an automated plant watering system using an ESP32, a capacitive soil moisture sensor, and a 5V relay to control a water pump."

def print_section(title: str):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}\n")


async def test_pipeline():
    print(f"PROMPT: {SAMPLE_PROMPT}\n")

    print(f"PROMPT: {SAMPLE_PROMPT}\n")

    data_agent = DataExtractionAgent()
    spec_agent = SpecGeneratorAgent()
    electronics_agent = ElectronicsAgent(use_nemotron=True)

    # -------------------------------------------------------------------------
    # Step 1: Data extraction + Spec generation (parallel)
    # -------------------------------------------------------------------------
    print_section("STEP 1: Data Extraction + Spec Generation (parallel)")
    # -------------------------------------------------------------------------
    # Step 1: Data extraction + Spec generation (parallel)
    # -------------------------------------------------------------------------
    print_section("STEP 1: Data Extraction + Spec Generation (parallel)")
    try:
        data_output, spec_output = await asyncio.gather(
            data_agent.extract_and_fetch(SAMPLE_PROMPT),
            spec_agent.generate_spec(SAMPLE_PROMPT),
        )
        data_output, spec_output = await asyncio.gather(
            data_agent.extract_and_fetch(SAMPLE_PROMPT),
            spec_agent.generate_spec(SAMPLE_PROMPT),
        )
    except Exception as e:
        import traceback
        print(f"Error in parallel step: {e}")
        traceback.print_exc()
        return

    print("Data Extraction:")
    print(f"  Components   : {data_output.metadata.get('extracted_components')}")
    print(f"  Datasheets   : {len(data_output.datasheet_pdfs)}")
    print(f"  STLs         : {len(data_output.component_stls)}")
    print(f"  Recommend.   : {[r.name for r in data_output.recommendations]}")
    for url in data_output.datasheet_pdfs:
        print(f"  PDF URL      : {url}")
    for url in data_output.component_stls:
        print(f"  STL URL      : {url}")

    print("\nSpec Generation:")
    print(f"  Summary      : {spec_output.design_spec_summary}")
    print(f"  Parts        : {spec_output.parts_required}")
    print(f"  Viable       : {spec_output.viable}")
    print(f"  Reasoning    : {spec_output.reasoning}")

    # -------------------------------------------------------------------------
    # Step 2: Electronics agent — full pipeline (Verilog + Yosys + schematic)
    # -------------------------------------------------------------------------
    print_section("STEP 2: Electronics Agent (Verilog → Yosys → RTL Schematic)")
    try:
        electronics_output = await electronics_agent.generate_design(spec_output, data_output)
        print(f"  Fetched components : {electronics_output.metadata.get('fetched_components')}")
        print(f"  Design spec        : {electronics_output.metadata.get('design_spec')}")
        print(f"  Viable             : {electronics_output.metadata.get('viable')}")
        print(f"\n--- RTL Schematic ---\n{electronics_output.instructions}")
        import traceback
        print(f"Error in parallel step: {e}")
        traceback.print_exc()
        return

    print("Data Extraction:")
    print(f"  Components   : {data_output.metadata.get('extracted_components')}")
    print(f"  Datasheets   : {len(data_output.datasheet_pdfs)}")
    print(f"  STLs         : {len(data_output.component_stls)}")
    print(f"  Recommend.   : {[r.name for r in data_output.recommendations]}")
    for url in data_output.datasheet_pdfs:
        print(f"  PDF URL      : {url}")
    for url in data_output.component_stls:
        print(f"  STL URL      : {url}")

    print("\nSpec Generation:")
    print(f"  Summary      : {spec_output.design_spec_summary}")
    print(f"  Parts        : {spec_output.parts_required}")
    print(f"  Viable       : {spec_output.viable}")
    print(f"  Reasoning    : {spec_output.reasoning}")

    # -------------------------------------------------------------------------
    # Step 2: Electronics agent — full pipeline (Verilog + Yosys + schematic)
    # -------------------------------------------------------------------------
    print_section("STEP 2: Electronics Agent (Verilog → Yosys → RTL Schematic)")
    try:
        electronics_output = await electronics_agent.generate_design(spec_output, data_output)
        print(f"  Fetched components : {electronics_output.metadata.get('fetched_components')}")
        print(f"  Design spec        : {electronics_output.metadata.get('design_spec')}")
        print(f"  Viable             : {electronics_output.metadata.get('viable')}")
        print(f"\n--- RTL Schematic ---\n{electronics_output.instructions}")
    except Exception as e:
        import traceback
        print(f"Electronics Agent Error: {e}")
        traceback.print_exc()
        return

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print_section("PIPELINE COMPLETE")
    print(f"  Components processed : {electronics_output.metadata.get('fetched_components')}")
    print(f"  Schematic URL        : {electronics_output.schematic_pdf_url}")

    verilog_out = "/tmp/unified_circuit.v"
    with open(verilog_out, "w") as f:
        f.write(electronics_output.code)
    print(f"  Verilog saved to     : {verilog_out}")

    firmware_out = "/tmp/firmware.ino"
    with open(firmware_out, "w") as f:
        f.write(electronics_output.firmware_code)
    print(f"  Firmware saved to    : {firmware_out}")

        import traceback
        print(f"Electronics Agent Error: {e}")
        traceback.print_exc()
        return

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print_section("PIPELINE COMPLETE")
    print(f"  Components processed : {electronics_output.metadata.get('fetched_components')}")
    print(f"  Schematic URL        : {electronics_output.schematic_pdf_url}")

    verilog_out = "/tmp/unified_circuit.v"
    with open(verilog_out, "w") as f:
        f.write(electronics_output.code)
    print(f"  Verilog saved to     : {verilog_out}")

    firmware_out = "/tmp/firmware.ino"
    with open(firmware_out, "w") as f:
        f.write(electronics_output.firmware_code)
    print(f"  Firmware saved to    : {firmware_out}")


if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("CRITICAL: Please set ANTHROPIC_API_KEY in backend/.env before running this test.")
    else:
        asyncio.run(test_pipeline())
