# InteractomeX: Clinical Prescribing Head Migration Guide
## Transition from Monotherapy `head_se` to Actionable `head_action`

This guide provides the exact cell-by-cell copy-paste code to update your Google Colab notebook (`ddi_gnn_model_v24_fixed (3).ipynb`) and train the **4-Tier Clinical Prescribing Head (`head_action`)**.

---

### Step 1: Upload the Ground-Truth Clinical Dataset to Google Drive

1. On your local machine, locate the preprocessed dataset:
   `InteractomeX - Copy (2)/data/processed/pair_clinical_actions.csv`
2. Upload `pair_clinical_actions.csv` to your project folder in Google Drive (the folder defined as `DRIVE_OUTPUT_DIR` in your Colab notebook).

---

### Step 2: Update Cell 52 (Model Architecture & Training Loop)

Open your notebook in Google Colab, scroll to **Cell 52**, and make the two updates below:

#### 2.1 Update `class PairNetV23`
Find `class PairNetV23` and replace its definition with this:

```python
class PairNetV23(PairNet):
    """
    v24 PairNet with:
    1. Pair Interaction Gate (head_gate)
    2. 40 Interaction Type Mechanisms (head_types)
    3. Actionable Clinical Prescribing & Regimen Head (head_action)
    """
    def __init__(
        self,
        known_mask,
        n_actions=4,           # 4 Prescribing Tiers (0: Safe, 1: Spacing, 2: Dose Adjust, 3: Contraindicated)
        use_bias=False,
        bias_drop=0.2,
        action_hid=128,
        action_dropout=0.2,
        **cfg
    ):
        super().__init__(known_mask, **cfg)
        self.use_bias = use_bias
        self.bias_drop = bias_drop

        hid = self.head_types.in_features  # 256-dim shared pair trunk representation

        # Replaces old monotherapy head_se:
        # Evaluates joint pair representation h = trunk(pair) to predict prescribing action
        self.head_action = nn.Sequential(
            nn.Linear(hid, action_hid),
            nn.ReLU(),
            nn.Dropout(action_dropout),
            nn.Linear(action_hid, n_actions)
        )

        if use_bias:
            self.type_bias = nn.Embedding(N_DRUGS, T)
            self.gate_bias = nn.Embedding(N_DRUGS, 1)
            nn.init.zeros_(self.type_bias.weight)
            nn.init.zeros_(self.gate_bias.weight)

    def forward(self, table, i1, i2):
        r1 = table[i1]
        r2 = table[i2]

        # Strictly symmetric pair trunk: [r1+r2, r1*r2, |r1-r2|]
        h = self.trunk(
            torch.cat([r1 + r2, r1 * r2, (r1 - r2).abs()], dim=1)
        )

        lt = self.head_types(h)
        lg = self.head_gate(h).squeeze(1)
        la = self.head_action(h)  # (B, 4) Clinical Prescribing Logits

        if self.use_bias:
            tb = self.type_bias.weight * self.known_mask
            gb = self.gate_bias.weight * self.known_mask
            if self.training and self.bias_drop > 0:
                keep = (torch.rand(tb.size(0), 1, device=tb.device) > self.bias_drop).float()
                tb = tb * keep
                gb = gb * keep
            lt = lt + tb[i1] + tb[i2]
            lg = lg + (gb[i1] + gb[i2]).squeeze(1)

        return lt, lg, la
```

#### 2.2 Add Clinical Action Training Function & Call
In **Cell 52**, find `def fit_se_probe(...)` and replace it with:

```python
def fit_clinical_action_probe(net, csv_path, epochs=30, batch_size=512, lr=1e-3):
    """
    Trains head_action on pair_clinical_actions.csv using balanced class weights.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Missing clinical actions file at: {csv_path}")

    print(f"[*] Loading clinical ground truth from: {csv_path}")
    df_act = pd.read_csv(csv_path)
    
    # Map CIDs to model node indices
    cid_to_i = {cid: idx for idx, cid in enumerate(drug_ids)}
    v1, v2, y = [], [], []
    for _, row in df_act.iterrows():
        c1, c2, lbl = str(row['drug_a_cid']).strip(), str(row['drug_b_cid']).strip(), int(row['action_label'])
        if c1 in cid_to_i and c2 in cid_to_i:
            v1.append(cid_to_i[c1])
            v2.append(cid_to_i[c2])
            y.append(lbl)

    idx1 = torch.tensor(v1, dtype=torch.long)
    idx2 = torch.tensor(v2, dtype=torch.long)
    labels = torch.tensor(y, dtype=torch.long)
    print(f"[+] Successfully mapped {len(labels):,} pairs to model vocabulary.")

    # 80/20 train/val split
    N = len(labels)
    perm = torch.randperm(N)
    tr_idx, va_idx = perm[:int(0.8 * N)], perm[int(0.8 * N):]

    # Balanced inverse class weights for CrossEntropyLoss
    counts = torch.bincount(labels[tr_idx], minlength=4).float()
    weights = (len(tr_idx) / (4.0 * counts)).to(device)

    net.eval()
    with torch.no_grad():
        table = net.drug_table(False)
        def get_h(i1, i2):
            r1, r2 = table[i1.to(device)], table[i2.to(device)]
            return net.trunk(torch.cat([r1 + r2, r1 * r2, (r1 - r2).abs()], dim=1))

        h_tr = get_h(idx1[tr_idx], idx2[tr_idx])
        y_tr = labels[tr_idx].to(device)
        h_va = get_h(idx1[va_idx], idx2[va_idx])
        y_va = labels[va_idx].to(device)

    crit = nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.AdamW(net.head_action.parameters(), lr=lr, weight_decay=1e-4)

    loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(h_tr, y_tr), batch_size=batch_size, shuffle=True
    )

    best_macro = 0.0
    best_state = None
    for ep in range(1, epochs + 1):
        net.head_action.train()
        for bh, by in loader:
            opt.zero_grad()
            out = net.head_action(bh)
            loss = crit(out, by)
            loss.backward()
            opt.step()

        net.head_action.eval()
        with torch.no_grad():
            preds = net.head_action(h_va).argmax(dim=-1).cpu().numpy()
        macro_f1 = f1_score(y_va.cpu().numpy(), preds, average='macro')
        if macro_f1 > best_macro:
            best_macro = macro_f1
            best_state = {k: v.detach().clone() for k, v in net.head_action.state_dict().items()}

        if ep % 5 == 0 or ep == epochs:
            print(f"  [head_action] Epoch {ep:02d}/{epochs} | Val Macro-F1: {macro_f1*100:.2f}% (Best: {best_macro*100:.2f}%)")

    net.head_action.load_state_dict(best_state)
    return best_macro
```

