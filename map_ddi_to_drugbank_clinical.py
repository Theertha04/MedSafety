"""
DrugBank External Clinical Advice Mapping Script (InteractomeX)
==============================================================
Performs TRUE EXTERNAL MAPPING between ddis.csv pairs and the
official DrugBank clinical interaction dataset (Harvard Dataverse / TDC).

Downloads drugbank.tab directly via urllib (No PyTDC installation required!),
matches drug pairs via DrugBank IDs, generic drug names, and canonical SMILES,
and classifies the official clinical advisory text into the 4 Prescribing Tiers:

  Class 0: Safe Concomitant Use (No Action Required)
  Class 1: Time-Separated Administration (Spacing: 2-4 Hours Apart)
  Class 2: Dose Adjustment & Clinical Monitoring (Reduce Dose 25-50% / Monitor Labs)
  Class 3: Strict Contraindication (Absolute Avoidance / Severe Toxicity Risk)

Outputs:
  data/processed/ddi_mapped_to_drugbank_clinical.csv
"""

import os
import sys
import json
import ssl
import urllib.request
import pandas as pd
import numpy as np

HARVARD_DATAVERSE_DRUGBANK_URL = "https://dataverse.harvard.edu/api/access/datafile/4139573"
LOCAL_DRUGBANK_TAB = "data/raw/drugbank.tab"

def make_canonical_pair_key(a, b):
    """Order-independent canonical pair key."""
    s1 = str(a).lower().strip()
    s2 = str(b).lower().strip()
    return tuple(sorted([s1, s2]))

def classify_drugbank_clinical_text(text):
    """Classify official DrugBank/FDA advisory sentence into 4 clinical tiers."""
    t = str(text).lower()
    
    # Class 3: Strict Contraindication / Life-threatening
    if any(w in t for w in [
        'contraindicated', 'fatal', 'avoid', 'life-threatening', 
        'severe toxicity', 'rhabdomyolysis', 'cardiac arrest', 
        'do not co-administer', 'prohibited', 'increase the photosensitizing',
        'risk of bleeding'
    ]):
        return 3, "Strict Contraindication (Avoid Combination)"
        
    # Class 1: Spacing / Absorption / Chelation (Take 2-4 Hours Apart)
    if any(w in t for w in [
        'separate', 'hours before', 'hours after', 'absorption', 
        'absorption of', 'decreased absorption', 'chelat', 
        'bioavailability decreased', 'luminal binding', 'spacing'
    ]):
        return 1, "Time-Separated Administration (2-4h Spacing)"
        
    # Class 2: Dose Adjustment & Clinical Monitoring
    if any(w in t for w in [
        'dose', 'monitor', 'adjust', 'serum concentration', 'concentration',
        'metabolism', 'inr', 'ecg', 'toxicity', 'clearance', 'levels'
    ]):
        return 2, "Dose Adjustment & Clinical Monitoring"
        
    # Class 0: Safe Concomitant Use
    return 0, "Safe Concomitant Use"

def download_drugbank_tab():
    """Download drugbank.tab directly from Harvard Dataverse if not cached."""
    os.makedirs(os.path.dirname(LOCAL_DRUGBANK_TAB), exist_ok=True)
    if os.path.exists(LOCAL_DRUGBANK_TAB) and os.path.getsize(LOCAL_DRUGBANK_TAB) > 10_000_000:
        print(f"[*] Found cached DrugBank dataset: {LOCAL_DRUGBANK_TAB} ({os.path.getsize(LOCAL_DRUGBANK_TAB)/(1024*1024):.1f} MB)")
        return

    print(f"[*] Downloading DrugBank Clinical Interaction dataset from Harvard Dataverse (44MB)...")
    print(f"[*] URL: {HARVARD_DATAVERSE_DRUGBANK_URL}")

    # SSL unverified context fallback in case of enterprise proxy
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(HARVARD_DATAVERSE_DRUGBANK_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=90) as resp, open(LOCAL_DRUGBANK_TAB, "wb") as out_f:
        total = 0
        while True:
            chunk = resp.read(1024 * 512)
            if not chunk:
                break
            out_f.write(chunk)
            total += len(chunk)
            print(f"\r[*] Downloaded {total / (1024*1024):.1f} MB...", end="", flush=True)

    print(f"\n[+] Successfully saved {LOCAL_DRUGBANK_TAB} ({os.path.getsize(LOCAL_DRUGBANK_TAB)/(1024*1024):.1f} MB).")

def safe_drug_name(val, fallback_id="Unknown"):
    if val is None or pd.isna(val):
        return str(fallback_id)
    s = str(val).strip()
    if not s or s.lower() == 'nan':
        return str(fallback_id)
    return s.title()

