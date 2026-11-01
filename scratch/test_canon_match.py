import json
import pandas as pd
from rdkit import Chem

with open('data/processed/smiles_cache.json') as f:
    s_cache = json.load(f)

def to_canon(s):
    try:
        if isinstance(s, (list, tuple)):
            s = s[0]
        s_clean = str(s).strip().strip('"').strip("'")
        m = Chem.MolFromSmiles(s_clean)
        return Chem.MolToSmiles(m) if m else None
    except:
        return None

local_canon = {}
for cid, s in s_cache.items():
    if cid.startswith('CID'):
        c = to_canon(s)
        if c:
            local_canon[c] = cid

print(f"Total local canonical molecules: {len(local_canon)}")

df = pd.read_csv('data/raw/drugbank.tab', sep='\t')
unique_db_smi = set(df['X1'].dropna().astype(str).str.strip('"')) | set(df['X2'].dropna().astype(str).str.strip('"'))
print(f"Total unique DrugBank SMILES: {len(unique_db_smi)}")

db_canon = {}
for s in unique_db_smi:
    c = to_canon(s)
    if c:
        db_canon[c] = s

matches = set(local_canon.keys()) & set(db_canon.keys())
print(f"Canonical chemical matches with DrugBank: {len(matches)} / {len(local_canon)} ({(len(matches)/len(local_canon))*100:.1f}%)")
