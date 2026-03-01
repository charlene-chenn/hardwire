import os
import anthropic
import asyncio
import uuid
from fpdf import FPDF
from dotenv import load_dotenv
from typing import List, Dict, Any
from schemas.agent_schemas import (
    DataExtractionOutput, 
    SpecGeneratorOutput, 
    ElectronicsOutput
)
from services.supabase_service import SupabaseService

load_dotenv()

class ElectronicsAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-3-5-sonnet-20240620"
        self.supabase = SupabaseService()

    async def generate_design(
        self, 
        spec: SpecGeneratorOutput, 
        extraction: DataExtractionOutput
    ) -> ElectronicsOutput:
        """
        Takes spec requirements and extracted datasheet data to generate
        a schematic PDF, instructions, and code.
        """
        
        # Prepare context from PDFs if available
        pdf_context = ""
        if hasattr(extraction, 'datasheet_contents') and extraction.datasheet_contents:
            pdf_context = "\nReference Datasheet Information (Base64 PDF snippets provided):\n"
            for i, content in enumerate(extraction.datasheet_contents[:2]): # Limit to first 2 for token reasons
                pdf_context += f"- Datasheet {i+1} summary: [PDF Data Included in Context]\n"

        system_prompt = (
            "You are a master hardware engineer. Your task is to design a system based on a specification "
            "and information extracted from component datasheets.\n\n"
            "You must provide:\n"
            "1. A detailed schematic description (which will be rendered to PDF).\n"
            "2. Step-by-step assembly and usage instructions.\n"
            "3. Firmware or control code (e.g., C++/Arduino or Python).\n\n"
            "Be extremely precise with pin connections and voltage levels."
        )

        user_content = (
            f"Design Specification:\n{spec.design_spec_summary}\n\n"
            f"Parts Identified:\n{', '.join(spec.parts_required)}\n\n"
            f"{pdf_context}\n"
            "Generate the schematic, instructions, and code using the output_design tool."
        )

        # Note: If extraction.datasheet_contents has base64 PDFs, we could technically 
        # send them as BetaPDF blocks if the model supports it, but for now we'll 
        # assume Claude can infer from the prompt or we pass text if we had extracted it.
        # Since the user specifically asked for "byte stream data (information from a pdf)",
        # I will include the base64 content in the message if the model/API allows, 
        # or simulate the "taking in" part. Claude-3-5-sonnet supports PDF input.

        messages = [
            {
                "role": "user", 
                "content": [
                    {"type": "text", "text": user_content}
                ]
            }
        ]

        # Add PDFs to content if they exist
        if hasattr(extraction, 'datasheet_contents') and extraction.datasheet_contents:
            for pdf_b64 in extraction.datasheet_contents[:2]: # Claude supports limited PDFs
                content_list: List[Dict[str, Any]] = messages[0]["content"] # type: ignore
                content_list.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64
                    }
                })

        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=[
                {
                    "name": "output_design",
                    "description": "Output the generated hardware design.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "schematic_description": {"type": "string", "description": "Textual description or SVG/Markdown of the schematic."},
                            "instructions": {"type": "string", "description": "Detailed assembly and usage instructions."},
                            "code": {"type": "string", "description": "Firmware or driver code."},
                            "metadata": {"type": "object"}
                        },
                        "required": ["schematic_description", "instructions", "code"]
                    }
                }
            ],
            tool_choice={"type": "tool", "name": "output_design"},
            betas=["pdfs-2024-09-25"]
        )

        tool_use = next(block for block in response.content if block.type == "tool_use")
        design_data = tool_use.input

        # Generate PDF from schematic description
        pdf_url = await self._generate_pdf(
            design_data["schematic_description"], 
            spec.design_spec_summary[:20]
        )

        return ElectronicsOutput(
            schematic_pdf_url=pdf_url,
            instructions=design_data["instructions"],
            code=design_data["code"],
            metadata=design_data.get("metadata", {})
        )

    async def _generate_pdf(self, schematic_desc: str, filename_prefix: str) -> str:
        """
        Renders the schematic description into a PDF and uploads to Supabase.
        """
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        
        pdf.cell(200, 10, txt="HARDWIRE - Schematic Design", ln=True, align='C')
        pdf.ln(10)
        
        # Split description into lines to avoid overflow
        for line in schematic_desc.split('\n'):
            pdf.multi_cell(0, 10, txt=line)
        
        pdf_bytes = pdf.output(dest='S')
        
        filename = f"designs/{filename_prefix.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
        
        storage_url = await self.supabase.upload_file("hardware_assets", filename, pdf_bytes)
        return storage_url or f"local-file://{filename}"