Then in the execution loop of **Cell 52** (near line 1520), replace the `fit_se_probe(...)` block with:
```python
        # ====================================================
        # FINAL CLINICAL PRESCRIBING ACTION HEAD
        # ====================================================
        clinical_csv = os.path.join(DRIVE_OUTPUT_DIR, "pair_clinical_actions.csv")
        if not os.path.exists(clinical_csv):
            clinical_csv = "pair_clinical_actions.csv"

        fit_clinical_action_probe(net, clinical_csv, epochs=30)
```

---

### Step 3: Update Cell 61 (Save Model Checkpoint)

In **Cell 61**, replace the pickle saving block with:

```python
# Save the best clinical model checkpoint
ss0 = WARM_SPLIT_SEEDS[0]
candD = {k: v for k, v in V23_RESULTS.items() if k[1] == ss0}
V23_BEST_KEY = max(candD, key=lambda k: candD[k]['info']['sel'])
_b = V23_RESULTS[V23_BEST_KEY]

os.makedirs(DRIVE_OUTPUT_DIR, exist_ok=True)
out_pkl = os.path.join(DRIVE_OUTPUT_DIR, 'ddi_v24_best.pkl')

target_action_classes = [
    "Class 0: Safe Concomitant Use (Standard Regimen)",
    "Class 1: Time-Separated Administration (Spacing: 2-4 Hours)",
    "Class 2: Dose Adjustment & Clinical Monitoring",
    "Class 3: Strict Contraindication (Absolute Avoidance)"
]

with open(out_pkl, 'wb') as fh:
    pickle.dump({
        'state_dict': _b['state'],
        'config': _b['cfg'],
        'use_bias': _b['use_bias'],
        'variant': V23_BEST_KEY[0],
        'drug_ids': drug_ids,
        'known_mask': _b['info']['known'],
        'gate_threshold': _b['f1']['gate threshold (val-tuned)'],
        'type_thresholds': _b['f1']['_type_thresholds'],
        'gate_temperature': _b['cal']['T'],
        'top_types': top_types,
        'type_names': type_names,
        'clinical_action_classes': target_action_classes,
        'n_actions': 4,
        'desc_names': DESC_NAMES,
        'desc_mean': _b['info']['desc_mean'],
        'desc_std': _b['info']['desc_std'],
    }, fh)

print('\n[+] Saved Clinical Prescribing Model ->', out_pkl)
```

---

### Step 4: Update Cell 63 (Inference Test Call)

In **Cell 63**, update `predict_full_v23` to return clinical advice:

```python
def predict_full_v24(drug_a, drug_b, top_n=5):
    i1, i2 = d2i[drug_a], d2i[drug_b]
    with torch.no_grad():
        table = _vnet.drug_table(False)
        lt, lg, la = _vnet(table, torch.tensor([i1], device=device), torch.tensor([i2], device=device))
        action_probs = torch.softmax(la, dim=-1).squeeze(0).cpu().numpy()
        pred_action_idx = int(np.argmax(action_probs))
    
    action_names = [
        "Safe Concomitant Use (No Action Required)",
        "Time-Separated Administration (Spacing 2-4h)",
        "Dose Adjustment & Clinical Monitoring Required",
        "Strict Contraindication (Absolute Avoidance)"
    ]

    return {
        "interacts": bool(torch.sigmoid(lg).item() >= _vf1['gate threshold (val-tuned)']),
        "clinical_action": {
            "tier": pred_action_idx,
            "label": action_names[pred_action_idx],
            "confidence": float(action_probs[pred_action_idx])
        }
    }
```

---

### Step 5: Final Step After Running Colab
1. Once the notebook finishes running, download **`ddi_v24_best.pkl`** from your Google Drive.
2. Place it in your local repository under `checkpoints/` (or update your `src/inference.py` to point to it).
3. The local server and web UI will now display the neural network's predicted prescribing action!
