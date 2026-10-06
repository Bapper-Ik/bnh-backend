"""Copy product reference snapshots into both repositories for standalone clones."""

import hashlib
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sources = root / "docs"
for repo in ("bnh-backend", "bnh-ui"):
    dest = root / repo / "docs" / "reference"
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ("implementation_pan.md", "features.md", "recap.md"):
        source = sources / name
        shutil.copyfile(source, dest / name)
        rows.append(f"- {name}: {hashlib.sha256(source.read_bytes()).hexdigest()}")
    (dest / "README.md").write_text(
        "# Product reference snapshots\n\n"
        "Generated from the shared workspace docs. Do not maintain a second tracker here. "
        "The shared docs/implementation_pan.md is canonical while working in the paired workspace. "
        "For a standalone clone, these snapshots preserve the agreed product requirements; "
        "bring both repositories and shared docs together before synchronising progress. "
        "Personal-data screenshots are intentionally not copied into Git.\n\n"
        "Regenerate from the paired workspace with python3 scripts/sync_requirements.py in bnh-backend.\n\n"
        + "\n".join(rows)
        + "\n"
    )
print("Copied requirement snapshots without personal-data screenshots.")
