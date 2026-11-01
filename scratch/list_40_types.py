import pickle

with open('models/ddi_v23_best.pkl', 'rb') as f:
    ckpt = pickle.load(f)

top_types = ckpt['top_types']
type_names = ckpt['type_names']
for i, t in enumerate(top_types):
    print(f"{i+1}. id={t}: {type_names.get(t, 'Unknown')}")
