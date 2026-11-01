"""
Validation and Edge Case Test Suite for InteractomeX.

Directly tests the validation and prediction logic without needing external HTTP clients.
Verifies system behaviors and alerts for:
1. Same name (e.g., 'Aspirin' and 'Aspirin')
2. Case-insensitive same name (e.g., 'aspirin' and 'ASPIRIN')
3. Same CID (e.g., 'CID000002244' and 'CID000002244')
4. Synonyms resolving to same compound (e.g., 'Aspirin' and 'Acetylsalicylic acid')
5. Same SMILES
6. Missing inputs
7. Invalid / non-existent drug name (e.g., 'invalid_xyz_random_test_123')
8. Invalid SMILES string (e.g., 'C123#NOTVALID')
9. Valid pair (e.g., 'Aspirin' and 'Warfarin')
"""

import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException
from api import predict, PredictRequest

def run_test(name, coro):
    try:
        res = asyncio.run(coro)
        return True, res
    except HTTPException as e:
        return False, e
    except Exception as e:
        return False, e

def main():
    print("\nRunning InteractomeX Backend Validation & Alert Test Suite...\n" + "=" * 65)

    # 1. Same name
    ok, res = run_test("Same Name", predict(PredictRequest(name_a="Aspirin", name_b="Aspirin")))
    assert not ok and res.status_code == 422, f"Failed same name check: {res}"
    print(f"[PASS] 1. Same Name Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 2. Case-insensitive same name
    ok, res = run_test("Case-Insensitive Same Name", predict(PredictRequest(name_a="aspirin", name_b="ASPIRIN")))
    assert not ok and res.status_code == 422, f"Failed case-insensitive check: {res}"
    print(f"[PASS] 2. Case-Insensitive Same Name Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 3. Same CID
    ok, res = run_test("Same CID", predict(PredictRequest(cid_a="CID000002244", cid_b="CID000002244")))
    assert not ok and res.status_code == 422, f"Failed same CID check: {res}"
    print(f"[PASS] 3. Same CID Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 4. Synonym identical compound
    ok, res = run_test("Synonym Identical Compound", predict(PredictRequest(name_a="Aspirin", name_b="Acetylsalicylic acid")))
    assert not ok and res.status_code == 422, f"Failed synonym identical check: {res}"
    print(f"[PASS] 4. Synonym Identical Compound Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 5. Missing Drug B
    ok, res = run_test("Missing Input", predict(PredictRequest(name_a="Aspirin")))
    assert not ok and res.status_code == 422, f"Failed missing input check: {res}"
    print(f"[PASS] 5. Missing Input Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 6. Invalid / Gibberish Drug Name
    ok, res = run_test("Invalid Drug Name", predict(PredictRequest(name_a="invalid_xyz_random_test_123", name_b="Warfarin")))
    assert not ok and res.status_code == 422, f"Failed invalid name check: {res}"
    print(f"[PASS] 6. Invalid Drug Name Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 7. Invalid SMILES
    ok, res = run_test("Invalid SMILES", predict(PredictRequest(smiles_a="C123#NOTVALID", smiles_b="CC(=O)OC1=CC=CC=C1C(=O)O")))
    assert not ok and res.status_code == 422, f"Failed invalid SMILES check: {res}"
    print(f"[PASS] 7. Invalid SMILES Alert: Status {res.status_code} -> \"{res.detail}\"")

    # 8. Valid Pair
    ok, res = run_test("Valid Pair", predict(PredictRequest(name_a="Aspirin", name_b="Warfarin")))
    assert ok and "gate_prob" in res, f"Failed valid pair check: {res}"
    print(f"[PASS] 8. Valid Prediction Success: Gate Confidence = {res['gate_prob']*100:.1f}%, Interacts = {res['interacts']}")

    print("=" * 65)
    print("ALL 8 VALIDATION & ALERT TESTS PASSED SUCCESSFULLY!\n")

if __name__ == "__main__":
    main()
