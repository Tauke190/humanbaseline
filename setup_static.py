#!/usr/bin/env python3
"""
Copy 5 smallest videos per class into human_baseline/static/videos/
and generate manifest.json for the static Netlify site.

Usage:
    python setup_static.py
"""

import csv
import json
import os
import shutil
from pathlib import Path

VARIANTS_CSV  = Path("/mnt/SSD2/SyntheticPatientCare/patient_actions_semantic_variants.csv")
VIDEOS_SRC    = Path("/mnt/SSD2/synthetic_patient_output/patient_care_videos/reallife")
DEST_VIDEOS   = Path(__file__).parent / "static" / "videos"
MANIFEST_OUT  = Path(__file__).parent / "manifest.json"

IGNORE_IDS       = {8, 9, 11}  # 0-based
VIDEOS_PER_CLASS = 5

# ---------------------------------------------------------------------------
# Load class names from variants CSV (1-based IDs → 0-based)
# ---------------------------------------------------------------------------
classes = {}
with open(VARIANTS_CSV) as f:
    for row in csv.DictReader(f):
        cid  = int(row["id"]) - 1
        name = row["class_name"].strip()
        classes[cid] = name[0].upper() + name[1:]

# ---------------------------------------------------------------------------
# Copy videos and build manifest
# ---------------------------------------------------------------------------
video_entries = []
total_bytes   = 0

for folder in sorted(VIDEOS_SRC.iterdir()):
    if not folder.is_dir():
        continue
    # Folder name starts with 2-digit 1-based number, e.g. "01_patient_lying..."
    try:
        cid = int(folder.name[:2]) - 1
    except ValueError:
        continue

    if cid in IGNORE_IDS or cid not in classes:
        continue

    mp4s = sorted(folder.glob("*.mp4"), key=lambda p: p.stat().st_size)
    if not mp4s:
        print(f"  [skip] {folder.name} — no mp4 files")
        continue

    selected = mp4s[:VIDEOS_PER_CLASS]
    dest_dir = DEST_VIDEOS / folder.name
    dest_dir.mkdir(parents=True, exist_ok=True)

    for src in selected:
        dest = dest_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
        size = src.stat().st_size
        total_bytes += size
        rel = f"static/videos/{folder.name}/{src.name}"
        video_entries.append({
            "path":       rel,
            "class_id":   cid,
            "class_name": classes[cid],
        })
        print(f"  {rel}  ({size // 1024} KB)")

# ---------------------------------------------------------------------------
# Write manifest
# ---------------------------------------------------------------------------
manifest = {
    "classes": [
        {"id": cid, "name": name}
        for cid, name in sorted(classes.items())
        if cid not in IGNORE_IDS
    ],
    "videos": video_entries,
}
MANIFEST_OUT.write_text(json.dumps(manifest, indent=2))

print(f"\n{'='*60}")
print(f"Videos:   {len(video_entries)} ({total_bytes / 1_000_000:.1f} MB total)")
print(f"Classes:  {len(manifest['classes'])}")
print(f"Manifest: {MANIFEST_OUT}")
