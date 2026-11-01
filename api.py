"""
InteractomeX – FastAPI backend.

Serves the DDI prediction model and static frontend.

Endpoints
---------
GET  /                       → frontend HTML
GET  /api/drugs              → list all 645 known drug CIDs + names
GET  /api/drug/{cid}/smiles  → fetch SMILES for a drug CID from PubChem
POST /api/predict            → run DDI prediction for two drugs

Run with:
    python -m uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
import requests

# Allow `from src.xxx import ...` when run from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import warnings
from contextlib import asynccontextmanager

warnings.filterwarnings("ignore", category=FutureWarning, module="torch.jit")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from src.inference import (
    InferenceEngine,
    cid_to_smiles,
    name_to_smiles,
    get_engine,
    is_same_compound,
)

# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()   # load weights once into memory
    yield

app = FastAPI(
    title="InteractomeX API",
    description="GNN-based Drug–Drug Interaction prediction",
    version="2.3",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND = Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    """Two drugs specified as SMILES strings and/or CIDs."""
    smiles_a: Optional[str] = None
    smiles_b: Optional[str] = None
    cid_a: Optional[str] = None
    cid_b: Optional[str] = None
    name_a: Optional[str] = None
    name_b: Optional[str] = None
    check_dataset: bool = True

    @field_validator("smiles_a", "smiles_b", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        return v if v and v.strip() else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(_FRONTEND / "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">⚗️</text></svg>"""
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/drugs")
async def list_drugs():
    """Return all 645 drug CIDs known to the model, with display names."""
    engine = get_engine()
    return {
        "count": len(engine.drug_ids),
        "drugs": [
            {"cid": str(cid), "name": str(engine.drug_name(cid))}
            for cid in engine.drug_ids
            if cid and str(cid).strip().lower() != "nan"
        ],
    }


COMMON_BRAND_ALIASES = {
    "dolo": "CID000001983",
    "dolo 650": "CID000001983",
    "dolo-650": "CID000001983",
    "dolo650": "CID000001983",
    "calpol": "CID000001983",
    "calpol 500": "CID000001983",
    "calpol 650": "CID000001983",
    "crocin": "CID000001983",
    "crocin 650": "CID000001983",
    "panadol": "CID000001983",
    "tylenol": "CID000001983",
    "paracetamol": "CID000001983",
    "acetaminophen": "CID000001983",
    "disprin": "CID000002244",
    "ecosprin": "CID000002244",
    "aspirin": "CID000002244",
    "advil": "CID000003672",
    "motrin": "CID000003672",
    "brufen": "CID000003672",
    "ibuprofen": "CID000003672",
    "glycomet": "CID000004091",
    "metformin": "CID000004091",
    "coumadin": "CID000005467",
    "warfarin": "CID000005467",
    "duragesic": "CID000003345",
    "fentanyl": "CID000003345",
}


@app.get("/api/autocomplete")
def autocomplete(q: str):
    """
    Fast autocomplete:
    1. Checks clinical brand aliases.
    2. Checks internal 645 curated drug database.
    3. If query >= 3 chars and local matches < 4, queries PubChem with short timeout.
    """
    if not q or not q.strip():
        return {"results": []}

    clean_q = q.strip().lower()
    engine = get_engine()
    results = []
    seen = set()

    # 0. Check clinical brand aliases
    for alias, alias_cid in COMMON_BRAND_ALIASES.items():
        if alias.startswith(clean_q) or (len(clean_q) >= 3 and clean_q in alias):
            alias_title = alias.title()
            canon_name = engine.drug_name(alias_cid)
            disp_name = f"{alias_title} ({canon_name})" if canon_name and canon_name.lower() != alias else alias_title
            if alias not in seen:
                results.append({"name": disp_name, "cid": alias_cid, "source": "known"})
                seen.add(alias)

    # 1. Local curated cohort matching
    prefix_matches = []
    sub_matches = []
    for cid in engine.drug_ids:
        name = engine.drug_name(cid)
        if not name or name.lower() == "nan":
            continue
        nl = name.lower()
        if nl in seen:
            continue
        if nl.startswith(clean_q):
            prefix_matches.append({"name": name, "cid": str(cid), "source": "known"})
            seen.add(nl)
        elif clean_q in nl:
            sub_matches.append({"name": name, "cid": str(cid), "source": "known"})
            seen.add(nl)

    results.extend(prefix_matches[:8])
    results.extend(sub_matches[:8 - len(results)])

    # 2. Return immediately if we already have local/brand matches (instant ~10ms response)
    if len(results) >= 1:
        return {"results": results[:12]}

    # 3. Live PubChem fallback only when needed (with strict 1.0s timeout)
    if len(clean_q) >= 3:
        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound/{requests.utils.quote(clean_q)}/json?limit=6"
            headers = {"User-Agent": "InteractomeX/1.0"}
            r = requests.get(url, timeout=1.0, headers=headers)
            if r.status_code == 200:
                terms = r.json().get("dictionary_terms", {}).get("compound", [])
                for term in terms:
                    tl = term.lower()
                    if tl not in seen and len(results) < 12:
                        results.append({"name": term, "cid": None, "source": "pubchem"})
                        seen.add(tl)
        except Exception:
            pass

    return {"results": results[:12]}


