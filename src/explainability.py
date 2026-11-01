"""
InteractomeX – Explainability Module (SHAP + Grad-CAM).

Provides:
  1. GNN Grad-CAM: Atom-level importance via gradient-weighted activation
     maps on the final GATv2Conv layer. Generates colored 2D SVGs.
  2. Descriptor SHAP: Gradient × input attribution for the 12 RDKit
     physicochemical descriptors fed to the descriptor MLP branch.
  3. Fingerprint Attribution: Gradient-based bit importance for the
     2048-bit Morgan fingerprint branch, reporting top-K contributing bits.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import torch
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D

from .featurizer import _DESC_NAMES


# ---------------------------------------------------------------------------
# 1.  GNN Grad-CAM  –  atom-level importance
# ---------------------------------------------------------------------------

def compute_gradcam(
    model,
    graphA, fpA, descA,
    graphB, fpB, descB,
    target_head: str = "gate",
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Grad-CAM atom importance for both drugs simultaneously.

    Hooks into the last GATv2Conv layer (encoder.conv3) of each drug's
    encoding pass. The importance of atom i is computed using gradient-weighted
    activations:
        α_k = (1/N) Σ_i (∂y / ∂A_ik)
        L_i = ReLU( Σ_k α_k · A_ik )

    Returns
    -------
    importance_a, importance_b : ndarray of shape (num_atoms,)
        Per-atom importance scores, min-max normalised to [0, 1].
    """
    model.eval()

    gA = graphA.clone()
    gB = graphB.clone()
    fA = fpA.clone().detach()
    dA = descA.clone().detach()
    fB = fpB.clone().detach()
    dB = descB.clone().detach()

    if not hasattr(gA, "batch") or gA.batch is None:
        gA.batch = torch.zeros(gA.num_nodes, dtype=torch.long)
    if not hasattr(gB, "batch") or gB.batch is None:
        gB.batch = torch.zeros(gB.num_nodes, dtype=torch.long)

    acts = {}
    grads = {}

    def fwd_hook(module, inp, output):
        idx = len(acts)
        acts[idx] = output

        def bwd_hook(grad):
            grads[idx] = grad

        output.register_hook(bwd_hook)

    handle = model.encoder.conv3.register_forward_hook(fwd_hook)

    try:
        gate_logit, _, _ = model(gA, fA, dA, gB, fB, dB)
        model.zero_grad()
        gate_logit.backward()

        def _calc_cam(act_tensor, grad_tensor, num_nodes):
            if act_tensor is None or grad_tensor is None:
                return np.zeros(num_nodes)
            alpha = grad_tensor.mean(dim=0, keepdim=True)
            cam = (act_tensor * alpha).sum(dim=-1)
            cam_relu = torch.relu(cam)
            if cam_relu.max() > 0:
                imp = cam_relu.detach().cpu().numpy()
            else:
                imp = torch.abs(cam).detach().cpu().numpy()

            rng = imp.max() - imp.min()
            if rng > 1e-9:
                return (imp - imp.min()) / rng
            return np.full_like(imp, 0.5)

        imp_a = _calc_cam(acts.get(0), grads.get(0), gA.num_nodes)
        imp_b = _calc_cam(acts.get(1), grads.get(1), gB.num_nodes)

        return imp_a, imp_b
    finally:
        handle.remove()


