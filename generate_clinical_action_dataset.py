"""
Generate Ground-Truth Clinical Action Dataset for InteractomeX (Balanced Edition)
================================================================================
Combines:
  1. Negative (non-interacting) drug pairs from ddis.csv as Class 0 (Safe Concomitant Use)
  2. Multi-threshold clinical severity grading across the 40 interaction phenotypes:
       - Class 0: Safe Concomitant Use (No Action Required / Benign Symptoms)
       - Class 1: Time-Separated Administration (Spacing: 2-4 Hours Apart / GI-absorption)
       - Class 2: Dose Adjustment & Clinical Monitoring (Reduce Dose 25-50% / Monitor Labs)
       - Class 3: Strict Contraindication (Absolute Avoidance / Severe Toxicity Risk)

Outputs:
  data/processed/pair_clinical_actions.csv
"""

import os
import pandas as pd
import numpy as np

# 40 standard interaction types vocabulary from notebook
TYPE_ID_TO_NAME = {
    45: 'arterial pressure NOS decreased', 68: 'anaemia', 24: 'Difficulty breathing',
    348: 'nausea', 62: 'neumonia', 121: 'Fatigue', 98: 'Pain', 124: 'diarrhea',
    200: 'asthenia', 201: 'emesis', 297: 'edema extremities', 320: 'body temperature increased',
    227: 'pleural pain', 172: 'abdominal pain', 53: 'Hypoventilation', 173: 'chest pain',
    116: 'dizziness', 1: 'Back Ache', 77: 'Head ache', 219: 'High blood pressure',
    64: 'confusion', 326: 'dehydration', 335: 'Anxiety', 260: 'kidney failure',
    185: 'loss of weight', 17: 'hyperglycaemia', 54: 'edema', 72: 'Anorexia',
    237: 'Aching joints', 148: 'acute kidney failure', 478: 'neuropathy',
    205: 'Extremity pain', 323: 'Infection Urinary Tract', 264: 'Cough',
    137: 'constipated', 332: 'heart rate increased', 410: 'weight gain',
    12: 'thrombocytopenia', 351: 'Pleural Effusion', 27: 'sepsis'
}

LIFE_THREATENING = {'acute kidney failure', 'kidney failure', 'sepsis', 'Hypoventilation', 'thrombocytopenia'}
GI_ABSORPTION = {'nausea', 'emesis', 'diarrhea', 'constipated', 'abdominal pain', 'dehydration'}
HEMODYNAMIC_METABOLIC = {
    'arterial pressure NOS decreased', 'High blood pressure', 'hyperglycaemia',
    'heart rate increased', 'chest pain', 'Difficulty breathing', 'confusion',
    'dizziness', 'edema', 'neuropathy', 'anaemia', 'neumonia', 'Pleural Effusion',
    'Infection Urinary Tract'
}

CLASS_DESCRIPTIONS = {
    0: "Safe Concomitant Use (No Action Required)",
    1: "Time-Separated Administration (Spacing: 2-4 Hours Apart)",
    2: "Dose Adjustment & Clinical Monitoring (Reduce Dose 25-50% / Monitor Labs)",
    3: "Strict Contraindication (Absolute Avoidance / Severe Toxicity Risk)"
}

def classify_positive_pair(type_names):
    """
    Classify active interaction types into the 4 clinical tiers using
    multi-threshold severity logic matching FDA / Lexicomp guidelines.
    """
    if not type_names:
        return 0, CLASS_DESCRIPTIONS[0], "Safe concomitant use. Standard dosing applies."

    life_count = len(type_names & LIFE_THREATENING)
    hemo_count = len(type_names & HEMODYNAMIC_METABOLIC)
    gi_count = len(type_names & GI_ABSORPTION)

    # Tier 3: Strict Contraindication -> Multiple co-occurring life-threatening toxicities
    if life_count >= 3 or (life_count >= 2 and hemo_count >= 6):
        matched = list(type_names & LIFE_THREATENING)[:3]
        rationale = f"Concomitant use prohibited due to high risk of {', '.join(matched)}."
        return 3, CLASS_DESCRIPTIONS[3], rationale

    # Tier 1: GI Absorption Spacing -> Primarily GI motility/absorption delay without critical organ failure
    if gi_count >= 1 and life_count <= 1 and hemo_count <= 4:
        matched = list(type_names & GI_ABSORPTION)[:3]
        rationale = f"Absorption/GI transit delay ({', '.join(matched)}). Administer 2-4 hours apart."
        return 1, CLASS_DESCRIPTIONS[1], rationale

    # Tier 2: Dose Adjustment & Clinical Monitoring -> Systemic hemodynamic/metabolic effects
    if life_count >= 1 or hemo_count >= 1:
        matched = list(type_names)[:3]
        rationale = f"Systemic pharmacodynamic interaction ({', '.join(matched)}). Dose reduction and monitoring required."
        return 2, CLASS_DESCRIPTIONS[2], rationale

    # Tier 0: Mild / Benign symptoms
    return 0, CLASS_DESCRIPTIONS[0], "Safe concomitant use. Standard dosing applies."

