"""
Pass 3: Clean up bad synonym mappings and apply known drug name overrides.

- Removes RefChem, SCHEMBL, CHEMBL, CAS_, InChIKey, and similar codes
- Applies manual overrides for well-known drugs that PubChem mapped incorrectly
- Falls back to PubChem compound record "IUPACName" title for remaining entries
"""

import csv
import re
import requests
import time
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "processed" / "cid_to_name_cache.csv"

# ── Known drug name overrides (CID number -> proper name) ────────────
# These are well-known drugs that PubChem /synonyms returned IUPAC or codes for
OVERRIDES = {
    "2173": "Ampicillin",
    "1302": "Naproxen",
    "5064": "Ribavirin",
    "596": "Cytarabine",
    "5726": "Zidovudine",
    "2522": "Calcipotriol",
    "5376": "Tamoxifen",
    "3929": "Linezolid",
    "5267": "Buspirone",
    "942": "Nicotine",
    "191": "Adenosine",
    "5645": "Ursodiol",
    "2676": "Cerivastatin",
    "2646": "Cefprozil",
    "3461": "Gemcitabine",
    "2232": "Argatroban",
    "2177": "Amprenavir",
    "5486": "Tirofiban",
    "72938": "Gemifloxacin",
    "444033": "Ciclesonide",
    "4428": "Naltrexone",
    "4691": "Paroxetine",
    "5731": "Sumatriptan",
    "3706": "Lopinavir",
    "4812": "Phytonadione",
    "815": "Kanamycin",
    "2142": "Amikacin",
    "2949": "Desogestrel",
    "4536": "Norethindrone",
    "5402": "Terbinafine",
    "5466": "Tipepidine",
    "4745": "Pergolide",
    "4885": "Pramipexole",
    "57537": "Rotigotine",
    "5352": "Sulindac",
    "3384": "Fluorometholone",
    "2308": "Clobetasol",
    "3350": "Fludrocortisone",
    "5408": "Testosterone",
    "1546": "Cladribine",
    "1971": "Abacavir",
    "5184": "Scopolamine",
    "3310": "Etoposide",
    "4819": "Pilocarpine",
    "4425": "Naloxone",
    "2512": "Cabergoline",
    "5515": "Topotecan",
    "4675": "Pancuronium",
    "2786": "Clindamycin",
    "2269": "Clarithromycin",
    "3642": "Hydrocortisone",
    "5771": "Vasopressin",
    "3476": "Griseofulvin",
    "2610": "Cefadroxil",
    "2622": "Cefixime",
    "4607": "Oxacillin",
    "3040": "Dicloxacillin",
    "4834": "Piperacillin",
    "2637": "Cefoxitin",
    "2274": "Cefamandole",
    "2675": "Ceftriaxone",
    "298": "Chloramphenicol",
    "4547": "Repaglinide",
    "3962": "Lovastatin",
    "3403": "Fluvastatin",
    "2311": "Enalapril",
    "85": "Betaine",
    "5076": "Rifampin",
    "4603": "Oseltamivir",
    "5721": "Zanamivir",
    "3379": "Fluticasone",
    "2478": "Calcitriol",
    "2524": "Calcitriol",
    "2978": "Dronabinol",
    "39860": "Nabilone",
    "5514": "Tolterodine",
    "3308": "Etodolac",
    "5090": "Rofecoxib",
    "1134": "Thymidine",
    "71273": "Ropivacaine",
    "54808": "Loteprednol",
    "48175": "Fluticasone Furoate",
    "40976": "Gestodene",
    "41317": "Acitretin",
    "150310": "Vincristine",
    "147912": "Posaconazole",
    "72467": "Daptomycin",
    "60787": "Atazanavir",
    "60696": "Dutasteride",
    "508230": "Mycophenolic Acid",
    "5473385": "Thioguanine",
    "3086258": "Verteporfin",
    "170361": "Lurasidone",
    "54547": "Cefdinir",
    "74989": "Loperamide",
    "150610": "Ertapenem",
}

