"""
Diagnostic script to inspect model predictions, scores, and calibration.
"""
import torch
import numpy as np
from src.inference import get_engine

def run_diagnostics():
    engine = get_engine()
    print("--- Model Information ---")
    print(f"Gate threshold: {engine.gate_threshold}")
    print(f"Gate temp (Platt scaling / temperature): {engine.gate_temp}")
    print(f"Known drugs in checkpoint: {len(engine.drug_ids)}")
    
    # Check top types and thresholds
    print(f"Top types count: {len(engine.top_types)}")
    print(f"Type thresholds sample: {engine.type_thresholds[:5]}")
    
    # Test pairs
    test_drugs = [
        # Common drug pairs
        ("Aspirin", "Warfarin"),      # known major interaction
        ("Aspirin", "Ibuprofen"),     # known interaction
        ("Metformin", "Aspirin"),     # typically minor/moderate
        ("Metformin", "Paracetamol"), # minimal direct interaction
        ("Paracetamol", "Caffeine"),  # often combined safely in OTC pills
        ("Amoxicillin", "Paracetamol"), # very safe/common combination
    ]
    
    print("\n--- Test Predictions ---")
    for d1, d2 in test_drugs:
        try:
            cid1 = engine.find_cid_by_name(d1)
            cid2 = engine.find_cid_by_name(d2)
            from src.inference import name_to_smiles, cid_to_smiles
            sm1, c1 = (cid_to_smiles(cid1), cid1) if cid1 else name_to_smiles(d1)
            sm2, c2 = (cid_to_smiles(cid2), cid2) if cid2 else name_to_smiles(d2)
            
            if not sm1 or not sm2:
                print(f"Could not get smiles for {d1} or {d2}")
                continue
                
            graphA, fpA, descA = engine.featurize(sm1)
            graphB, fpB, descB = engine.featurize(sm2)
            
            with torch.no_grad():
                gate_logit, type_logits, se_logits = engine.model(
                    graphA, fpA, descA,
                    graphB, fpB, descB,
                )
            
            raw_logit = gate_logit.item()
            raw_sigmoid = torch.sigmoid(gate_logit).item()
            scaled_prob = torch.sigmoid(gate_logit / engine.gate_temp).item()
            
            # Check symmetry: what if we swap A and B?
            gate_logit_rev, _, _ = engine.model(
                graphB, fpB, descB,
                graphA, fpA, descA,
            )
            raw_logit_rev = gate_logit_rev.item()
            
            print(f"\nPair: {d1} + {d2}")
            print(f"  CID: {c1} + {c2}")
            print(f"  Raw logit (A, B): {raw_logit:.4f} | (B, A): {raw_logit_rev:.4f}")
            print(f"  Raw Sigmoid: {raw_sigmoid:.4f}")
            print(f"  Temp-scaled prob (temp={engine.gate_temp:.4f}): {scaled_prob:.4f}")
            print(f"  Gate threshold: {engine.gate_threshold:.4f}")
            print(f"  Interacts verdict: {scaled_prob >= engine.gate_threshold}")
            
            # Check types
            type_probs = torch.sigmoid(type_logits).squeeze(0).numpy()
            active_types = [
                (engine.type_names.get(tid, str(tid)), float(type_probs[i]), engine.type_thresholds[i])
                for i, tid in enumerate(engine.top_types)
                if float(type_probs[i]) >= engine.type_thresholds[i]
            ]
            print(f"  Active types count: {len(active_types)} / 40")
            if active_types:
                active_types.sort(key=lambda x: x[1], reverse=True)
                print(f"  Top type: {active_types[0][0]} (prob: {active_types[0][1]:.4f}, thresh: {active_types[0][2]:.4f})")
        except Exception as e:
            print(f"Error testing {d1} + {d2}: {e}")

if __name__ == "__main__":
    run_diagnostics()