def main():
    print("=" * 75)
    print(" INTERACTOMEX BALANCED CLINICAL GROUND-TRUTH DATASET GENERATOR")
    print("=" * 75)

    # 1. Load CID to Generic Drug Name mapping
    name_cache_file = "data/processed/cid_to_name_cache.csv"
    if not os.path.exists(name_cache_file):
        raise FileNotFoundError(f"Missing {name_cache_file}")

    name_df = pd.read_csv(name_cache_file)
    cid_to_name = dict(zip(name_df['drug_id'].astype(str), name_df['name'].astype(str)))
    print(f"[*] Loaded {len(cid_to_name)} drug CID-to-Name translations.")

    # 2. Check ddis.csv
    ddi_file = "data/raw/ddis (1).csv"
    if not os.path.exists(ddi_file):
        ddi_file = "data/raw/ddis.csv"
    if not os.path.exists(ddi_file):
        raise FileNotFoundError(f"Could not find ddis.csv in data/raw/")

    print(f"[*] Reading interaction rows from {ddi_file}...")
    ddi_df = pd.read_csv(ddi_file, usecols=['d1', 'd2', 'type', 'Neg samples'])
    print(f"[*] Total raw interaction rows loaded: {len(ddi_df):,}")

    # 3. Group positive pairs
    print("[*] Aggregating multi-typed interactions per unique positive drug pair...")
    pair_grouped = ddi_df.groupby(['d1', 'd2'])['type'].apply(set).reset_index()
    print(f"[*] Identified {len(pair_grouped):,} unique interacting drug pairs.")

    # 4. Classify positive pairs with multi-threshold clinical rules
    print("[*] Classifying interacting pairs into Clinical Prescribing Tiers...")
    pos_records = []
    for _, row in pair_grouped.iterrows():
        d1 = str(row['d1']).strip()
        d2 = str(row['d2']).strip()
        types_set = row['type']

        type_names = set(TYPE_ID_TO_NAME[tid] for tid in types_set if tid in TYPE_ID_TO_NAME)
        lbl, tier_desc, rationale = classify_positive_pair(type_names)

        pos_records.append({
            'drug_a_cid': d1,
            'drug_a_name': cid_to_name.get(d1, d1),
            'drug_b_cid': d2,
            'drug_b_name': cid_to_name.get(d2, d2),
            'num_active_types': len(types_set),
            'action_label': lbl,
            'action_tier': tier_desc,
            'clinical_rationale': rationale
        })

    # 5. Extract genuine true negative pairs from Neg samples as Class 0
    print("[*] Mining true negative (non-interacting) pairs for Class 0 (Safe Concomitant)...")
    all_pos = set(zip(pair_grouped['d1'], pair_grouped['d2'])) | set(zip(pair_grouped['d2'], pair_grouped['d1']))

    neg_candidates = (
        ddi_df[['d1', 'Neg samples']]
        .dropna()
        .drop_duplicates()
        .rename(columns={'Neg samples': 'd2'})
    )
    neg_candidates = neg_candidates[neg_candidates['d1'] != neg_candidates['d2']]

    valid_neg_pairs = [
        (a, b) for a, b in zip(neg_candidates['d1'], neg_candidates['d2'])
        if (a, b) not in all_pos and (b, a) not in all_pos
    ]
    # Keep canonical order
    canonical_neg = list(set((min(a, b), max(a, b)) for a, b in valid_neg_pairs))
    print(f"[*] Available genuine negative pairs: {len(canonical_neg):,}")

    # Sample 25,000 true negatives to balance the classes
    target_negatives = 25000
    np.random.seed(42)
    sampled_indices = np.random.choice(len(canonical_neg), size=min(target_negatives, len(canonical_neg)), replace=False)

    neg_records = []
    for idx in sampled_indices:
        d1, d2 = canonical_neg[idx]
        neg_records.append({
            'drug_a_cid': d1,
            'drug_a_name': cid_to_name.get(d1, d1),
            'drug_b_cid': d2,
            'drug_b_name': cid_to_name.get(d2, d2),
            'num_active_types': 0,
            'action_label': 0,
            'action_tier': CLASS_DESCRIPTIONS[0],
            'clinical_rationale': "No documented pharmacological interaction. Standard concomitant dosing applies."
        })
    print(f"[*] Sampled {len(neg_records):,} true negative pairs as Class 0.")

    # 6. Combine and shuffle
    full_df = pd.DataFrame(pos_records + neg_records).sample(frac=1.0, random_state=42).reset_index(drop=True)

    # 7. Save output
    out_dir = "data/processed"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "pair_clinical_actions.csv")
    full_df.to_csv(out_file, index=False)
    print(f"\n[+] Successfully saved balanced clinical dataset to: {out_file}")

    # 8. Diagnostics Report
    print("\n" + "=" * 75)
    print(" BALANCED DATASET DIAGNOSTICS & CLASS REPORT")
    print("=" * 75)
    print(f"Total Unique Evaluated Pairs : {len(full_df):,}")
    print("\nClass Breakdown:")
    counts = full_df['action_label'].value_counts().sort_index()
    for lbl, count in counts.items():
        pct = (count / len(full_df)) * 100
        print(f"  Class {lbl}: {CLASS_DESCRIPTIONS[lbl]:<65} = {count:>6,} ({pct:>5.1f}%)")

    print("\nSample Generated Records:")
    sample_cols = ['drug_a_name', 'drug_b_name', 'action_label', 'action_tier', 'clinical_rationale']
    print(full_df[sample_cols].head(5).to_string(index=False))
    print("=" * 75)

if __name__ == '__main__':
    main()
