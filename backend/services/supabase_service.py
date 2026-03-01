import os
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

class SupabaseService:
    def __init__(self):
        url: str = os.getenv("SUPABASE_URL", "")
        key: str = os.getenv("SUPABASE_KEY", "")
        if url and key:
            self.client: Client = create_client(url, key)
        else:
            self.client = None
            print("Supabase credentials not found. MOCK mode active.")

    async def upload_file(self, bucket: str, path: str, content: bytes) -> Optional[str]:
        """
        Uploads a file to a Supabase bucket and returns its URL.
        """
        if not self.client:
            return f"mock_url://{bucket}/{path}"

        try:
            res = self.client.storage.from_(bucket).upload(path, content, file_options={"upsert": "true"})
            # Get public URL
            public_url = self.client.storage.from_(bucket).get_public_url(path)
            return public_url
        except Exception as e:
            print(f"Supabase upload error: {e}")
            return None

    def save_data(self, table: str, data: dict):
        """
        Saves a record to a Supabase table.
        """
        if not self.client:
            print(f"Mock Save to {table}: {data}")
            return

        try:
            self.client.table(table).insert(data).execute()
        except Exception as e:
            print(f"Supabase save error: {e}")
