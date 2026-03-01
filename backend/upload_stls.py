"""
Standalone script to upload STL files from cad_library/components/ to Supabase.

Schema (component_assets table):
  - id            : auto-generated
  - component_name: human-readable name derived from filename
  - asset_type    : "stl"
  - url           : public storage URL
  - label         : clean filename stem (lowercase, underscores)
  - created_at    : auto-generated
  - content_base64: base64-encoded STL content

Usage:
  python upload_stls.py                        # uploads all STLs in cad_library/components/
  python upload_stls.py path/to/file.stl ...   # uploads specific files
"""

import os
import sys
import base64
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BUCKET       = "hardware_assets"
TABLE        = "component_assets"
STL_DIR      = Path(__file__).parent / "cad_library" / "components"


def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_stl(client: Client, stl_path: Path) -> None:
    label = stl_path.stem.lower().replace(" ", "_")           # e.g. "esp32"
    component_name = stl_path.stem.replace("_", " ").title()  # e.g. "Esp32"
    storage_path = f"stls/{label}.stl"

    print(f"  Reading  : {stl_path.name}")
    content = stl_path.read_bytes()
    content_b64 = base64.b64encode(content).decode("utf-8")

    # Upload to storage (upsert so re-runs are safe)
    print(f"  Uploading: {storage_path}")
    try:
        client.storage.from_(BUCKET).upload(
            storage_path, content, file_options={"upsert": "true"}
        )
    except Exception as e:
        print(f"  !! Storage upload error: {e}")
        return

    public_url: str = client.storage.from_(BUCKET).get_public_url(storage_path)

    # Upsert DB record — match on (label, asset_type) to avoid duplicates
    print(f"  Saving DB : {TABLE} <- label={label}")
    try:
        client.table(TABLE).upsert(
            {
                "component_name": component_name,
                "asset_type":      "stl",
                "url":             public_url,
                "label":           label,
                "content_base64":  content_b64,
            },
            on_conflict="label,asset_type",
        ).execute()
    except Exception as e:
        print(f"  !! DB save error: {e}")
        return

    print(f"  Done      : {public_url}\n")


def collect_stl_paths(args: list[str]) -> list[Path]:
    if args:
        paths = [Path(p) for p in args]
        missing = [p for p in paths if not p.exists()]
        if missing:
            for m in missing:
                print(f"File not found: {m}")
            sys.exit(1)
        return paths

    if not STL_DIR.exists():
        print(f"STL directory not found: {STL_DIR}")
        sys.exit(1)

    paths = sorted(STL_DIR.glob("*.stl"))
    if not paths:
        print(f"No .stl files found in {STL_DIR}")
        sys.exit(0)
    return paths


def main() -> None:
    client = get_client()
    stl_paths = collect_stl_paths(sys.argv[1:])

    print(f"Uploading {len(stl_paths)} STL file(s) to Supabase...\n")
    for path in stl_paths:
        print(f"[{path.name}]")
        upload_stl(client, path)

    print("All done.")


if __name__ == "__main__":
    main()
