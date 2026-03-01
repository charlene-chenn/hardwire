import os
import anthropic
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
            
            # Save direct datasheet download URL only (.pdf)
            for url in ds_urls:
                if not url.lower().endswith(".pdf"):
                    print(f"Skipping non-direct PDF link: {url}")
                    continue
                print(f"Saving datasheet URL: {url}")
                all_datasheets.append(url)
                self.supabase.save_data("component_assets", {
                    "component_name": comp,
                    "asset_type": "datasheet",
                    "url": url,
                    "label": clean_comp,
                    "content_base64": None,
                })
                break

            # Save direct STL download URL only (.stl)
            for url in stl_urls:
                if not url.lower().endswith(".stl"):
                    print(f"Skipping non-direct STL link: {url}")
                    continue
                print(f"Saving STL URL: {url}")
                all_stls.append(url)
                self.supabase.save_data("component_assets", {
                    "component_name": comp,
                    "asset_type": "stl",
                    "url": url,
                    "label": clean_comp,
                    "content_base64": None,
                })
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
