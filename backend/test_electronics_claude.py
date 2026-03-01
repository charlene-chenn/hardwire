"""
Dummy test for the electronics pipeline using Claude instead of Nemotron.
Bypasses GPU requirement — useful for hackathon demos and CI.
"""

import os
import sys
import json
import base64
import subprocess
import tempfile
import anthropic
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Dummy PDF bytes — a minimal valid PDF with ESP32 datasheet-like text
# ---------------------------------------------------------------------------
DUMMY_PDF_TEXT = """
ESP32 Datasheet Excerpt

Overview:
The ESP32 is a dual-core 32-bit microcontroller with integrated Wi-Fi and Bluetooth.

Pin Description:
- GPIO0  : Boot mode select / General purpose I/O (input/output)
- GPIO2  : General purpose I/O with internal pull-down
- EN     : Chip enable (active high)
- VDD33  : 3.3V power supply
- GND    : Ground
- TX0    : UART0 transmit
- RX0    : UART0 receive
- CLK    : Clock input (up to 240MHz)

Electrical Characteristics:
- Operating voltage: 3.0V – 3.6V
- Clock frequency: up to 240 MHz
- GPIO drive current: 40mA max

Features:
- Dual Xtensa LX6 cores
- 520 KB SRAM
- Hardware PWM, ADC, DAC, SPI, I2C, UART
"""


# ---------------------------------------------------------------------------
# Step A: Generate Verilog using Claude
# ---------------------------------------------------------------------------
def generate_verilog_claude(pdf_text: str, component_name: str) -> str:
    print(f"\n[Step A] Generating Verilog for {component_name} via Claude...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=(
            "You are an expert HDL engineer. Given a component datasheet, "
            "generate a syntactically correct Verilog module that captures "
            "pin functions, input/output ports, clock triggers, and combinational logic. "
            "Output ONLY valid Verilog code with no explanation."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Component: {component_name}\n\n"
                    f"Datasheet (excerpt):\n{pdf_text[:4000]}\n\n"
                    "Generate the Verilog module now."
                ),
            }
        ],
    )
    verilog = response.content[0].text.strip()
    # Strip markdown code fences if Claude wrapped it
    if verilog.startswith("```"):
        lines = verilog.split("\n")
        # Remove first line (```verilog) and last line (```) if present
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        verilog = "\n".join(lines[start:end])
    print(f"  Generated {len(verilog)} chars of Verilog")
    return verilog


# ---------------------------------------------------------------------------
# Step B: Synthesize Verilog → netlist JSON via Yosys
# ---------------------------------------------------------------------------
def _extract_module_name(verilog_code: str) -> str:
    """Extract the top module name from Verilog code."""
    import re
    match = re.search(r'\bmodule\s+(\w+)', verilog_code)
    return match.group(1) if match else None


SVG_OUTPUT_PATH = "/tmp/schematic.svg"


def synthesize_with_yosys(verilog_code: str) -> str:
    print("\n[Step B] Running Yosys synthesis...")
    module_name = _extract_module_name(verilog_code)
    top_flag = f"-top {module_name}" if module_name else ""
    print(f"  Top module: {module_name or '(auto-detect)'}")

    with tempfile.TemporaryDirectory() as tmpdir:
        verilog_path = os.path.join(tmpdir, "design.v")
        netlist_path = os.path.join(tmpdir, "netlist.json")
        svg_prefix = os.path.join(tmpdir, "schematic")
        script_path = os.path.join(tmpdir, "synth.ys")

        with open(verilog_path, "w") as f:
            f.write(verilog_code)

        yosys_script = (
            f"read_verilog {verilog_path}\n"
            f"synth {top_flag}\n"
            f"write_json {netlist_path}\n"
            f"show -format svg -prefix {svg_prefix}\n"
        )
        with open(script_path, "w") as f:
            f.write(yosys_script)

        try:
            result = subprocess.run(
                ["yosys", "-s", script_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                print(f"  Yosys error:\n{result.stderr[:500]}")
                return json.dumps({"error": result.stderr})

            # Copy SVG to a stable output path
            svg_tmp = svg_prefix + ".svg"
            if os.path.exists(svg_tmp):
                import shutil
                shutil.copy(svg_tmp, SVG_OUTPUT_PATH)
                print(f"  SVG schematic saved to: {SVG_OUTPUT_PATH}")
            else:
                print("  SVG not generated (GraphViz may not be installed)")

            if os.path.exists(netlist_path):
                with open(netlist_path, "r") as f:
                    netlist = f.read()
                print(f"  Netlist generated ({len(netlist)} chars)")
                return netlist
            return json.dumps({"stdout": result.stdout})

        except FileNotFoundError:
            print("  Yosys not found — returning stub netlist")
            return json.dumps({
                "modules": {
                    "esp32_stub": {
                        "ports": {
                            "CLK": {"direction": "input", "bits": [0]},
                            "EN": {"direction": "input", "bits": [1]},
                            "TX0": {"direction": "output", "bits": [2]},
                            "RX0": {"direction": "input", "bits": [3]},
                        },
                        "cells": {},
                    }
                }
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Yosys timed out"})


# ---------------------------------------------------------------------------
# Step C: Build RTL schematic description from netlist JSON
# ---------------------------------------------------------------------------
def generate_rtl_schematic(netlist_json: str, component_name: str) -> str:
    print("\n[Step C] Generating RTL schematic description...")
    lines = [f"RTL Schematic — {component_name}", "=" * 50]
    try:
        netlist = json.loads(netlist_json)
        if "error" in netlist:
            lines.append(f"Synthesis error: {netlist['error']}")
            return "\n".join(lines)

        for module_name, module_data in netlist.get("modules", {}).items():
            lines.append(f"\nModule: {module_name}")
            for port_name, port_info in module_data.get("ports", {}).items():
                direction = port_info.get("direction", "?")
                width = len(port_info.get("bits", []))
                lines.append(f"  [{direction:3s}] {port_name} ({width}-bit)")
            cells = module_data.get("cells", {})
            if cells:
                lines.append(f"  Cells ({len(cells)}):")
                for cell_name, cell_info in cells.items():
                    cell_type = cell_info.get("type", "?")
                    lines.append(f"    {cell_name} : {cell_type}")

    except (json.JSONDecodeError, KeyError) as e:
        lines.append(f"Could not parse netlist: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    component_name = "ESP32"
    pdf_text = DUMMY_PDF_TEXT

    print(f"=== Electronics Pipeline Test (Claude) ===")
    print(f"Component: {component_name}")

    # Step A
    verilog = generate_verilog_claude(pdf_text, component_name)
    print(f"\n--- Verilog ---\n{verilog}\n")

    # Step B
    netlist_json = synthesize_with_yosys(verilog)

    # Step C
    schematic = generate_rtl_schematic(netlist_json, component_name)
    print(f"\n--- RTL Schematic ---\n{schematic}\n")

    print(f"\n  Open schematic: open {SVG_OUTPUT_PATH}")
    print("\n=== Test complete ===")