@app.get("/api/drug/resolve")
async def resolve_drug(q: str):
    """
    Universal resolver for drug name OR PubChem CID.
    Returns: {"name": str, "cid": str, "smiles": str}
    """
    if not q or not q.strip():
        raise HTTPException(422, "Query parameter 'q' is required")

    clean_q = q.strip()
    engine = get_engine()

    # 0. Check clinical brand aliases
    alias_cid = COMMON_BRAND_ALIASES.get(clean_q.lower())
    if alias_cid:
        smiles = cid_to_smiles(alias_cid)
        canonical_name = engine.drug_name(alias_cid) or clean_q
        if smiles:
            return {"name": canonical_name, "cid": alias_cid, "smiles": smiles}

    # 1. Check if q is numeric CID or CID string
    is_numeric_cid = clean_q.isdigit() or clean_q.upper().startswith("CID")
    if is_numeric_cid:
        cid_str = clean_q.upper() if clean_q.upper().startswith("CID") else f"CID{clean_q.zfill(8)}"
        smiles = cid_to_smiles(cid_str)
        name = engine.drug_name(cid_str) or clean_q
        if smiles:
            return {"name": name, "cid": cid_str, "smiles": smiles}

    # 2. Check local curated database by name
    matched_cid = engine.find_cid_by_name(clean_q)
    if matched_cid:
        smiles = cid_to_smiles(matched_cid)
        if smiles:
            return {"name": clean_q, "cid": matched_cid, "smiles": smiles}

    # 3. Query PubChem by name
    smiles, resolved_cid = name_to_smiles(clean_q)
    if smiles:
        return {"name": clean_q, "cid": resolved_cid or matched_cid, "smiles": smiles}

    # 4. Fallback attempt directly via cid_to_smiles
    smiles = cid_to_smiles(clean_q)
    if smiles:
        return {"name": clean_q, "cid": clean_q, "smiles": smiles}

    raise HTTPException(404, f"Could not find compound or SMILES for {clean_q!r}")


@app.get("/api/drug/{cid}/smiles")
async def drug_smiles(cid: str):
    """Look up canonical SMILES for a PubChem CID or drug name."""
    clean_key = cid.lower().strip()
    alias_cid = COMMON_BRAND_ALIASES.get(clean_key)
    if alias_cid:
        s = cid_to_smiles(alias_cid)
        if s:
            return {"cid": alias_cid, "smiles": s}

    engine = get_engine()
    matched_cid = engine.find_cid_by_name(cid)
    if matched_cid:
        s = cid_to_smiles(matched_cid)
        if s:
            return {"cid": matched_cid, "smiles": s}

    s = cid_to_smiles(cid)
    if s:
        return {"cid": cid, "smiles": s}

    s, resolved_cid = name_to_smiles(cid)
    if s:
        return {"cid": resolved_cid or cid, "smiles": s}

    raise HTTPException(404, f"Could not retrieve SMILES for {cid!r}")