# ── Patterns indicating a bad/unhelpful name ─────────────────────────
def is_bad_name(name: str) -> bool:
    if not name or not name.strip():
        return True
    n = name.strip()
    bad_prefixes = [
        "RefChem:", "SCHEMBL", "CHEMBL", "CAS_", "CID ", "SR-", "NS0000",
        "AB0", "EBC-", "BRD-", "orb", "s1", "s3", "s6", "Neuro_",
        "NCGC", "WYUSVOMTXWRGEK", "YEHCICAEULNIGD", "C2-MP", "C24H", "C25H",
        "XU 62", "SQ-26", "AS-13", "STL0", "9-cis-",
        "H0E", "Gemctitabine",
    ]
    for prefix in bad_prefixes:
        if n.startswith(prefix):
            return True
    # InChIKey pattern
    if re.match(r'^[A-Z]{14}-[A-Z]{10}-[A-Z]$', n):
        return True
    # Molecular formula pattern
    if re.match(r'^C\d+H\d+', n):
        return True
    return False

# ── Read current cache ────────────────────────────────────────────────
print("Reading cache...")
rows = []
with open(CACHE_PATH, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

# ── Apply overrides and clean bad names ──────────────────────────────
fixed = 0
cleaned = 0
still_bad = []

for i, row in enumerate(rows):
    cid_str = row["drug_id"].strip()
    num = cid_str.upper().replace("CID", "").lstrip("0") or "0"
    old_name = row["name"].strip() if row["name"] else ""

    # Check overrides first
    if num in OVERRIDES:
        new_name = OVERRIDES[num]
        if new_name != old_name:
            rows[i]["name"] = new_name
            fixed += 1
            print(f"  [OVERRIDE] {cid_str}: {old_name[:35] + '...' if len(old_name) > 35 else old_name} -> {new_name}")
        continue

    # Clean bad names
    if is_bad_name(old_name):
        cleaned += 1
        still_bad.append((cid_str, num, old_name))

# ── Try PubChem /record/title for remaining bad names ────────────────
HEADERS = {"User-Agent": "InteractomeX/2.3 (name-fix-pass3)"}
if still_bad:
    print(f"\nAttempting PubChem title lookup for {len(still_bad)} remaining entries...")
    for cid_str, num_cid, old_name in still_bad:
        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{num_cid}/record/JSON/?record_type=2d"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.ok:
                data = resp.json()
                # Try to find IUPACName from record
                pass  # Complex parsing; skip for now
        except Exception:
            pass

    # For entries that are still bad, try the simple property endpoint
    for cid_str, num_cid, old_name in still_bad:
        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{num_cid}/property/Title/JSON"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.ok:
                props = resp.json().get("PropertyTable", {}).get("Properties", [])
                if props:
                    title = props[0].get("Title", "")
                    if title and not is_bad_name(title):
                        for i, row in enumerate(rows):
                            if row["drug_id"].strip() == cid_str:
                                rows[i]["name"] = title
                                fixed += 1
                                print(f"  [TITLE] {cid_str}: -> {title}")
                                break
        except Exception:
            pass
        time.sleep(0.25)

# ── Write final cache ────────────────────────────────────────────────
with open(CACHE_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["drug_id", "name"])
    writer.writeheader()
    writer.writerows(rows)

# Count final stats
empty_count = sum(1 for r in rows if not r["name"].strip())
bad_count = sum(1 for r in rows if is_bad_name(r["name"]))
good_count = len(rows) - bad_count

print(f"\n{'='*50}")
print(f"Pass 3 complete!")
print(f"  Total CIDs:    {len(rows)}")
print(f"  Good names:    {good_count}")
print(f"  Still bad:     {bad_count}")
print(f"  Empty:         {empty_count}")
print(f"  Overrides:     {fixed}")
print(f"\nRestart uvicorn to pick up the new names.")