def importance_to_svg(
    smiles: str,
    atom_importance: np.ndarray,
    width: int = 520,
    height: int = 320,
) -> Optional[str]:
    """
    Render a 2D molecule SVG with atoms colored by Grad-CAM importance.

    Uses a blue → yellow → red heatmap where:
      - Blue  = low importance (cool)
      - Yellow = medium importance
      - Red   = high importance (hot)

    Parameters
    ----------
    smiles : str
    atom_importance : ndarray of shape (num_atoms,), values in [0, 1]
    width, height : SVG dimensions

    Returns
    -------
    svg_string or None
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        # Generate 2D coordinates
        AllChem.Compute2DCoords(mol)

        num_atoms = mol.GetNumAtoms()
        if len(atom_importance) != num_atoms:
            # Pad or truncate
            padded = np.zeros(num_atoms)
            n = min(len(atom_importance), num_atoms)
            padded[:n] = atom_importance[:n]
            atom_importance = padded

        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        opts = drawer.drawOptions()
        opts.clearBackground = False
        opts.bondLineWidth = 2.2
        opts.padding = 0.12

        # Build atom color map: importance → heatmap color
        atom_colors = {}
        atom_radii = {}
        for i in range(num_atoms):
            imp = float(atom_importance[i])

            # Blue (0.6, 0.75, 1.0) → Yellow (1.0, 0.95, 0.4) → Red (0.95, 0.25, 0.2)
            if imp < 0.5:
                t = imp * 2  # 0 → 1
                r = 0.6 + t * 0.4
                g = 0.75 + t * 0.2
                b = 1.0 - t * 0.6
            else:
                t = (imp - 0.5) * 2  # 0 → 1
                r = 1.0 - t * 0.05
                g = 0.95 - t * 0.7
                b = 0.4 - t * 0.2

            atom_colors[i] = (r, g, b, 0.65)
            atom_radii[i] = 0.34 + imp * 0.24  # Well-proportioned highlight radius

        rdMolDraw2D.PrepareAndDrawMolecule(
            drawer, mol,
            highlightAtoms=list(range(num_atoms)),
            highlightAtomColors=atom_colors,
            highlightAtomRadii=atom_radii,
            highlightBonds=[],
        )
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception as e:
        print(f"[XAI] importance_to_svg error: {e}")
        return None


# ---------------------------------------------------------------------------
# 2.  Descriptor SHAP  –  True KernelSHAP (Fast Vectorized Batch Evaluation)
# ---------------------------------------------------------------------------

def compute_descriptor_shap(
    model,
    graphA, fpA, descA,
    graphB, fpB, descB,
) -> tuple[list[dict], list[dict]]:
    """
    Compute game-theoretic Shapley values (KernelSHAP) for the 12 RDKit physicochemical descriptors.
    Uses vectorized batch evaluation of the descriptor MLP trunk for sub-100ms real-time inference.
    Falls back gracefully to Gradient x Input if needed.

    Returns
    -------
    shap_a, shap_b : list of dicts with keys {name, value, attribution, abs_attribution}
    """
    model.eval()

    try:
        import shap
        import warnings
        warnings.filterwarnings("ignore")

        # Precompute fixed GNN and FP embeddings (they do not vary with descriptors)
        with torch.no_grad():
            gnn_A = model.encoder(graphA.x, graphA.edge_index, graphA.edge_attr, graphA.batch) # (1, 128)
            fp_A  = model.fp_mlp(fpA)                                                           # (1, 128)
            eB    = model._encode_drug(graphB, fpB, descB)                                     # (1, 256)

            gnn_B = model.encoder(graphB.x, graphB.edge_index, graphB.edge_attr, graphB.batch) # (1, 128)
            fp_B  = model.fp_mlp(fpB)                                                           # (1, 128)
            eA    = model._encode_drug(graphA, fpA, descA)                                     # (1, 256)

        def predict_batch_a(X_np):
            with torch.no_grad():
                M = X_np.shape[0]
                desc_tensor = torch.tensor(X_np, dtype=torch.float32)
                desc_emb = model.desc_mlp(desc_tensor)
                eA_batch = model.proj(torch.cat([gnn_A.expand(M, -1), fp_A.expand(M, -1), desc_emb], dim=-1))
                eB_tiled = eB.expand(M, -1)
                pair = torch.cat([eA_batch + eB_tiled, eA_batch * eB_tiled, torch.abs(eA_batch - eB_tiled)], dim=-1)
                h = model.trunk(pair)
                return model.head_gate(h).squeeze(-1).cpu().numpy()

        def predict_batch_b(X_np):
            with torch.no_grad():
                M = X_np.shape[0]
                desc_tensor = torch.tensor(X_np, dtype=torch.float32)
                desc_emb = model.desc_mlp(desc_tensor)
                eB_batch = model.proj(torch.cat([gnn_B.expand(M, -1), fp_B.expand(M, -1), desc_emb], dim=-1))
                eA_tiled = eA.expand(M, -1)
                pair = torch.cat([eA_tiled + eB_batch, eA_tiled * eB_batch, torch.abs(eA_tiled - eB_batch)], dim=-1)
                h = model.trunk(pair)
                return model.head_gate(h).squeeze(-1).cpu().numpy()

        # Normalized zero baseline (represents training dataset mean)
        background = np.zeros((8, 12))
        explainer_a = shap.KernelExplainer(predict_batch_a, background)
        explainer_b = shap.KernelExplainer(predict_batch_b, background)

        sv_a = explainer_a.shap_values(descA.numpy(), nsamples=64, l1_reg="num_features(10)")
        sv_b = explainer_b.shap_values(descB.numpy(), nsamples=64, l1_reg="num_features(10)")

        raw_a = sv_a[0] if isinstance(sv_a, list) else sv_a.squeeze()
        raw_b = sv_b[0] if isinstance(sv_b, list) else sv_b.squeeze()

        vals_a = descA.detach().squeeze(0).numpy()
        vals_b = descB.detach().squeeze(0).numpy()

        shap_a = []
        shap_b = []
        for i, name in enumerate(_DESC_NAMES):
            shap_a.append({
                "name": name,
                "value": round(float(vals_a[i]), 4),
                "attribution": round(float(raw_a[i]), 6),
                "abs_attribution": round(abs(float(raw_a[i])), 6),
            })
            shap_b.append({
                "name": name,
                "value": round(float(vals_b[i]), 4),
                "attribution": round(float(raw_b[i]), 6),
                "abs_attribution": round(abs(float(raw_b[i])), 6),
            })

        shap_a.sort(key=lambda x: x["abs_attribution"], reverse=True)
        shap_b.sort(key=lambda x: x["abs_attribution"], reverse=True)
        return shap_a, shap_b

    except Exception as exc:
        print(f"[XAI] KernelSHAP fallback to Gradient x Input: {exc}")
        # Fallback to gradient x input if SHAP library fails
        def _desc_attributions(desc_tensor, graph, fp, desc, graph_other, fp_other, desc_other, is_drug_a=True):
            d = desc_tensor.clone().detach().requires_grad_(True)
            if is_drug_a:
                gate_logit, _, _ = model(graph, fp, d, graph_other, fp_other, desc_other)
            else:
                gate_logit, _, _ = model(graph_other, fp_other, desc_other, graph, fp, d)
            model.zero_grad()
            gate_logit.backward(retain_graph=False)
            grad = d.grad.detach().squeeze(0).cpu().numpy()
            vals = desc_tensor.detach().squeeze(0).cpu().numpy()
            attributions = grad * vals
            results = []
            for i, name in enumerate(_DESC_NAMES):
                results.append({
                    "name": name,
                    "value": round(float(vals[i]), 4),
                    "attribution": round(float(attributions[i]), 6),
                    "abs_attribution": round(abs(float(attributions[i])), 6),
                })
            results.sort(key=lambda x: x["abs_attribution"], reverse=True)
            return results

        gA = graphA.clone()
        gA.batch = torch.zeros(gA.num_nodes, dtype=torch.long)
        gB = graphB.clone()
        gB.batch = torch.zeros(gB.num_nodes, dtype=torch.long)
        gA2 = graphA.clone()
        gA2.batch = torch.zeros(gA2.num_nodes, dtype=torch.long)
        gB2 = graphB.clone()
        gB2.batch = torch.zeros(gB2.num_nodes, dtype=torch.long)

        shap_a = _desc_attributions(descA, gA, fpA.clone(), descA, gB, fpB.clone(), descB, is_drug_a=True)
        shap_b = _desc_attributions(descB, gA2, fpA.clone(), descA.clone(), gB2, fpB.clone(), descB, is_drug_a=False)
        return shap_a, shap_b


# ---------------------------------------------------------------------------
# 3.  Fingerprint Attribution  –  top-K gradient-based bit importance
# ---------------------------------------------------------------------------

def compute_fingerprint_attribution(
    model,
    graphA, fpA, descA,
    graphB, fpB, descB,
    top_k: int = 20,
) -> tuple[list[dict], list[dict]]:
    """
    Compute gradient-based attribution for Morgan fingerprint bits.

    For each drug's fingerprint, computes ∂(gate_logit)/∂(fp_bit) and
    returns the top-K bits by |gradient|, along with their on/off status.

    Returns
    -------
    top_bits_a, top_bits_b : list of dicts with {bit_index, gradient, is_on, direction}
    """
    model.eval()

    def _fp_attributions(fp_tensor, graph, fp, desc, graph_other, fp_other, desc_other, is_drug_a=True):
        f = fp_tensor.clone().detach().requires_grad_(True)

        gA = graph.clone()
        gA.batch = torch.zeros(gA.num_nodes, dtype=torch.long)
        gB = graph_other.clone()
        gB.batch = torch.zeros(gB.num_nodes, dtype=torch.long)

        if is_drug_a:
            gate_logit, _, _ = model(gA, f, desc, gB, fp_other, desc_other)
        else:
            gate_logit, _, _ = model(gA, fp, desc, gB, f, desc_other)

        model.zero_grad()
        gate_logit.backward(retain_graph=False)

        grad = f.grad.detach().squeeze(0).cpu().numpy()   # (2048,)
        bits = fp_tensor.detach().squeeze(0).cpu().numpy()  # (2048,)

        # Get top-K by |gradient|
        abs_grad = np.abs(grad)
        top_indices = np.argsort(abs_grad)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            results.append({
                "bit_index": int(idx),
                "gradient": round(float(grad[idx]), 6),
                "abs_gradient": round(float(abs_grad[idx]), 6),
                "is_on": bool(bits[idx] > 0.5),
                "direction": "promotes" if grad[idx] > 0 else "suppresses",
            })

        return results

    top_a = _fp_attributions(
        fpA, graphA, fpA, descA, graphB, fpB, descB,
        is_drug_a=True
    )
    top_b = _fp_attributions(
        fpB, graphA, fpA, descA, graphB, fpB, descB,
        is_drug_a=False
    )

    return top_a, top_b


# ---------------------------------------------------------------------------
# 4.  Master XAI function  –  called from inference.py
# ---------------------------------------------------------------------------

def compute_full_explainability(
    model,
    graphA, fpA, descA,
    graphB, fpB, descB,
    smiles_a: str,
    smiles_b: str,
) -> dict:
    """
    Run all explainability analyses and return a structured dict.

    Returns
    -------
    dict with keys:
        gradcam: {drug_a_svg, drug_b_svg, drug_a_scores, drug_b_scores}
        descriptor_shap: {drug_a, drug_b}
        fingerprint_attribution: {drug_a, drug_b}
    """
    result = {
        "gradcam": None,
        "descriptor_shap": None,
        "fingerprint_attribution": None,
    }

    try:
        imp_a, imp_b = compute_gradcam(
            model, graphA, fpA, descA, graphB, fpB, descB
        )
        svg_a = importance_to_svg(smiles_a, imp_a)
        svg_b = importance_to_svg(smiles_b, imp_b)

        result["gradcam"] = {
            "drug_a_svg": svg_a,
            "drug_b_svg": svg_b,
            "drug_a_scores": [round(float(x), 4) for x in imp_a],
            "drug_b_scores": [round(float(x), 4) for x in imp_b],
        }
    except Exception as e:
        print(f"[XAI] Grad-CAM failed: {e}")

    try:
        shap_a, shap_b = compute_descriptor_shap(
            model, graphA, fpA, descA, graphB, fpB, descB
        )
        result["descriptor_shap"] = {
            "drug_a": shap_a,
            "drug_b": shap_b,
        }
    except Exception as e:
        print(f"[XAI] Descriptor SHAP failed: {e}")

    try:
        fp_a, fp_b = compute_fingerprint_attribution(
            model, graphA, fpA, descA, graphB, fpB, descB
        )
        result["fingerprint_attribution"] = {
            "drug_a": fp_a,
            "drug_b": fp_b,
        }
    except Exception as e:
        print(f"[XAI] Fingerprint attribution failed: {e}")

    return result
