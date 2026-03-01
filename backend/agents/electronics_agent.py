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
    def __init__(self, use_nemotron: bool | None = None):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-6"
        self.supabase = SupabaseService()
        self.use_nemotron = self._resolve_use_nemotron(use_nemotron)
        self.nemotron_endpoint = os.getenv("NEMOTRON_ENDPOINT")  # e.g. http://host:8000/v1
        self.nemotron_api_key = os.getenv("NEMOTRON_API_KEY", "none")
        self.nemotron_model = os.getenv("NEMOTRON_MODEL", "nemotron")

    @staticmethod
    def _resolve_use_nemotron(explicit_flag: bool | None) -> bool:
        if explicit_flag is not None:
            return explicit_flag
        env_flag = os.getenv("NEMOTRON_ENABLED", "false").strip().lower()
        return env_flag in {"1", "true", "yes", "on"}

    def _call_nemotron(self, system_prompt: str, user_prompt: str) -> str:
        """Call the remote Nemotron endpoint using the OpenAI-compatible client."""
        from openai import OpenAI
        if not self.nemotron_endpoint:
            raise ValueError("NEMOTRON_ENDPOINT env var not set.")

        print(f"  Calling Nemotron at {self.nemotron_endpoint} (model={self.nemotron_model}) ...")
        client = OpenAI(base_url=self.nemotron_endpoint, api_key=self.nemotron_api_key)
        resp = client.chat.completions.create(
            model=self.nemotron_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=4096,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        choice = resp.choices[0]
        content = choice.message.content
        print(f"  Nemotron finish_reason: {choice.finish_reason}")
        print(f"  Nemotron raw content length: {len(content) if content else 0}")
        if content:
            print(f"  Nemotron raw content preview: {content[:300]!r}")
        else:
            print("  WARNING: Nemotron returned None/empty content!")
        return (content or "").strip()

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
            "1. Use ONLY Verilog-2001 syntax. Do NOT use SystemVerilog constructs "
            "   (no 'logic', no 'always_ff', no 'always_comb', no 'interface', no 'typedef', no '::').\n"
            "2. Use 'reg' and 'wire' for all signal declarations.\n"
            "3. Every module that is instantiated MUST be fully defined in the same file.\n"
            "4. Do NOT reference or instantiate any module that you do not define inline.\n"
            "5. Use only one top-level module and define all sub-modules below it in the same file.\n"
            "6. PORT CONSISTENCY (most common mistake): Every port name used in a module instantiation "
            "   (e.g., .clk(clk), .data_out(wire_x)) MUST exactly match a port declared in that module's "
            "   port list. Before outputting, mentally trace every instantiation and verify each connected "
            "   port name exists in the target module definition.\n"
            "7. Start the file directly with the first module keyword (optionally preceded by a `timescale directive). "
            "   No prose, no explanation, no markdown fences."
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
            print("  Using Nemotron (remote endpoint)")
            verilog = self._call_nemotron(system_prompt, user_prompt)
            # Strip <think>...</think> reasoning blocks if the model emitted them
            import re as _re
            verilog = _re.sub(r'(?s)<think>.*?</think>', '', verilog).strip()
            # Strip markdown code fences if present (e.g. ```verilog ... ```)
            if verilog.startswith("```"):
                lines = verilog.split("\n")
                start = 1
                end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
                verilog = "\n".join(lines[start:end])
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

        # Strip any prose/comments before the first actual module declaration.
        # Match `module` only at the start of a line (not inside inline comments).
        import re
        raw_verilog = verilog
        module_match = re.search(r'(?m)^\s*(`timescale\b.*\n\s*)?module\s+\w+', verilog)
        if module_match:
            verilog = verilog[module_match.start():]
        else:
            # Fallback: look for any `module` keyword
            m2 = re.search(r'\bmodule\s+\w+', verilog)
            if m2:
                verilog = verilog[m2.start():]

        verilog = verilog.strip()

        if not verilog:
            print(f"  WARNING: Prose stripping removed all content! Raw response was {len(raw_verilog)} chars.")
            print(f"  Raw response preview: {raw_verilog[:500]!r}")
        else:
            print(f"  Post-strip Verilog preview: {verilog[:200]!r}")

        return verilog

    # -------------------------------------------------------------------------
    # Step B: Synthesize Verilog → netlist JSON via Yosys
    # -------------------------------------------------------------------------

    @staticmethod
    def _sanitize_verilog(verilog_code: str) -> str:
        """
        Remove or replace characters that cause Yosys parse errors:
        - Smart/curly quotes → straight ASCII quotes
        - Non-ASCII characters → stripped out
        - Windows line endings → Unix
        """
        replacements = {
            "\u2018": "'", "\u2019": "'",  # left/right single curly quotes
            "\u201c": '"', "\u201d": '"',  # left/right double curly quotes
            "\u2014": "--",                # em-dash
            "\u2013": "-",                 # en-dash
            "\u00b5": "u",                 # micro sign → u
        }
        for bad, good in replacements.items():
            verilog_code = verilog_code.replace(bad, good)
        # Strip remaining non-ASCII (outside printable range)
        verilog_code = verilog_code.encode("ascii", errors="ignore").decode("ascii")
        # Normalize line endings
        verilog_code = verilog_code.replace("\r\n", "\n").replace("\r", "\n")
        return verilog_code

    @staticmethod
    def _extract_top_module(verilog_code: str) -> str:
        """Return the first module name found in the Verilog source."""
        import re
        match = re.search(r'\bmodule\s+(\w+)', verilog_code)
        return match.group(1) if match else None

    def _synthesize_with_yosys(self, verilog_code: str) -> str:
        """
        Step B: Write Verilog to a temp file, run Yosys synthesis,
        and return (netlist_json, svg_path).
        Requires yosys to be installed: brew install yosys / apt install yosys
        """
        import shutil as _shutil

        verilog_code = self._sanitize_verilog(verilog_code)
        module_name = self._extract_top_module(verilog_code)
        top_flag = f"-top {module_name}" if module_name else ""
        print(f"  Top module: {module_name or '(none found)'}")

        SVG_OUTPUT = "/tmp/schematic.svg"

        with tempfile.TemporaryDirectory() as tmpdir:
            verilog_path = os.path.join(tmpdir, "design.v")
            netlist_path = os.path.join(tmpdir, "netlist.json")
            svg_prefix   = os.path.join(tmpdir, "schematic")
            script_path  = os.path.join(tmpdir, "synth.ys")

            with open(verilog_path, "w", encoding="ascii") as f:
                f.write(verilog_code)

            show_module = module_name if module_name else ""
            yosys_script = (
                f"read_verilog -sv {verilog_path}\n"
                f"synth {top_flag}\n"
                f"write_json {netlist_path}\n"
                f"show -format svg -prefix {svg_prefix} {show_module}\n"
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

                svg_tmp = svg_prefix + ".svg"
                svg_out = None
                if os.path.exists(svg_tmp):
                    _shutil.copy(svg_tmp, SVG_OUTPUT)
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

    def _fix_verilog_with_error(self, verilog: str, yosys_error: str) -> str:
        """
        Ask Claude to patch the Verilog given a Yosys error message.
        Returns the corrected Verilog code only (no prose, no fences).
        """
        print(f"  Asking Claude to fix synthesis error...")
        fix_system = (
            "You are an expert Verilog-2001 engineer. "
            "You will be given a broken Verilog file and a Yosys error message. "
            "Output ONLY the corrected Verilog source with no explanation, no markdown fences. "
            "Fix the specific error described while preserving the rest of the design. "
            "PORT CONSISTENCY rule: every .port(signal) in a module instantiation must match "
            "a port name declared in that module's port list."
        )
        fix_user = (
            f"Yosys error:\n{yosys_error}\n\n"
            f"Verilog source:\n{verilog}\n\n"
            "Return the corrected Verilog only."
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=fix_system,
            messages=[{"role": "user", "content": fix_user}],
        )
        fixed = response.content[0].text.strip()
        if fixed.startswith("```"):
            lines = fixed.split("\n")
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            fixed = "\n".join(lines[start:end])
        return fixed.strip()

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

        # Step B — synthesize unified Verilog → netlist JSON via Yosys (with retry)
        print("\n--- Step B: Yosys synthesis ---")
        MAX_SYNTH_RETRIES = 3
        netlist_json, svg_path = None, None
        current_verilog = verilog
        for attempt in range(1, MAX_SYNTH_RETRIES + 1):
            print(f"  Synthesis attempt {attempt}/{MAX_SYNTH_RETRIES}")
            netlist_json, svg_path = self._synthesize_with_yosys(current_verilog)
            try:
                parsed = json.loads(netlist_json)
                if "error" not in parsed:
                    break  # success
                yosys_error = parsed["error"]
                # Don't retry on Yosys-not-found or timeout — those won't be fixed by rewriting
                if "not found" in yosys_error or "timed out" in yosys_error:
                    break
                if attempt < MAX_SYNTH_RETRIES:
                    print(f"  Synthesis error on attempt {attempt}: {yosys_error[:200]}")
                    current_verilog = self._fix_verilog_with_error(current_verilog, yosys_error)
                    if not current_verilog.strip():
                        print("  Fix returned empty Verilog — stopping retries.")
                        break
            except (json.JSONDecodeError, KeyError):
                break  # netlist_json is real JSON, not an error dict
        verilog = current_verilog  # use the (possibly fixed) version in output
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