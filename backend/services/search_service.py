from googlesearch import search
import httpx
from bs4 import BeautifulSoup
from urllib.parse import unquote
from typing import List, Optional

class SearchService:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def search_google(self, query: str, num_results: int = 5) -> List[str]:
        """
        Use the googlesearch-python library.
        """
        try:
            results = search(query, num_results=num_results)
            return list(results)
        except Exception as e:
            print(f"Google Search error: {e}")
            return []

    async def search_ddg(self, query: str, num_results: int = 5) -> List[str]:
        """
        Fallback scraper for DuckDuckGo.
        """
        url = f"https://html.duckduckgo.com/html/?q={query}"
        async with httpx.AsyncClient(headers=self.headers) as client:
            try:
                response = await client.get(url, timeout=10)
                if response.status_code != 200:
                    return []
                
                soup = BeautifulSoup(response.text, 'html.parser')
                links = []
                for a in soup.find_all('a', class_='result__a', href=True):
                    href = a['href']
                    if 'uddg=' in href:
                        actual_url = href.split('uddg=')[1].split('&')[0]
                        links.append(unquote(actual_url))
                    else:
                        links.append(href)
                        
                    if len(links) >= num_results:
                        break
                return links
            except Exception as e:
                print(f"DDG Search error: {e}")
                return []

    async def search_hybrid(self, query: str, num_results: int = 5) -> List[str]:
        """
        Try Google first, fallback to DDG.
        """
        results = self.search_google(query, num_results)
        if not results:
            print(f"Falling back to DDG for query: {query}")
            results = await self.search_ddg(query, num_results)
        return results

    async def search_datasheets(self, component_name: str) -> List[str]:
        query = f"{component_name} datasheet filetype:pdf"
        return await self.search_hybrid(query)

    async def search_stls(self, component_name: str) -> List[str]:
        query = f"{component_name} 3D model STL GrabCAD SnapEDA"
        return await self.search_hybrid(query)

    async def download_file(self, url: str) -> Optional[bytes]:
        async with httpx.AsyncClient(headers=self.headers) as client:
            try:
                response = await client.get(url, timeout=10, follow_redirects=True)
                if response.status_code == 200:
                    return response.content
            except Exception as e:
                print(f"Error downloading {url}: {e}")
        return None
