import os
import httpx
from tavily import TavilyClient
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

class SearchService:
    def __init__(self):
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            print("WARNING: TAVILY_API_KEY not found in .env. Search will fail.")
        self.tavily = TavilyClient(api_key=api_key)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    async def search_tavily(self, query: str, search_depth: str = "advanced", num_results: int = 5) -> List[str]:
        """
        Search using Tavily AI Search.
        """
        try:
            # Tavily is optimized for LLM agents
            response = self.tavily.search(query=query, search_depth=search_depth, max_results=num_results)
            return [r['url'] for r in response.get('results', [])]
        except Exception as e:
            print(f"Tavily Search error: {e}")
            return []

    async def search_datasheets(self, component_name: str) -> List[str]:
        """
        Search for datasheets, prioritizing credible sources.
        """
        credible_domains = ["digikey.com", "mouser.com", "rs-online.com", "farnell.com", "ti.com", "st.com", "analog.com"]
        site_query = " OR ".join([f"site:{domain}" for domain in credible_domains])
        query = f"{component_name} official datasheet pdf ({site_query})"
        
        print(f"Searching Tavily for {component_name} datasheets...")
        return await self.search_tavily(query, num_results=3)

    async def search_stls(self, component_name: str) -> List[str]:
        """
        Search for 3D STL files.
        """
        query = f"{component_name} 3D model STL file GrabCAD SnapEDA"
        print(f"Searching Tavily for {component_name} STL models...")
        return await self.search_tavily(query, num_results=3)

    async def download_file(self, url: str) -> Optional[bytes]:
        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True) as client:
            try:
                print(f"Downloading: {url}")
                response = await client.get(url, timeout=15)
                if response.status_code == 200:
                    return response.content
                else:
                    print(f"Failed to download {url}: Status {response.status_code}")
            except Exception as e:
                print(f"Error downloading {url}: {e}")
        return None
