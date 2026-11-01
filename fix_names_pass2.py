"""
Pass 2: Fix remaining IUPAC names using PubChem /synonyms endpoint.

Identifies entries that still have long chemical names (heuristic: name has
brackets, length > 40, or is empty) and resolves them via /synonyms.
"""

import csv
import re
import time
import requests
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "processed" / "cid_to_name_cache.csv"

# ── Read current cache ────────────────────────────────────────────────
print("Reading cache...")
rows = []
with open(CACHE_PATH, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

# ── Identify entries that need fixing ─────────────────────────────────
def needs_fix(name: str) -> bool:
    if not name or not name.strip():
        return True  # empty
    n = name.strip()
    # Likely IUPAC if it contains brackets/square brackets and is longish
    if len(n) > 35 and ("[" in n or "{" in n or "(" in n):
        return True
    # Very long names are likely IUPAC
    if len(n) > 50:
        return True
    # Contains typical IUPAC fragments
    iupac_markers = ["yl)", "yl-", "oyl", "amino-", "oxo-", "thia-", "aza-",
                      "bicyclo", "pyrimidin", "oxolan", "inden-", "hexahydro",
                      "propionic", "carboxamide", "naphthyl", "furano",
                      "pentofuranosyl", "methylene", "ethylidene"]
    n_lower = n.lower()
    if any(m in n_lower for m in iupac_markers):
        return True
    # Names starting with numbers followed by dash are often IUPAC
    if re.match(r'^\d+-[({[]', n):
        return True
    return False

to_fix = [(i, row) for i, row in enumerate(rows) if needs_fix(row["name"])]
print(f"Found {len(to_fix)} entries needing better names out of {len(rows)} total.")

if not to_fix:
    print("All names look good! Nothing to do.")
    exit(0)

# ── Query PubChem /synonyms for each ─────────────────────────────────
HEADERS = {"User-Agent": "InteractomeX/2.3 (name-fix-pass2)"}
BATCH_SIZE = 100

# Build list of numeric CIDs
fix_items = []
for idx, row in to_fix:
    cid_str = row["drug_id"].strip()
    num = cid_str.upper().replace("CID", "").lstrip("0") or "0"
    fix_items.append((idx, cid_str, num, row["name"]))

# Batch query synonyms
numeric_cids = [item[2] for item in fix_items]
cid_to_best_name = {}

total_batches = (len(numeric_cids) + BATCH_SIZE - 1) // BATCH_SIZE
print(f"Querying PubChem /synonyms in {total_batches} batches...")

for batch_idx in range(0, len(numeric_cids), BATCH_SIZE):
    batch = numeric_cids[batch_idx:batch_idx + BATCH_SIZE]
    batch_num = batch_idx // BATCH_SIZE + 1
    cid_list = ",".join(batch)

    url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid_list}"
        f"/synonyms/JSON"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for info in data.get("InformationList", {}).get("Information", []):
            cid_num = str(info.get("CID", ""))
            synonyms = info.get("Synonym", [])
            if not synonyms or not cid_num:
                continue

            # Pick the best synonym: prefer short, recognizable generic names
            best = None
            for syn in synonyms:
                s = syn.strip()
                # Skip very long names (IUPAC)
                if len(s) > 40:
                    continue
                # Skip names that are just numbers or CAS numbers
                if re.match(r'^\d[\d-]*\d$', s):
                    continue
                # Skip UNII codes and similar alphanumeric codes
                if re.match(r'^[A-Z0-9]{8,}$', s):
                    continue
                # First short, readable name wins
                best = s
                break

            if not best and synonyms:
                # Fallback: just use the first synonym
                best = synonyms[0].strip()

            if best:
                cid_to_best_name[cid_num] = best

        resolved = sum(1 for c in batch if c in cid_to_best_name)
        print(f"  Batch {batch_num}/{total_batches}: resolved {resolved}/{len(batch)}")

    except Exception as e:
        print(f"  Batch {batch_num}/{total_batches}: ERROR - {e}")
        # Individual fallback
        for cid_num in batch:
            if cid_num in cid_to_best_name:
                continue
            try:
                url2 = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid_num}/synonyms/JSON"
                r2 = requests.get(url2, headers=HEADERS, timeout=10)
                r2.raise_for_status()
                info_list = r2.json().get("InformationList", {}).get("Information", [])
                if info_list:
                    syns = info_list[0].get("Synonym", [])
                    if syns:
                        cid_to_best_name[cid_num] = syns[0].strip()
            except Exception:
                pass
            time.sleep(0.25)

    time.sleep(0.5)

# ── Apply fixes ──────────────────────────────────────────────────────
fixed = 0
still_bad = 0
for idx, cid_str, num_cid, old_name in fix_items:
    new_name = cid_to_best_name.get(num_cid)
    if new_name:
        rows[idx]["name"] = new_name
        if new_name != old_name:
            fixed += 1
            old_display = (old_name[:40]+'...') if len(old_name or '')>40 else repr(old_name)
            print(f"  [OK] {cid_str}: {old_display} -> {new_name}")
    else:
        still_bad += 1

# ── Write updated cache ─────────────────────────────────────────────
with open(CACHE_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["drug_id", "name"])
    writer.writeheader()
    writer.writerows(rows)

print(f"\n{'='*50}")
print(f"Pass 2 complete!")
print(f"  Fixed:        {fixed}")
print(f"  Still missing: {still_bad}")
print(f"  Total:         {len(rows)}")
print(f"\nRestart uvicorn to pick up the new names.")