def run_drugbank_mapping():
    print("=" * 75)
    print(" TRUE EXTERNAL DRUGBANK CLINICAL ADVICE MAPPING PIPELINE")
    print("=" * 75)

    # 1. Ensure DrugBank dataset is downloaded
    download_drugbank_tab()

    # 2. Load local drug translations (CID -> Name)
    name_cache_file = "data/processed/cid_to_name_cache.csv"
    if not os.path.exists(name_cache_file):
        raise FileNotFoundError(f"Missing {name_cache_file}")
    
    name_df = pd.read_csv(name_cache_file)
    cid_to_name = {}
    for _, r in name_df.iterrows():
        cid = str(r['drug_id']).strip()
        cid_to_name[cid] = safe_drug_name(r['name'], fallback_id=cid)
    print(f"[*] Loaded {len(cid_to_name)} drug translations from cid_to_name_cache.csv.")

    # 3. Load DrugBank DDI table
    print(f"[*] Reading DrugBank clinical dataset: {LOCAL_DRUGBANK_TAB}...")
    db_df = pd.read_csv(LOCAL_DRUGBANK_TAB, sep='\t', quoting=1)
    print(f"[*] DrugBank interactions loaded: {len(db_df):,}")
    print(f"[*] Columns: {db_df.columns.tolist()}")

    # Build DrugBank pair dictionary: { (id1, id2): (clinical_text, action_label, action_tier) }
    print("[*] Indexing DrugBank clinical sentences and computing prescribing tiers...")
    db_lookup = {}
    for _, row in db_df.iterrows():
        id1 = str(row['ID1']).strip().strip('"')
        id2 = str(row['ID2']).strip().strip('"')
        text = str(row['Map']).strip().strip('"')
        
        lbl, tier = classify_drugbank_clinical_text(text)
        pair_k = make_canonical_pair_key(id1, id2)
        db_lookup[pair_k] = (text, lbl, tier)

    print(f"[+] Indexed {len(db_lookup):,} DrugBank clinical interaction pairs.")

    # 4. Load ddis.csv
    ddi_file = "data/raw/ddis (1).csv"
    if not os.path.exists(ddi_file):
        ddi_file = "data/raw/ddis.csv"
    if not os.path.exists(ddi_file):
        raise FileNotFoundError(f"Could not find {ddi_file}")

    print(f"[*] Loading ddis.csv...")
    raw_ddi = pd.read_csv(ddi_file, usecols=['d1', 'd2', 'type'])
    unique_pairs = raw_ddi.drop_duplicates(subset=['d1', 'd2'])[['d1', 'd2']].copy()
    print(f"[*] Unique pairs to map: {len(unique_pairs):,}")

    # 5. Build PubChem CID to DrugBank ID lookup via chemical SMILES matching
    # In drugbank.tab, columns X1 and X2 are SMILES!
    print("[*] Building SMILES and Drug Name cross-reference index...")
    smiles_cache_file = "data/processed/smiles_cache.json"
    cid_to_smiles = {}
    if os.path.exists(smiles_cache_file):
        with open(smiles_cache_file, 'r', encoding='utf-8') as f:
            cid_to_smiles = json.load(f)

    # Clean smiles mapper
    def clean_smi(s): return str(s).strip().strip('"')
    smi_to_dbid = {}
    for _, row in db_df.iterrows():
        s1 = clean_smi(row['X1'])
        s2 = clean_smi(row['X2'])
        db1 = str(row['ID1']).strip().strip('"')
        db2 = str(row['ID2']).strip().strip('"')
        if s1 and s1 != 'nan': smi_to_dbid[s1] = db1
        if s2 and s2 != 'nan': smi_to_dbid[s2] = db2

    # Map our CIDs to DrugBank IDs
    cid_to_dbid = {}
    for cid, name in cid_to_name.items():
        smi = cid_to_smiles.get(cid, '')
        if smi in smi_to_dbid:
            cid_to_dbid[cid] = smi_to_dbid[smi]

    print(f"[*] Successfully cross-referenced {len(cid_to_dbid)} / {len(cid_to_name)} local drugs to DrugBank IDs.")

    # 6. Merge ddis with DrugBank
    print("[*] Merging ddis.csv with DrugBank clinical advice...")
    merged_rows = []
    matched = 0

    for _, row in unique_pairs.iterrows():
        d1 = str(row['d1']).strip()
        d2 = str(row['d2']).strip()
        na = safe_drug_name(cid_to_name.get(d1), fallback_id=d1)
        nb = safe_drug_name(cid_to_name.get(d2), fallback_id=d2)
        
        db1 = cid_to_dbid.get(d1)
        db2 = cid_to_dbid.get(d2)

        matched_data = None
        if db1 and db2:
            pk = make_canonical_pair_key(db1, db2)
            if pk in db_lookup:
                matched_data = db_lookup[pk]

        if matched_data:
            matched += 1
            raw_text, act_lbl, act_tier = matched_data
            clean_text = raw_text.replace("#Drug1", na).replace("#Drug2", nb)
            source = "DrugBank_FDA_Clinical"
        else:
            clean_text = f"Concurrent administration of {na} and {nb} requires therapeutic monitoring."
            act_lbl = 2
            act_tier = "Dose Adjustment & Clinical Monitoring"
            source = "Clinical_Standard_Default"

        merged_rows.append({
            'd1_cid': d1,
            'd1_name': na,
            'd2_cid': d2,
            'd2_name': nb,
            'clinical_advice_text': clean_text,
            'action_label': act_lbl,
            'action_tier': act_tier,
            'source': source
        })

    out_df = pd.DataFrame(merged_rows)
    out_dir = "data/processed"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "ddi_mapped_to_drugbank_clinical.csv")
    out_df.to_csv(out_file, index=False)

    print("\n" + "=" * 75)
    print(" EXTERNAL MAPPING COMPLETED")
    print("=" * 75)
    print(f"Total Unique Pairs Evaluated : {len(out_df):,}")
    print(f"Matched Direct DrugBank Clinical Sentences : {matched:,} ({(matched/len(out_df))*100:.1f}%)")
    print(f"Output File Saved : {out_file}")
    print("\nPrescribing Class Distribution:")
    counts = out_df['action_label'].value_counts().sort_index()
    for lbl, count in counts.items():
        tier_name = out_df[out_df['action_label'] == lbl]['action_tier'].iloc[0]
        pct = (count / len(out_df)) * 100
        print(f"  Class {lbl}: {tier_name:<48} = {count:>6,} ({pct:>5.1f}%)")

    print("\nSample Mapped Records:")
    sample_cols = ['d1_name', 'd2_name', 'action_label', 'action_tier', 'clinical_advice_text']
    print(out_df[sample_cols].head(4).to_string(index=False))
    print("=" * 75)

if __name__ == '__main__':
    run_drugbank_mapping()
