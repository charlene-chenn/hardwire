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
from typing import List, Tuple
from backend.schemas.agent_schemas import (
    DataExtractionOutput,
    SpecGeneratorOutput, 
    ElectronicsOutput
)
from backend.services.supabase_service import SupabaseService

load_dotenv()

class ElectronicsAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-3-5-sonnet-20240620"
        self.supabase = SupabaseService()
        self._nemotron_tokenizer = None
        self._nemotron_model = None

    def _load_nemotron(self):
        """Lazy-load the Nemotron model on first use."""
        if self._nemotron_model is None:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch
            model_name = "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"
            print(f"Loading {model_name} (requires ~140GB VRAM in fp16)...")
            self._nemotron_tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._nemotron_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16,
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

    def _generate_verilog(self, pdf_text: str, component_name: str) -> str:
        """
        Step A: Feed datasheet text into Nemotron and return Verilog code.
        """
        tokenizer, model = self._load_nemotron()
        import torch

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert HDL engineer. Given a component datasheet, "
                    "generate a syntactically correct Verilog module that captures "
                    "pin functions, input/output ports, clock triggers, and combinational logic. "
                    "Output ONLY valid Verilog code with no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Component: {component_name}\n\n"
                    f"Datasheet (excerpt):\n{pdf_text[:4000]}\n\n"
                    "Generate the Verilog module now."
                ),
            },
        ]

        input_ids = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(model.device)

        with torch.no_grad():
            output_ids = model.generate(
                input_ids,
                max_new_tokens=1024,
                temperature=0.1,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
            )

        verilog = tokenizer.decode(
            output_ids[0][input_ids.shape[1]:],
            skip_special_tokens=True,
        )
        return verilog.strip()

    # -------------------------------------------------------------------------
    # Step B: Synthesize Verilog → netlist JSON via Yosys
    # -------------------------------------------------------------------------

    def _synthesize_with_yosys(self, verilog_code: str) -> str:
        """
        Step B: Write Verilog to a temp file, run Yosys synthesis,
        and return the netlist JSON string.
        Requires yosys to be installed: brew install yosys / apt install yosys
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            verilog_path = os.path.join(tmpdir, "design.v")
            netlist_path = os.path.join(tmpdir, "netlist.json")
            script_path = os.path.join(tmpdir, "synth.ys")

            with open(verilog_path, "w") as f:
                f.write(verilog_code)

            yosys_script = (
                f"read_verilog {verilog_path}\n"
                f"synth -top auto\n"
                f"write_json {netlist_path}\n"
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
                    return json.dumps({"error": result.stderr})

                if os.path.exists(netlist_path):
                    with open(netlist_path, "r") as f:
                        return f.read()
                return json.dumps({"stdout": result.stdout})

            except FileNotFoundError:
                msg = "Yosys not found. Install with: brew install yosys"
                print(msg)
                return json.dumps({"error": msg})
            except subprocess.TimeoutExpired:
                return json.dumps({"error": "Yosys synthesis timed out."})

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
        print(f"Electronics agent using components from session: {components}")

        # Step 0 — fetch PDFs from Supabase
        datasheet_pairs = self._fetch_datasheets_from_db(components)

        for comp_name, pdf_bytes in datasheet_pairs:
            print(f"Fetched {len(pdf_bytes)} bytes for: {comp_name}")

        # Steps A, B, C — Verilog, Yosys, RTL schematic
        all_schematics = []
        for comp_name, pdf_bytes in datasheet_pairs:
            print(f"\n--- Processing {comp_name} ---")

            # Step A: extract PDF text → Verilog via Nemotron
            pdf_text = self._extract_text_from_pdf(pdf_bytes)
            print(f"Extracted {len(pdf_text)} chars from PDF")
            verilog = self._generate_verilog(pdf_text, comp_name)
            print(f"Generated Verilog ({len(verilog)} chars)")

            # Step B: synthesize Verilog → netlist JSON via Yosys
            netlist_json = self._synthesize_with_yosys(verilog)
            print(f"Yosys synthesis complete")

            # Step C: build RTL schematic description
            schematic = self._generate_rtl_schematic(netlist_json, comp_name)
            all_schematics.append(schematic)
            print(schematic)

        combined_schematic = "\n\n".join(all_schematics) if all_schematics else "No datasheets found."

        return ElectronicsOutput(
            schematic_pdf_url="pending",
            instructions=combined_schematic,
            code="pending",
            metadata={"fetched_components": [c for c, _ in datasheet_pairs]},
        )

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