@app.post("/api/predict")
async def predict(req: PredictRequest):
    """
    Predict drug–drug interaction.

    Accepts any combination of SMILES / CID / drug name for each drug.
    Priority: smiles > cid > name
    """
    engine = get_engine()

    async def resolve_smiles(smiles, cid, name, label):
        if smiles:
            return smiles, cid

        # Normalize input: user may have entered a name into cid, or a CID number into name
        raw_val = cid or name
        if not raw_val:
            raise HTTPException(422, f"Provide drug name, PubChem CID, or SMILES for {label}")

        raw_str = str(raw_val).strip()

        # Check brand aliases first (e.g. Dolo -> Paracetamol)
        alias_cid = COMMON_BRAND_ALIASES.get(raw_str.lower())
        if alias_cid:
            s = cid_to_smiles(alias_cid)
            if s:
                return s, alias_cid

        is_numeric_cid = raw_str.isdigit() or raw_str.upper().startswith("CID")

        if is_numeric_cid:
            s = cid_to_smiles(raw_str)
            if s:
                return s, raw_str
            # If CID lookup failed, attempt name matching as fallback
            matched_cid = engine.find_cid_by_name(raw_str)
            if matched_cid:
                s = cid_to_smiles(matched_cid)
                if s:
                    return s, matched_cid

        # Resolve as Drug Name or clinical brand alias
        matched_cid = engine.find_cid_by_name(raw_str)
        if matched_cid:
            s = cid_to_smiles(matched_cid)
            if s:
                return s, matched_cid

        s, resolved_cid = name_to_smiles(raw_str)
        if s:
            return s, resolved_cid or matched_cid

        # If resolution completely failed:
        if is_numeric_cid:
            raise HTTPException(422, f"Could not fetch SMILES for {label} CID {raw_str!r}")
        raise HTTPException(422, f"Could not fetch SMILES for {label} name {raw_str!r}")

    # Immediate pre-resolution duplicate check
    if is_same_compound(
        smiles_a=req.smiles_a,
        smiles_b=req.smiles_b,
        cid_a=req.cid_a,
        cid_b=req.cid_b,
        name_a=req.name_a,
        name_b=req.name_b,
    ):
        raise HTTPException(
            422,
            "Drug A and Drug B are identical. DDI prediction requires two distinct compounds.",
        )

    smiles_a, resolved_cid_a = await resolve_smiles(
        req.smiles_a, req.cid_a, req.name_a, "Drug A"
    )
    smiles_b, resolved_cid_b = await resolve_smiles(
        req.smiles_b, req.cid_b, req.name_b, "Drug B"
    )

    if is_same_compound(
        smiles_a=smiles_a,
        smiles_b=smiles_b,
        cid_a=resolved_cid_a or req.cid_a,
        cid_b=resolved_cid_b or req.cid_b,
        name_a=req.name_a,
        name_b=req.name_b,
    ):
        raise HTTPException(
            422,
            "Drug A and Drug B are identical. DDI prediction requires two distinct compounds.",
        )

    try:
        result = engine.predict(
            smiles_a, smiles_b,
            cid_a=resolved_cid_a,
            cid_b=resolved_cid_b,
            check_dataset=req.check_dataset,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    name_a = req.name_a or (engine.drug_name(resolved_cid_a) if resolved_cid_a else None) or "Drug A"
    name_b = req.name_b or (engine.drug_name(resolved_cid_b) if resolved_cid_b else None) or "Drug B"
    name_a = str(name_a).strip() if name_a and str(name_a).strip().lower() != "nan" else "Drug A"
    name_b = str(name_b).strip() if name_b and str(name_b).strip().lower() != "nan" else "Drug B"

    # Augment molecule names
    if "molecules" in result:
        result["molecules"]["drug_a"]["name"] = name_a
        result["molecules"]["drug_b"]["name"] = name_b

    return {
        "drug_a": {"name": name_a, "smiles": smiles_a, "cid": resolved_cid_a},
        "drug_b": {"name": name_b, "smiles": smiles_b, "cid": resolved_cid_b},
        **result,
    }


def get_available_port(preferred: int = 8000) -> int:
    import socket
    for candidate in [preferred, 8050, 8080, 8001]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", candidate))
            s.close()
            return candidate
        except OSError:
            continue
    return preferred


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 0)) or get_available_port(8000)
    print("\n" + "=" * 60)
    print("  InteractomeX Live Web App")
    print(f"  Open in browser: http://127.0.0.1:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("api:app", host="127.0.0.1", port=port, reload=True)

