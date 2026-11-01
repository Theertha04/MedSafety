import sys
sys.path.insert(0, '.')
from src.inference import get_engine, cid_to_smiles

eng = get_engine()
cid_a = eng.find_cid_by_name('aspirin')
cid_b = eng.find_cid_by_name('warfarin')
smiles_a = cid_to_smiles(cid_a)
smiles_b = cid_to_smiles(cid_b)

res = eng.predict(smiles_a, smiles_b, cid_a, cid_b)
print('Interacting Pair (Aspirin + Warfarin):')
print('Interacts:', res['interacts'], 'Gate prob:', res['gate_prob'])
print('Active types sample:')
for t in res['active_interaction_types'][:4]:
    print(f"  • {t['name']} [{t['severity_tier']}] ({t['prob']*100:.0f}%): {t['clinical_explanation']}")

cid_s = eng.find_cid_by_name('sevoflurane')
cid_e = eng.find_cid_by_name('ertapenem')
smiles_s = cid_to_smiles(cid_s)
smiles_e = cid_to_smiles(cid_e)

res2 = eng.predict(smiles_s, smiles_e, cid_s, cid_e)
print('\nNon-interacting Pair (Sevoflurane + Ertapenem):')
print('Interacts:', res2['interacts'], 'Gate prob:', res2['gate_prob'])
print('Drug A top baseline:', [(s['name'], f"{s['prob']*100:.0f}%") for s in res2['drug_a_side_effects'][:3]])
print('Drug B top baseline:', [(s['name'], f"{s['prob']*100:.0f}%") for s in res2['drug_b_side_effects'][:3]])
