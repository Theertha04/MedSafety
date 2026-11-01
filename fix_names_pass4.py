"""
Pass 4: Final override for remaining well-known drugs still showing IUPAC names.
"""
import csv
from pathlib import Path

CACHE_PATH = Path(__file__).parent / "data" / "processed" / "cid_to_name_cache.csv"

# Additional overrides for remaining drugs with IUPAC names
OVERRIDES = {
    "3823": "Ketoconazole",
    "4920": "Progesterone",
    "32797": "Halobetasol",
    "5038": "Ramipril",
    "5005": "Quinapril",
    "4259": "Moxifloxacin",
    "2666": "Cephalexin",
    "4889": "Pravastatin",
    "41774": "Acarbose",
    "4635": "Oxycodone",
    "5650": "Valsartan",
    "3750": "Irinotecan",
    "4666": "Paclitaxel",
    "5538": "Tretinoin",
    "5311297": "Montelukast",
    "1065": "Quinine",
    "4599": "Orlistat",
    "5512": "Tolterodine",
    "450": "Estradiol",
    "5672": "Vinblastine",
    "2487": "Butorphanol",
    "27686": "Cromoglicic Acid",
    "3154": "Dorzolamide",
    "772": "Enoxaparin",
    "2609": "Cefaclor",
    "3661": "Atropine",
    "4419": "Nalbuphine",
    "5203": "Sertraline",
    "3404": "Fluvoxamine",
    "3255": "Erythromycin",
    "5077": "Rivastigmine",
    "3279": "Ethambutol",
    "4253": "Morphine",
    "4659568": "Entacapone",
    "159": "Alprostadil",
    "163742": "Fondaparinux",
    "54688": "Dirithromycin",
    "12536": "Budesonide",
    "3468412": "Amphotericin B",
    "1972": "Nystatin",
    "2171": "Amoxicillin",
    "2712": "Chlordiazepoxide",
    "47725": "Triptorelin",
    "2476": "Buprenorphine",
    "2283": "Leuprolide",
    "5381226": "Sirolimus",
    "3405": "Fluvastatin",
}

# Read cache
print("Reading cache...")
rows = []
with open(CACHE_PATH, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

fixed = 0
for i, row in enumerate(rows):
    cid_str = row["drug_id"].strip()
    num = cid_str.upper().replace("CID", "").lstrip("0") or "0"
    if num in OVERRIDES:
        old = row["name"]
        new = OVERRIDES[num]
        if old != new:
            rows[i]["name"] = new
            fixed += 1
            old_short = (old[:35] + "...") if len(old or "") > 35 else (old or "(empty)")
            print(f"  {cid_str}: {old_short} -> {new}")

# Write
with open(CACHE_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["drug_id", "name"])
    writer.writeheader()
    writer.writerows(rows)

# Stats
empty = sum(1 for r in rows if not r["name"].strip())
has_name = sum(1 for r in rows if r["name"].strip())
print(f"\nFixed {fixed} entries. {has_name}/{len(rows)} now have names ({empty} empty).")
print("Restart uvicorn to pick up changes.")
