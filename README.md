# InteractomeX ⚗️

InteractomeX is a multi-modal Graph Neural Network (GNN) platform for predicting **Drug–Drug Interactions (DDIs)**, clinical interaction risk types, and adverse side effects directly from molecular structures.

---

## Key Features

1. **Independent Model Inference**
   - Predictions are computed purely from chemical structure representations (Graph Attention Network `GATv2Conv`, Morgan fingerprints, and RDKit molecular descriptors).
   - Inference does **not** depend on `pair_df.csv`. Unseen drug pairs can be predicted seamlessly.

2. **Explainability & Molecular Visualization**
   - **2D Structure Diagrams:** Real-time chemical structure SVG rendering using RDKit with transparent dark-mode styling.
   - **Physicochemical Feature Breakdown:** Direct comparison of 12 physicochemical descriptors (MolWt, LogP, TPSA, H-Bond donors/acceptors, ring systems) and pair difference vectors ($|A - B|$).
   - **Attribution Transparency:** Exposes explicit architectural representations, directional symmetry variance ($A \to B$ vs $B \to A$), and mathematical transformations rather than synthetic atom heatmaps.

3. **Calibrated Score Decomposition**
   - Displays the **Raw Logit**, **Raw Sigmoid**, **Platt Calibrated Probability** ($T = 0.9664$), and **Decision Threshold** ($\tau = 0.4800$) separately.
   - Guarded against false 100% certainty displays with contextual certainty disclosures.

4. **Multi-Modal Input Options**
   - **Drug Name:** Search across 645 curated drugs with instant autocomplete and PubChem lookup.
   - **PubChem CID:** Direct identifier resolution (e.g., `CID000002244`).
   - **SMILES String:** Predict interactions for custom or novel chemical structures.

5. **Multi-Task Predictions**
   - **Gate Interaction Probability:** Calibrated binary classification of whether two drugs interact.
   - **Active Clinical Types:** Multi-label classification across 40 clinical interaction mechanisms with decision margin indicators.
   - **Ranked Adverse Side Effects:** Probability ranking across 50 target side effects.
   - **Dataset Membership Verification:** Fast, pre-indexed verification against confirmed training interactions.

---

## Project Structure

```text
InteractomeX/
├── api.py                    # FastAPI server & route handlers
├── models/
│   └── ddi_v23_best.pkl      # Trained model weights & normalization stats
├── src/
│   ├── featurizer.py         # SMILES to GNN graph, Morgan FP & descriptors
│   ├── model.py              # DDIModel & DrugEncoder (GATv2Conv architecture)
│   └── inference.py          # InferenceEngine, chemical drawer & PubChem resolver
├── data/
│   ├── raw/
│   │   └── ddis (1).csv      # Ground-truth DDI training interactions
│   └── processed/
│       ├── pair_set.pkl      # Fast O(1) indexed dataset membership cache
│       └── cid_to_name_cache.csv # CID-to-drug-name dictionary
└── frontend/
    ├── index.html            # Tabbed UI (Overview, Explainability, Model Specs)
    ├── style.css             # Scientific dark design system with purple accents
    └── app.js                # Dynamic rendering, metrics breakdown, SVG visualizer
```

---

## How to Run

### Start the Server

```bash
python api.py
```

Or using uvicorn:

```bash
uvicorn api:app --reload --port 8000
```

Open your browser at:
```
http://127.0.0.1:8000
```
