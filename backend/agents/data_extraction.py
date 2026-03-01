import os
import anthropic
import base64
from dotenv import load_dotenv
from schemas.agent_schemas import DataExtractionOutput, ComponentRecommendation
from services.search_service import SearchService
from services.supabase_service import SupabaseService
from typing import List

load_dotenv()

class DataExtractionAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-6"
        self.search_service = SearchService()
        self.supabase = SupabaseService()

    async def extract_and_fetch(self, user_prompt: str) -> DataExtractionOutput:
        """
        Extracts components, searches for datasheets/STLs, and recommends other parts.
        """
        # 1. Identify components from user prompt
        system_prompt = (
            "You are an expert electronics engineer assistant. Extract only the names of electronic components "
            "that have technical specifications (like ICs, transistors, sensors, microcontrollers). "
            "Exclude generic hardware like 'wires', 'screws', 'breadboards', or mechanical parts without datasheets. "
            "Return a clean JSON array of strings using the list_components tool."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Extract electronic components with specifications from: {user_prompt}"}],
            tools=[
                {
                    "name": "list_components",
                    "description": "List extracted electronic component names.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "components": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["components"]
                    }
                }
            ],
            tool_choice={"type": "tool", "name": "list_components"}
        )

        tool_use = next(block for block in response.content if block.type == "tool_use")
        components = tool_use.input.get("components", [])

        # 2. Search for datasheets and STLs
        all_datasheets = []
        all_stls = []
        datasheet_contents = []
        stl_contents = []
        
        for comp in components:
            # Clean component name for filename: lowercase and replace spaces with underscores
            clean_comp = comp.lower().replace(" ", "_")
            print(f"--- Processing component: {comp} (as {clean_comp}) ---")
            
            # Search
            ds_urls = await self.search_service.search_datasheets(comp)
            stl_urls = await self.search_service.search_stls(comp)
            
            # Download and Upload Datasheets
            for i, url in enumerate(ds_urls):
                # Skip common non-direct links if they don't look like PDFs
                if any(x in url.lower() for x in [".html", ".php", "/search", "/category"]):
                    if not url.lower().endswith(".pdf"):
                        print(f"Skipping likely non-direct PDF link: {url}")
                        continue

                print(f"Downloading datasheet: {url}")
                content = await self.search_service.download_file(url)
                if content:
                    # Verify it's actually a PDF
                    if content.startswith(b"%PDF"):
                        # Save as base64
                        content_64 = base64.b64encode(content).decode('utf-8')
                        datasheet_contents.append(content_64)
                        
                        filename = f"datasheets/{clean_comp}.pdf"
                        storage_url = await self.supabase.upload_file("hardware_assets", filename, content)
                        if storage_url:
                            all_datasheets.append(storage_url)
                            self.supabase.save_data("component_assets", {
                                "component_name": comp,
                                "asset_type": "datasheet",
                                "url": storage_url,
                                "label": clean_comp,
                                "content_base64": content_64,
                            })
                        else:
                            all_datasheets.append(url)
                        break
                    else:
                        print(f"Downloaded content from {url} was not a valid PDF.")

            # Download and Upload STLs
            for i, url in enumerate(stl_urls):
                # Skip likely landing pages
                if any(x in url.lower() for x in [".html", ".php", "/parts", "/libraries"]):
                    if not url.lower().endswith(".stl"):
                        print(f"Skipping likely non-direct STL link: {url}")
                        continue

                print(f"Downloading STL/Model: {url}")
                content = await self.search_service.download_file(url)
                if content:
                    # Basic check if it's likely a binary STL or ASCII STL
                    is_stl = b"solid" in content[:100].lower() or len(content) > 80
                    if is_stl:
                        # Save as base64
                        stl_contents.append(base64.b64encode(content).decode('utf-8'))

                        filename = f"stls/{clean_comp}.stl"
                        storage_url = await self.supabase.upload_file("hardware_assets", filename, content)
                        if storage_url:
                            all_stls.append(storage_url)
                            self.supabase.save_data("component_assets", {
                                "component_name": comp,
                                "asset_type": "stl",
                                "url": storage_url,
                                "label": clean_comp,
                                "content_base64": base64.b64encode(content).decode('utf-8'),
                            })
                        else:
                            all_stls.append(url)
                        break

        # 3. Recommend other components
        rec_prompt = (
            f"Based on these components: {', '.join(components)} and the use case: '{user_prompt}', "
            "recommend 2-3 complementary electronic components and why they are needed."
        )
        rec_response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system="You are an expert electronics consultant.",
            messages=[{"role": "user", "content": rec_prompt}],
            tools=[
                {
                    "name": "recommend_components",
                    "description": "Recommend additional components.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "recommendations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "reason": {"type": "string"},
                                        "datasheet_url": {"type": "string"}
                                    },
                                    "required": ["name", "reason"]
                                }
                            }
                        },
                        "required": ["recommendations"]
                    }
                }
            ],
            tool_choice={"type": "tool", "name": "recommend_components"}
        )

        rec_tool_use = next(block for block in rec_response.content if block.type == "tool_use")
        recommendations = [ComponentRecommendation(**r) for r in rec_tool_use.input.get("recommendations", [])]

        # 4. Return results
        return DataExtractionOutput(
            datasheet_pdfs=all_datasheets,
            component_stls=all_stls,
            datasheet_contents=datasheet_contents,
            stl_contents=stl_contents,
            recommendations=recommendations,
            metadata={"extracted_components": components}
        )
