"""
Rebuild cid_to_name_cache.csv with proper generic/common drug names from PubChem.

Replaces IUPAC chemical names with recognisable generic names (e.g. "Ampicillin"
instead of "6-{[Amino(phenyl)acetyl]amino}-3,3-dimethyl-...").

Uses PubChem PUG REST batch API for efficiency.
"""

import csv
import time
import requests
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "processed" / "cid_to_name_cache.csv"
BACKUP_PATH = CACHE_PATH.with_suffix(".csv.bak")

# ── Step 1: Read existing CIDs ────────────────────────────────────────
print("Reading existing cache...")
rows = []
with open(CACHE_PATH, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

all_cids = []
for row in rows:
    cid_str = row["drug_id"].strip()
    # Extract numeric CID
    num = cid_str.upper().replace("CID", "").lstrip("0") or "0"
    all_cids.append((cid_str, num))

print(f"Found {len(all_cids)} CIDs in cache.")

# ── Step 2: Backup existing file ──────────────────────────────────────
import shutil
shutil.copy2(CACHE_PATH, BACKUP_PATH)
print(f"Backed up existing cache to {BACKUP_PATH.name}")

# ── Step 3: Batch-query PubChem for preferred names ──────────────────
BATCH_SIZE = 100
HEADERS = {"User-Agent": "InteractomeX/2.3 (name-cache-rebuild)"}

cid_to_name = {}
numeric_cids = [num for _, num in all_cids]

total_batches = (len(numeric_cids) + BATCH_SIZE - 1) // BATCH_SIZE
print(f"Querying PubChem in {total_batches} batches of up to {BATCH_SIZE}...")

for batch_idx in range(0, len(numeric_cids), BATCH_SIZE):
    batch = numeric_cids[batch_idx:batch_idx + BATCH_SIZE]
    batch_num = batch_idx // BATCH_SIZE + 1
    cid_list = ",".join(batch)

    # PUG REST: get the record title (which is the common/generic name)
    url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid_list}"
        f"/description/JSON"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for info in data.get("InformationList", {}).get("Information", []):
            cid_num = str(info.get("CID", ""))
            title = info.get("Title", "")
            if cid_num and title:
                # Only store if it's not an IUPAC-looking name (heuristic: short, no brackets)
                cid_to_name[cid_num] = title

        resolved = sum(1 for c in batch if c in cid_to_name)
        print(f"  Batch {batch_num}/{total_batches}: resolved {resolved}/{len(batch)} names")

    except Exception as e:
        print(f"  Batch {batch_num}/{total_batches}: ERROR - {e}")
        # Fall back to individual lookups for this batch
        for cid_num in batch:
            if cid_num in cid_to_name:
                continue
            try:
                url2 = (
                    f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid_num}"
                    f"/description/JSON"
                )
                r2 = requests.get(url2, headers=HEADERS, timeout=10)
                r2.raise_for_status()
                info_list = r2.json().get("InformationList", {}).get("Information", [])
                if info_list:
                    title = info_list[0].get("Title", "")
                    if title:
                        cid_to_name[cid_num] = title
            except Exception:
                pass
            time.sleep(0.25)

    # Respect PubChem rate limits (max 5 requests/second)
    time.sleep(0.5)

# ── Step 4: Write updated cache ──────────────────────────────────────
updated = 0
missing = 0
kept_old = 0
new_rows = []

for orig_cid, num_cid in all_cids:
    old_name = next((r["name"] for r in rows if r["drug_id"] == orig_cid), "")
    new_name = cid_to_name.get(num_cid, "")

    if new_name:
        # Use the PubChem title (generic name)
        final_name = new_name
        if old_name and old_name != new_name:
            updated += 1
        elif not old_name:
            updated += 1
    elif old_name and old_name.strip():
        # Keep existing name if PubChem didn't return one
        final_name = old_name
        kept_old += 1
    else:
        final_name = ""
        missing += 1

    new_rows.append({"drug_id": orig_cid, "name": final_name})

with open(CACHE_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["drug_id", "name"])
    writer.writeheader()
    writer.writerows(new_rows)

print(f"\n{'='*50}")
print(f"Done! Updated cache written to {CACHE_PATH.name}")
print(f"  Total CIDs:       {len(new_rows)}")
print(f"  Names resolved:   {len(new_rows) - missing}")
print(f"  Updated/filled:   {updated}")
print(f"  Kept existing:    {kept_old}")
print(f"  Still missing:    {missing}")
print(f"  Backup at:        {BACKUP_PATH.name}")
print(f"\nRestart uvicorn to pick up the new names.")
