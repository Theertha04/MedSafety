import json
import pandas as pd
from rdkit import Chem

with open('data/processed/smiles_cache.json') as f:
    s_cache = json.load(f)

def to_key(s):
    try:
        m = Chem.MolFromSmiles(str(s).strip().strip('"'))
        return Chem.MolToInchiKey(m) if m else None
    except:
        return None

local_keys = {}
for cid, s in s_cache.items():
    k = to_key(s)
    if k:
        local_keys[k] = cid

print(f"Total local chemical keys: {len(local_keys)}")

db_df = pd.read_csv('data/raw/drugbank.tab', sep='\t')
db_keys = {}
for _, r in db_df.iterrows():
    s1 = to_key(r['X1'])
    s2 = to_key(r['X2'])
    id1 = str(r['ID1']).strip('"')
    id2 = str(r['ID2']).strip('"')
    if s1 and s1 not in db_keys:
        db_keys[s1] = id1
    if s2 and s2 not in db_keys:
        db_keys[s2] = id2

matches = set(local_keys.keys()) & set(db_keys.keys())
print(f"Chemical InChIKey matches with DrugBank: {len(matches)} / {len(local_keys)}")
