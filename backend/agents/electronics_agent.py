import os
import base64
import subprocess
import tempfile
import json
import anthropic
import asyncio
import uuid
from fpdf import FPDF
from dotenv import load_dotenv
from typing import List, Dict, Any, Tuple
from schemas.agent_schemas import (
    DataExtractionOutput, 
    SpecGeneratorOutput, 
    ElectronicsOutput
)
from services.supabase_service import SupabaseService

load_dotenv()

class ElectronicsAgent:
    def __init__(self, use_nemotron: bool = False):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-6"
        self.supabase = SupabaseService()
        self.use_nemotron = use_nemotron
        self._nemotron_tokenizer = None
        self._nemotron_model = None

    def _load_nemotron(self):
        """Lazy-load the Nemotron model on first use (4-bit quantized, ~35GB VRAM)."""
        if self._nemotron_model is None:
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
            import torch
            model_name = "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"
            print(f"Loading {model_name} in 4-bit quantized mode...")
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            self._nemotron_tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._nemotron_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                quantization_config=bnb_config,
                device_map="auto",
            )
            print("Nemotron model loaded.")
        return self._nemotron_tokenizer, self._nemotron_model

    # -------------------------------------------------------------------------
    # Step 0: Fetch PDFs from Supabase by component label
    # -------------------------------------------------------------------------

    def _fetch_datasheets_from_db(self, components: List[str]) -> List[Tuple[str, bytes]]:
        """
        Query component_assets for each component label, decode content_base64,
        and return list of (component_name, pdf_bytes) tuples.
        """
        results = []
        if not self.supabase.client:
            print("No Supabase client — skipping datasheet fetch.")
            return results

        for comp in components:
            clean_label = comp.lower().replace(" ", "_")
            print(f"Searching for {clean_label}")
            try:
                response = (
                    self.supabase.client
                    .table("component_assets")
                    .select("content_base64")
                    .ilike("label", f"%{clean_label}%")
                    .eq("asset_type", "datasheet")
                    .limit(1)
                    .execute()
                )
                # print(f"  DB response: {response.data}")
                if response.data and response.data[0].get("content_base64"):
                    pdf_bytes = base64.b64decode(response.data[0]["content_base64"])
                    results.append((comp, pdf_bytes))
                    print(f"Fetched datasheet for: {comp}")
                else:
                    print(f"No datasheet found in DB for: {comp} (row exists but content_base64 is NULL or empty)")
            except Exception as e:
                print(f"Error fetching datasheet for {comp}: {e}")

        return results

    # -------------------------------------------------------------------------
    # Step A: Extract PDF text → Verilog via Nemotron
    # -------------------------------------------------------------------------

    def _extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber (first 10 pages)."""
        import pdfplumber
        import io
        text = ""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages[:10]:
                    text += page.extract_text() or ""
        except Exception as e:
            print(f"PDF text extraction error: {e}")
        return text

    def _generate_unified_verilog(
        self,
        component_datasheets: List[Tuple[str, str]],
        spec: "SpecGeneratorOutput",
    ) -> str:
        """
        Step A: Given pinout/datasheet text for ALL components, reason about how
        they connect and generate ONE unified top-level Verilog module for the circuit.
        Uses Claude or Nemotron depending on self.use_nemotron.
        """
        system_prompt = (
            "You are an expert HDL engineer and circuit designer. "
            "Given pinout and datasheet excerpts for multiple components and an overall design intent, "
            "reason about how the components connect to each other (shared buses, control signals, power rails) "
            "and generate a single syntactically correct Verilog file that wires them all together. "
            "CRITICAL RULES:\n"
            "1. Every module that is instantiated MUST be fully defined in the same file.\n"
            "2. Do NOT reference or instantiate any module that you do not define inline.\n"
            "3. Use only one top-level module and define all sub-modules below it in the same file.\n"
            "4. Output ONLY valid Verilog code with no explanation, no markdown, no comments outside the code."
        )

        datasheets_text = ""
        for comp_name, pdf_text in component_datasheets:
            datasheets_text += f"\n--- {comp_name} Datasheet Excerpt ---\n{pdf_text[:2000]}\n"

        user_prompt = (
            f"Design intent: {spec.design_spec_summary}\n"
            f"Parts in this design: {', '.join(spec.parts_required)}\n\n"
            f"Component datasheets:\n{datasheets_text}\n"
            "Generate the unified top-level Verilog module that connects all components together."
        )

        if self.use_nemotron:
            tokenizer, model = self._load_nemotron()
            import torch
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            input_ids = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to(model.device)
            with torch.no_grad():
                output_ids = model.generate(
                    input_ids,
                    max_new_tokens=2048,
                    temperature=0.1,
                    do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                )
            verilog = tokenizer.decode(
                output_ids[0][input_ids.shape[1]:],
                skip_special_tokens=True,
            )
        else:
            print("  Using Claude for unified Verilog generation (Nemotron disabled)")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            verilog = response.content[0].text.strip()
            if verilog.startswith("```"):
                lines = verilog.split("\n")
                start = 1
                end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
                verilog = "\n".join(lines[start:end])

        return verilog.strip()

    # -------------------------------------------------------------------------
    # Step B: Synthesize Verilog → netlist JSON via Yosys
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_top_module(verilog_code: str) -> str:
        """Return the first module name found in the Verilog source."""
        import re
        match = re.search(r'\bmodule\s+(\w+)', verilog_code)
        return match.group(1) if match else None

    def _synthesize_with_yosys(self, verilog_code: str) -> str:
        """
        Step B: Write Verilog to a temp file, run Yosys synthesis,
        and return the netlist JSON string.
        Requires yosys to be installed: brew install yosys / apt install yosys
        """
        module_name = self._extract_top_module(verilog_code)
        top_flag = f"-top {module_name}" if module_name else ""
        print(f"  Top module: {module_name or '(none found)'}")

        SVG_OUTPUT = "/tmp/schematic.svg"

        with tempfile.TemporaryDirectory() as tmpdir:
            verilog_path = os.path.join(tmpdir, "design.v")
            netlist_path = os.path.join(tmpdir, "netlist.json")
            svg_prefix   = os.path.join(tmpdir, "schematic")
            script_path  = os.path.join(tmpdir, "synth.ys")

            with open(verilog_path, "w") as f:
                f.write(verilog_code)

            yosys_script = (
                f"read_verilog -defer {verilog_path}\n"
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
                    print(f"Yosys synthesis error:\n{result.stderr}")
                    return json.dumps({"error": result.stderr}), None

                import shutil
                svg_tmp = svg_prefix + ".svg"
                svg_out = None
                if os.path.exists(svg_tmp):
                    shutil.copy(svg_tmp, SVG_OUTPUT)
                    svg_out = SVG_OUTPUT
                    print(f"  SVG schematic saved to: {SVG_OUTPUT}")
                else:
                    print("  SVG not generated (GraphViz may not be installed)")

                if os.path.exists(netlist_path):
                    with open(netlist_path, "r") as f:
                        return f.read(), svg_out
                return json.dumps({"stdout": result.stdout}), svg_out

            except FileNotFoundError:
                msg = "Yosys not found. Install with: brew install yosys"
                print(msg)
                return json.dumps({"error": msg}), None
            except subprocess.TimeoutExpired:
                return json.dumps({"error": "Yosys synthesis timed out."}), None

    # -------------------------------------------------------------------------
    # Step C: Build RTL schematic description from netlist JSON
    # -------------------------------------------------------------------------

    def _generate_rtl_schematic(self, netlist_json: str, component_name: str) -> str:
        """
        Step C: Parse Yosys netlist JSON and produce a human-readable
        RTL schematic description listing modules, ports, and cells.
        """
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
            lines.append(netlist_json[:500])

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Main entry point
    # -------------------------------------------------------------------------

    async def generate_design(
        self,
        spec: SpecGeneratorOutput,
        extraction: DataExtractionOutput,
    ) -> ElectronicsOutput:
        """
        Full pipeline:
          0. Fetch datasheets from Supabase using component labels from session memory
          A. Nemotron → Verilog
          B. Yosys → netlist
          C. Netlist → RTL schematic description
          Then use Claude to generate assembly instructions and firmware code.
        """
        components: List[str] = extraction.metadata.get("extracted_components", [])
        print(f"Electronics agent using components: {components}")
        print(f"Design spec: {spec.design_spec_summary}")
        print(f"Viable: {spec.viable} — {spec.reasoning}")

        # Step 0 — fetch PDFs from Supabase for all components
        datasheet_pairs = self._fetch_datasheets_from_db(components)
        for comp_name, pdf_bytes in datasheet_pairs:
            print(f"Fetched {len(pdf_bytes)} bytes for: {comp_name}")

        if not datasheet_pairs:
            print("No datasheets found — cannot generate circuit Verilog.")
            return ElectronicsOutput(
                schematic_pdf_url="pending",
                instructions="No datasheets found.",
                code="pending",
                metadata={"fetched_components": [], "design_spec": spec.design_spec_summary},
            )

        # Step A — extract text from all PDFs, then generate ONE unified Verilog
        print("\n--- Step A: Extracting pinout text from all datasheets ---")
        component_datasheets: List[Tuple[str, str]] = []
        for comp_name, pdf_bytes in datasheet_pairs:
            pdf_text = self._extract_text_from_pdf(pdf_bytes)
            print(f"  {comp_name}: {len(pdf_text)} chars extracted")
            component_datasheets.append((comp_name, pdf_text))

        print("\n--- Step A: Generating unified circuit Verilog ---")
        verilog = self._generate_unified_verilog(component_datasheets, spec)
        print(f"Unified Verilog generated ({len(verilog)} chars)")

        verilog_path = "/tmp/unified_circuit.txt"
        with open(verilog_path, "w") as f:
            f.write(verilog)
        print(f"Verilog saved to: {verilog_path}")
        print(f"Verilog preview: {verilog[:200]!r}")

        if not verilog.strip() or "module" not in verilog:
            print("ERROR: Generated Verilog is empty or missing module definition — skipping synthesis.")
            return ElectronicsOutput(
                schematic_pdf_url="not_generated",
                instructions="Verilog generation failed.",
                code=verilog,
                firmware_code="",
                metadata={
                    "fetched_components": [c for c, _ in datasheet_pairs],
                    "design_spec": spec.design_spec_summary,
                    "viable": spec.viable,
                    "parts_required": spec.parts_required,
                },
            )

        # Step B — synthesize unified Verilog → netlist JSON via Yosys
        print("\n--- Step B: Yosys synthesis ---")
        netlist_json, svg_path = self._synthesize_with_yosys(verilog)
        print("Yosys synthesis complete")

        # Step C — build RTL schematic description from netlist
        print("\n--- Step C: RTL schematic ---")
        schematic = self._generate_rtl_schematic(netlist_json, "unified_circuit")
        print(schematic)

        # Step D — generate firmware code to run on the microcontroller
        print("\n--- Step D: Generating firmware code ---")
        firmware = self._generate_firmware(spec, [c for c, _ in datasheet_pairs])
        print(f"Firmware generated ({len(firmware)} chars)")

        return ElectronicsOutput(
            schematic_pdf_url=svg_path or "not_generated",
            instructions=schematic,
            code=verilog,
            firmware_code=firmware,
            metadata={
                "fetched_components": [c for c, _ in datasheet_pairs],
                "design_spec": spec.design_spec_summary,
                "viable": spec.viable,
                "parts_required": spec.parts_required,
            },
        )

    def _generate_firmware(self, spec: "SpecGeneratorOutput", components: List[str]) -> str:
        """Generate Arduino/C++ firmware code to run the circuit on the microcontroller."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=(
                "You are an expert embedded systems engineer. "
                "Given a circuit design spec and list of components, write complete, "
                "compilable Arduino/C++ firmware code that runs the described system. "
                "Include pin definitions, setup(), loop(), interrupt handlers, and any helper functions. "
                "Output ONLY valid Arduino/C++ code with no explanation, no markdown fences."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Design: {spec.design_spec_summary}\n"
                    f"Components: {', '.join(components)}\n"
                    f"Parts list: {', '.join(spec.parts_required)}\n\n"
                    "Write the complete firmware."
                ),
            }],
        )
        firmware = response.content[0].text.strip()
        if firmware.startswith("```"):
            lines = firmware.split("\n")
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            firmware = "\n".join(lines[start:end])
        return firmware

    # -------------------------------------------------------------------------
    # PDF generation
    # -------------------------------------------------------------------------

    async def _generate_pdf(self, schematic_desc: str, filename_prefix: str) -> str:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        pdf.cell(200, 10, txt="HARDWIRE - RTL Schematic Design", ln=True, align="C")
        pdf.ln(10)
        for line in schematic_desc.split("\n"):
            pdf.multi_cell(0, 10, txt=line)
        pdf_bytes = bytes(pdf.output())
        filename = f"designs/{filename_prefix.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
        storage_url = await self.supabase.upload_file("hardware_asset", filename, pdf_bytes)
        return storage_url or f"local-file://{filename}"