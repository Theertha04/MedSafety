"""
InteractomeX – Model inference engine.

Loads ddi_v23_best.pkl, reconstructs the DDIModel, and exposes a clean
`predict(smiles_a, smiles_b)` function that returns a structured result dict.

Dataset membership (was this pair in the training CSV?) is treated as an
OPTIONAL feature and is only checked when explicitly requested.
pair_df.csv is never assumed to exist.
"""

from __future__ import annotations

import os
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from torch_geometric.data import Batch
import requests

from .featurizer import smiles_to_graph, smiles_to_fp, smiles_to_desc
from .model import DDIModel
from .explainability import compute_full_explainability

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE = Path(__file__).resolve().parent.parent
_V24_PATH = _BASE / "models" / "ddi_v24_best.pkl"
_V23_PATH = _BASE / "models" / "ddi_v23_best.pkl"
_MODEL_PATH = _V24_PATH if _V24_PATH.exists() else _V23_PATH
_RAW_CSV    = _BASE / "data" / "raw" / "ddis (1).csv"
_PAIR_CACHE = _BASE / "data" / "processed" / "pair_set.pkl"
_NAME_CACHE = _BASE / "data" / "processed" / "cid_to_name_cache.csv"

# ---------------------------------------------------------------------------
# Chemical Drawing & Descriptor Utilities
# ---------------------------------------------------------------------------
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D


def smiles_to_svg(smiles: str, width: int = 280, height: int = 180) -> Optional[str]:
    """Generate dark-mode friendly 2D molecular structure SVG."""
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        opts = drawer.drawOptions()
        opts.clearBackground = False
        opts.bondLineWidth = 2
        # Soft slate-light palette for dark background
        opts.updateAtomPalette({0: (0.85, 0.90, 0.98), 6: (0.85, 0.90, 0.98)})
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return None


def is_same_compound(
    smiles_a: Optional[str] = None,
    smiles_b: Optional[str] = None,
    cid_a: Optional[str] = None,
    cid_b: Optional[str] = None,
    name_a: Optional[str] = None,
    name_b: Optional[str] = None,
) -> bool:
    """Check if two drug inputs represent the identical chemical compound."""
    import re

    # 1. Match by CID if both are provided (normalize numeric CID value)
    if cid_a and cid_b:
        num_a = re.sub(r'\D', '', str(cid_a))
        num_b = re.sub(r'\D', '', str(cid_b))
        if num_a and num_b and int(num_a) == int(num_b):
            return True
        clean_a = str(cid_a).strip().upper()
        clean_b = str(cid_b).strip().upper()
        if clean_a and clean_b and clean_a == clean_b:
            return True

    # 2. Match by Name if both are provided
    if name_a and name_b:
        n_a = str(name_a).strip().lower()
        n_b = str(name_b).strip().lower()
        if n_a and n_b and n_a == n_b:
            return True

    # 3. Match by SMILES (exact string or canonicalized RDKit representation)
    if smiles_a and smiles_b:
        sa = str(smiles_a).strip()
        sb = str(smiles_b).strip()
        if sa and sb:
            if sa == sb:
                return True
            try:
                can_a = Chem.CanonSmiles(sa)
                can_b = Chem.CanonSmiles(sb)
                if can_a == can_b:
                    return True
            except Exception:
                pass

    return False


import math
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.jit")

def smiles_to_raw_descriptors(smiles: str) -> list[dict]:
    """Calculate key physicochemical descriptors with descriptions and units."""
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return []

        def safe_f(v, digits=None, default=0.0):
            try:
                val = float(v)
                if math.isnan(val) or math.isinf(val):
                    return default
                return round(val, digits) if digits is not None else int(val)
            except Exception:
                return default

        meta = [
            ("MolWt", "Molecular Weight", safe_f(Descriptors.MolWt(mol), 2), "g/mol", "Mass of the uncharged molecule"),
            ("MolLogP", "LogP (Lipophilicity)", safe_f(Descriptors.MolLogP(mol), 2), "", "Octanol-water partition coefficient"),
            ("TPSA", "Polar Surface Area (TPSA)", safe_f(Descriptors.TPSA(mol), 2), "Å²", "Sum of surfaces of all polar atoms"),
            ("HBD", "H-Bond Donors", safe_f(rdMolDescriptors.CalcNumHBD(mol)), "", "Count of hydrogen bond donor groups (OH, NH)"),
            ("HBA", "H-Bond Acceptors", safe_f(rdMolDescriptors.CalcNumHBA(mol)), "", "Count of hydrogen bond acceptor atoms (N, O)"),
            ("RotatableBonds", "Rotatable Bonds", safe_f(rdMolDescriptors.CalcNumRotatableBonds(mol)), "", "Count of flexible non-ring single bonds"),
            ("RingCount", "Total Rings", safe_f(rdMolDescriptors.CalcNumRings(mol)), "", "Number of ring assemblies"),
            ("AromaticRings", "Aromatic Rings", safe_f(rdMolDescriptors.CalcNumAromaticRings(mol)), "", "Count of aromatic ring systems"),
            ("FractionCSP3", "Fraction Csp3", safe_f(Descriptors.FractionCSP3(mol), 3), "", "Fraction of sp3 carbons to total carbons"),
            ("HeavyAtomCount", "Heavy Atoms", safe_f(mol.GetNumHeavyAtoms()), "", "Count of non-hydrogen atoms"),
            ("AliphaticRings", "Aliphatic Rings", safe_f(rdMolDescriptors.CalcNumAliphaticRings(mol)), "", "Count of non-aromatic rings"),
            ("SaturatedRings", "Saturated Rings", safe_f(rdMolDescriptors.CalcNumSaturatedRings(mol)), "", "Count of completely saturated rings"),
        ]
        return [
            {"key": k, "label": label, "value": val, "unit": unit, "tooltip": tip}
            for k, label, val, unit, tip in meta
        ]
    except Exception:
        return []


def format_type_name(raw_name: str) -> str:
    """Format interaction type names into clean, readable titles."""
    name = raw_name.replace(" NOS ", " ").replace(" NOS", "")
    name = " ".join(word.capitalize() for word in name.split())
    return name


# ---------------------------------------------------------------------------
# PubChem SMILES lookup with persistent disk & in-memory cache
# ---------------------------------------------------------------------------
_SMILES_CACHE_FILE = _BASE / "data" / "processed" / "smiles_cache.json"
_smiles_cache: dict[str, any] = {}

if _SMILES_CACHE_FILE.exists():
    try:
        import json
        with open(_SMILES_CACHE_FILE, "r", encoding="utf-8") as _f:
            _smiles_cache = json.load(_f)
    except Exception:
        _smiles_cache = {}


def _save_smiles_cache():
    try:
        import json
        with open(_SMILES_CACHE_FILE, "w", encoding="utf-8") as _f:
            json.dump(_smiles_cache, _f, indent=2)
    except Exception:
        pass


def cid_to_smiles(cid: str) -> Optional[str]:
    """Fetch canonical SMILES for a PubChem CID. Returns None on failure."""
    clean_cid = str(cid).strip().upper()
    if clean_cid in _smiles_cache:
        val = _smiles_cache[clean_cid]
        return val[0] if isinstance(val, (list, tuple)) else val

    num = clean_cid.replace("CID", "").lstrip("0") or "0"
    if num in _smiles_cache:
        val = _smiles_cache[num]
        return val[0] if isinstance(val, (list, tuple)) else val

    # Try PubChem lookup with retry
    import time
    for attempt in range(2):
        try:
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{num}/property/SMILES,IsomericSMILES,CanonicalSMILES,ConnectivitySMILES/JSON"
            headers = {"User-Agent": "InteractomeX/1.0"}
            r = requests.get(url, timeout=6, headers=headers)
            if r.status_code == 200:
                props = r.json()["PropertyTable"]["Properties"][0]
                smiles = props.get("SMILES") or props.get("IsomericSMILES") or props.get("CanonicalSMILES") or props.get("ConnectivitySMILES")
                if smiles:
                    _smiles_cache[clean_cid] = smiles
                    _save_smiles_cache()
                return smiles
            elif r.status_code == 503 and attempt == 0:
                time.sleep(0.8)
                continue
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
    return None


def name_to_smiles(name: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch (SMILES, CID) for a drug name via PubChem. Returns (None, None) on failure."""
    clean = str(name).strip()
    key = f"name:{clean.lower()}"
    if key in _smiles_cache:
        cached = _smiles_cache[key]
        if isinstance(cached, (list, tuple)):
            return cached[0], cached[1]
        return cached, None

    import time
    for attempt in range(2):
        try:
            url = (
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                f"{requests.utils.quote(clean)}/property/SMILES,IsomericSMILES,CanonicalSMILES,ConnectivitySMILES/JSON"
            )
            headers = {"User-Agent": "InteractomeX/1.0"}
            r = requests.get(url, timeout=6, headers=headers)
            if r.status_code == 200:
                props = r.json()["PropertyTable"]["Properties"][0]
                smiles = props.get("SMILES") or props.get("IsomericSMILES") or props.get("CanonicalSMILES") or props.get("ConnectivitySMILES")
                cid_val = props.get("CID")
                cid_str = f"CID{str(cid_val).zfill(8)}" if cid_val else None
                res = [smiles, cid_str]
                if smiles:
                    _smiles_cache[key] = res
                    if cid_str:
                        _smiles_cache[cid_str] = smiles
                    _save_smiles_cache()
                return smiles, cid_str
            elif r.status_code == 503 and attempt == 0:
                time.sleep(0.8)
                continue
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
    return None, None


# ---------------------------------------------------------------------------
# Model loader (singleton, lazy)
# ---------------------------------------------------------------------------
_engine: Optional["InferenceEngine"] = None


def get_engine() -> "InferenceEngine":
    global _engine
    if _engine is None:
        _engine = InferenceEngine(_MODEL_PATH)
    return _engine


class InferenceEngine:
    """Wraps the trained DDIModel and exposes high-level predict()."""

    def __init__(self, model_path: Path) -> None:
        with open(model_path, "rb") as f:
            ckpt = pickle.load(f)

        self.drug_ids: list[str]      = ckpt["drug_ids"]
        self.drug_id_set: set[str]    = set(self.drug_ids)
        self.gate_threshold: float    = ckpt["gate_threshold"]
        self.gate_temp: float         = ckpt["gate_temperature"]
        self.type_thresholds: np.ndarray = np.array(ckpt["type_thresholds"])
        self.top_types: list[int]     = ckpt["top_types"]
        self.type_names: dict[int, str] = ckpt["type_names"]
        self.target_se: list[str]     = ckpt.get("target_side_effects", [])
        self.input_se: list[str]      = ckpt.get("input_side_effects", [])
        self.clinical_action_classes: list[str] = ckpt.get("clinical_action_classes", [
            "Class 0: Safe Concomitant Use (Standard Regimen)",
            "Class 1: Time-Separated Administration (Spacing: 2-4 Hours)",
            "Class 2: Dose Adjustment & Clinical Monitoring",
            "Class 3: Strict Contraindication (Absolute Avoidance)"
        ])
        self.n_actions: int           = ckpt.get("n_actions", len(self.clinical_action_classes))
        self.desc_mean: np.ndarray    = ckpt["desc_mean"]
        self.desc_std:  np.ndarray    = ckpt["desc_std"]

        # Rule-based clinical severity mapping from notebook v24 (Cell 51 & Cell 63)
        self.SEV_NAMES = {-1: "None", 0: "Low", 1: "Moderate", 2: "High"}
        self.HIGH_KW = [
            'haemorrhag', 'hemorrhag', 'bleed', 'renal failure', 'kidney failure', 'acute kidney', 'hepatic failure',
            'liver failure', 'cardiac arrest', 'cardiac failure', 'heart failure', 'myocardial infarction', 'stroke',
            'cerebrovascular', 'torsade', 'qt prolong', 'ventricular', 'arrhythm', 'serotonin syndrome',
            'rhabdomyolysis', 'anaphyla', 'angioedema', 'seizure', 'convulsion', 'respiratory depression',
            'respiratory failure', 'respiratory arrest', 'sepsis', 'septic', 'shock', 'coma', 'embol', 'thrombosis',
            'death', 'suicid', 'agranulocytosis', 'pancytopenia', 'stevens-johnson', 'toxic epidermal', 'overdose',
            'hyperkal'
        ]
        self.MOD_KW = [
            'hypotension', 'hypertension', 'tachycardia', 'bradycardia', 'syncope', 'dizz', 'confusion', 'anaemia',
            'anemia', 'thrombocytopenia', 'leukopenia', 'neutropenia', 'dehydration', 'hypoglyc', 'hypokal',
            'hyponat', 'hypercalc', 'oedema', 'edema', 'vomit', 'diarrh', 'pneumonia', 'infection', 'pain',
            'fracture', 'renal', 'hepatic', 'liver', 'jaundice', 'dyspn', 'asthma', 'depress', 'anxiety',
            'hallucinat', 'somnolence', 'sedation', 'tremor', 'rash', 'urticaria', 'pruritus', 'fever', 'pyrexia',
            'insomnia', 'palpitation', 'chest', 'cough'
        ]
        self.SEV_OVERRIDE = {
            'Difficulty breathing': 2, 'Hypoventilation': 2,
            'arterial pressure NOS decreased': 1, 'nausea': 1, 'neumonia': 1, 'Fatigue': 1,
            'asthenia': 1, 'emesis': 1, 'body temperature increased': 1, 'Back Ache': 1,
            'Head ache': 1, 'High blood pressure': 1, 'hyperglycaemia': 1, 'Anorexia': 1,
            'Aching joints': 1, 'neuropathy': 1, 'constipated': 1, 'heart rate increased': 1,
            'Pleural Effusion': 1,
        }

        self.CLEAN_TYPE_NAMES = {
            45: "Severe Hypotension (Low Blood Pressure)",
            68: "Anaemia (Low Red Blood Cells)",
            24: "Difficulty Breathing (Dyspnea)",
            348: "Nausea",
            62: "Pneumonia",
            121: "Fatigue & Lethargy",
            98: "Generalized Pain",
            124: "Diarrhea",
            200: "Asthenia (Muscle Weakness)",
            201: "Vomiting (Emesis)",
            297: "Peripheral Edema (Swollen Extremities)",
            320: "Pyrexia (Fever / High Temperature)",
            227: "Pleural Pain",
            172: "Abdominal Pain",
            53: "Hypoventilation (Respiratory Depression)",
            173: "Chest Pain (Angina)",
            116: "Dizziness & Vertigo",
            1: "Back Pain",
            77: "Headache",
            219: "Hypertension (High Blood Pressure)",
            64: "Cognitive Confusion",
            326: "Dehydration",
            335: "Anxiety & Agitation",
            260: "Renal / Kidney Impairment",
            185: "Weight Loss",
            17: "Hyperglycemia (High Blood Sugar)",
            54: "Edema (Fluid Retention)",
            72: "Anorexia (Loss of Appetite)",
            237: "Arthralgia (Joint Pain)",
            148: "Acute Kidney Injury",
            478: "Peripheral Neuropathy",
            205: "Extremity Pain",
            323: "Urinary Tract Infection",
            264: "Persistent Cough",
            137: "Constipation",
            332: "Tachycardia (Rapid Heart Rate)",
            410: "Weight Gain",
            12: "Thrombocytopenia (Low Platelets)",
            351: "Pleural Effusion (Fluid in Lungs)",
            27: "Sepsis Risk",
        }

        self.TYPE_CLINICAL_EXPLANATIONS = {
            45: "Additive vasodilatory or sympatholytic activity may precipitate a sudden drop in blood pressure, risking orthostatic dizziness or syncope.",
            68: "Synergistic microvascular irritation or bone marrow suppression reduces circulating red blood cells, impairing systemic oxygen delivery.",
            24: "Combined central nervous system or respiratory muscle depression compromises breathing depth and lung ventilation.",
            348: "Concurrent gastric mucosal irritation and central chemoreceptor trigger zone stimulation induces persistent nausea.",
            62: "Immunosuppressive interaction or impaired airway clearance increases vulnerability to secondary pulmonary infection.",
            121: "Additive central sedating and systemic metabolic depression produces severe lethargy and exhaustion.",
            98: "Altered pain threshold, acute tissue ischemia, or neuromuscular hypersensitivity exacerbates localized or generalized pain.",
            124: "Disruption of intestinal motility or mucosal fluid homeostasis accelerates bowel transit and fluid loss.",
            200: "Generalized loss of muscle tone and physical vitality resulting from combined central depressive effects.",
            201: "Synergistic activation of gastric vagal afferents and the central emetic reflex triggers recurrent vomiting and dehydration risk.",
            297: "Capillary hyperpermeability or renal sodium retention causes peripheral fluid accumulation in the lower extremities.",
            320: "Dysregulation of hypothalamic thermoregulatory pathways or drug-induced inflammatory response elevates core body temperature.",
            227: "Irritation or inflammatory friction of the pleural membranes causes sharp, respiration-dependent chest discomfort.",
            172: "Gastric hyperacidity, mucosal ulceration, or intestinal spasm produces localized abdominal cramping and tenderness.",
            53: "Profound depression of the brainstem respiratory center decreases breathing rate and tidal volume, risking acute hypoxia.",
            173: "Elevated myocardial oxygen demand or coronary vasospasm triggers acute angina-like retrosternal discomfort.",
            116: "Transient cerebral hypoperfusion or vestibular signaling disturbance impairs balance and spatial orientation.",
            1: "Musculoskeletal tension or renal capsular irritation can manifest as localized lumbar discomfort.",
            77: "Cerebrovascular tone modulation or dural vessel dilation precipitates throbbing cephalalgia.",
            219: "Additive peripheral vasoconstriction or fluid retention elevates systemic vascular resistance and arterial pressure.",
            64: "Disruption of central neurotransmission (cholinergic, GABAergic, or dopaminergic) causes acute disorientation.",
            326: "Accelerated renal or gastrointestinal fluid depletion without compensatory intake impairs hydration balance.",
            335: "Sympathetic nervous system hyperactivation or central GABAergic withdrawal produces psychomotor agitation.",
            260: "Impaired renal hemodynamics or cumulative nephrotoxic stress compromises glomerular filtration capacity.",
            185: "Suppression of appetite, catabolic acceleration, or gastrointestinal malabsorption leads to unintended weight reduction.",
            17: "Suppression of pancreatic insulin release or elevated peripheral insulin resistance raises circulating blood glucose.",
            54: "Generalized extracellular fluid retention caused by altered hydrostatic pressure or vascular leakage.",
            72: "Suppression of central hypothalamic appetite-regulating centers produces a marked loss of desire for food.",
            237: "Drug-induced synovial irritation, inflammatory mediator release, or musculoskeletal strain causes joint ache.",
            148: "Rapid deterioration of renal perfusion and tubular cellular injury heightens the risk of acute kidney impairment.",
            478: "Axonal stress or demyelinating neurotoxicity produces distal extremity numbness, tingling, and sensory deficits.",
            205: "Localized vascular insufficiency, muscular spasm, or neuropathic irritation causes limb pain.",
            323: "Altered urinary pH, bladder voiding dysfunction, or local immune suppression facilitates bacterial colonization.",
            264: "Bradykinin accumulation, airway hyperreactivity, or bronchial irritation triggers persistent coughing.",
            137: "Suppression of gastrointestinal motility and mucosal dehydration significantly delays colonic transit.",
            332: "Sympathomimetic stimulation, vagal withdrawal, or compensatory reflex mechanisms induce sustained tachycardia.",
            410: "Altered metabolic rate, increased appetite, or persistent fluid accumulation causes gradual weight gain.",
            12: "Impaired megakaryocyte maturation or immune-mediated platelet clearance increases bleeding and bruising risk.",
            351: "Elevated hydrostatic pressure or inflammatory exudation causes abnormal fluid collection in the pleural space.",
            27: "Severe immune suppression or escalated systemic inflammatory cascade enables life-threatening widespread infection.",
        }

        import re
        def _sev_of(name):
            n = str(name).lower()
            if name in self.SEV_OVERRIDE:
                return self.SEV_OVERRIDE[name]
            for tier, kws in ((2, self.HIGH_KW), (1, self.MOD_KW)):
                for kw in kws:
                    if re.search(r'\b' + re.escape(kw), n):
                        return tier
            return 0

        self.sev_vec = np.array([_sev_of(self.type_names.get(t, "")) for t in self.top_types], dtype=np.float32)
        self.risk_edges = [1.0, 1.125]  # Empirical [1/3, 2/3] quantile cutoffs from training pairs

        # Rebuild and load model
        self.model = DDIModel()
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()

        # Name cache
        self._name_map: dict[str, str] = {}
        self._name_to_cid: dict[str, str] = {}
        if _NAME_CACHE.exists():
            import pandas as pd
            nc = pd.read_csv(_NAME_CACHE)
            for _, row in nc.iterrows():
                cid_val = row.get("drug_id")
                if pd.isna(cid_val):
                    continue
                cid_str = str(cid_val).strip()
                name_val = row.get("name")
                if pd.isna(name_val):
                    continue
                name_str = str(name_val).strip()
                if not name_str or name_str.lower() == "nan":
                    continue
                self._name_map[cid_str] = name_str
                self._name_to_cid[name_str.lower()] = cid_str

        # Popular clinical brand aliases and trade names mapped to benchmark CIDs
        brand_aliases = {
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
            "ecospirin": "CID000002244",
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
        for alias, target_cid in brand_aliases.items():
            if alias not in self._name_to_cid:
                self._name_to_cid[alias] = target_cid

        # Fast dataset membership index
        self._positive_pair_index: Optional[set[tuple[str, str]]] = None
        if _PAIR_CACHE.exists():
            try:
                with open(_PAIR_CACHE, "rb") as pf:
                    self._positive_pair_index = pickle.load(pf)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def drug_name(self, cid: str) -> str:
        if not cid:
            return ""
        name = self._name_map.get(cid)
        if name and isinstance(name, str) and name.strip() and name.strip().lower() != "nan":
            return name.strip()
        return str(cid).strip()

    def find_cid_by_name(self, name: str) -> Optional[str]:
        if not name or not isinstance(name, str):
            return None
        return self._name_to_cid.get(name.lower().strip())

    # ------------------------------------------------------------------
    def featurize(self, smiles: str):
        """Return (graph, fp, desc) tensors for a single SMILES string."""
        graph = smiles_to_graph(smiles)
        graph.batch = torch.zeros(graph.num_nodes, dtype=torch.long)
        fp    = smiles_to_fp(smiles)
        desc  = smiles_to_desc(smiles, self.desc_mean, self.desc_std)
        return graph, fp, desc

    # ------------------------------------------------------------------
    def predict(
        self,
        smiles_a: str,
        smiles_b: str,
        cid_a: Optional[str] = None,
        cid_b: Optional[str] = None,
        check_dataset: bool = True,
    ) -> dict:
        """
        Predict drug–drug interaction with full score breakdowns and explainability.
        """
        if is_same_compound(smiles_a=smiles_a, smiles_b=smiles_b, cid_a=cid_a, cid_b=cid_b):
            raise ValueError("Drug A and Drug B are identical. DDI prediction requires two distinct compounds.")

        graphA, fpA, descA = self.featurize(smiles_a)
        graphB, fpB, descB = self.featurize(smiles_b)

        with torch.no_grad():
            gate_logit, type_logits, action_logits = self.model(
                graphA, fpA, descA,
                graphB, fpB, descB,
            )
            # Evaluate reverse order (B, A) to verify mathematical symmetry f(A,B) == f(B,A)
            gate_logit_rev, _, _ = self.model(
                graphB, fpB, descB,
                graphA, fpA, descA,
            )

        raw_logit = float(gate_logit.item())
        raw_sigmoid = float(torch.sigmoid(gate_logit).item())
        calibrated_prob = float(torch.sigmoid(gate_logit / self.gate_temp).item())

        rev_logit = float(gate_logit_rev.item())
        rev_sigmoid = float(torch.sigmoid(gate_logit_rev).item())
        rev_prob = float(torch.sigmoid(gate_logit_rev / self.gate_temp).item())

        interacts = calibrated_prob >= self.gate_threshold

        # Interaction types & rule-based clinical risk tier (notebook v24 Cell 51 & 63)
        type_probs = torch.sigmoid(type_logits).squeeze(0).numpy()
        active_types = []
        for i, tid in enumerate(self.top_types):
            prob = float(type_probs[i])
            thresh = float(self.type_thresholds[i])
            raw_t_name = self.type_names.get(tid, f"Type {tid}")
            display_name = self.CLEAN_TYPE_NAMES.get(tid, format_type_name(raw_t_name))
            clinical_expl = self.TYPE_CLINICAL_EXPLANATIONS.get(
                tid,
                f"Combined pharmacological exposure increases susceptibility to {display_name}."
            )
            active_types.append({
                "id": tid,
                "name": display_name,
                "clinical_explanation": clinical_expl,
                "prob": round(prob, 4),
                "threshold": round(thresh, 4),
                "is_active": prob >= thresh,
                "relative_margin": round(prob - thresh, 4),
                "severity_tier": self.SEV_NAMES[int(self.sev_vec[i])],
            })
        active_types.sort(key=lambda x: x["prob"], reverse=True)

        hit = type_probs >= self.type_thresholds
        n_active = int(hit.sum())
        sev_score = float((hit * self.sev_vec).sum() / max(n_active, 1.0)) if n_active > 0 else 0.0
        tier_idx = (int(sev_score > self.risk_edges[0]) + int(sev_score > self.risk_edges[1])) if (interacts and n_active > 0) else (-1 if not interacts else 0)
        risk_label = self.SEV_NAMES[tier_idx]
        risk_data = {
            "tier": tier_idx,
            "label": risk_label,
            "score": round(sev_score, 3),
            "active_types_count": n_active,
            "edges": self.risk_edges,
            "description": f"Clinical severity classified as {risk_label} based on {n_active} active interaction type(s)."
        }

        # Multi-class clinical prescribing action (v24)
        action_probs = torch.softmax(action_logits, dim=-1).squeeze(0).cpu().numpy()
        action_tier_idx = int(np.argmax(action_probs))
        action_label = self.clinical_action_classes[action_tier_idx]
        action_conf = float(action_probs[action_tier_idx])

        ACTION_RECOMMENDATIONS = {
            0: "These medications can be safely prescribed together using standard dosages. No significant interaction was detected between their chemical properties, requiring no adjustments to dose or schedule.",
            1: "Administer these medications at separate times, at least 2 to 4 hours apart. Spacing the doses prevents absorption conflicts in the gastrointestinal tract and ensures both medications remain effective.",
            2: "Dose adjustment and regular clinical monitoring are advised during concurrent use. Lowering the maintenance dose and checking routine laboratory parameters helps minimize adverse interaction risks.",
            3: "Avoid co-administration of these two medications. Concomitant use carries a high risk of severe toxicity or adverse clinical outcomes. An alternative medication should be selected."
        }

        clinical_action_data = {
            "tier": action_tier_idx,
            "label": action_label,
            "confidence": round(action_conf, 4),
            "recommendation": ACTION_RECOMMENDATIONS.get(action_tier_idx, ""),
            "class_probabilities": {
                cls_name: round(float(p), 4)
                for cls_name, p in zip(self.clinical_action_classes, action_probs)
            }
        }

        # Target side effects: backwards-compatibility empty lists if not in checkpoint
        side_effects_joint = []
        side_effects_a = []
        side_effects_b = []

        # Molecular profiles
        mol_a = {
            "smiles": smiles_a,
            "cid": cid_a,
            "svg": smiles_to_svg(smiles_a),
            "descriptors": smiles_to_raw_descriptors(smiles_a),
        }
        mol_b = {
            "smiles": smiles_b,
            "cid": cid_b,
            "svg": smiles_to_svg(smiles_b),
            "descriptors": smiles_to_raw_descriptors(smiles_b),
        }

        # Dataset verification
        in_dataset = None
        if check_dataset and cid_a and cid_b:
            in_dataset = self._check_dataset(cid_a, cid_b)

        # Detailed score interpretation
        if interacts:
            threshold_verdict = (
                f"Compared against the decision threshold ({self.gate_threshold:.4f}), "
                f"the calibrated score meets or exceeds the cutoff, predicting an active interaction affinity."
            )
        else:
            threshold_verdict = (
                f"Compared against the decision threshold ({self.gate_threshold:.4f}), "
                f"the calibrated score falls below the cutoff, indicating no significant interaction affinity is predicted."
            )

        explanation = {
            "score_interpretation": (
                f"The raw model output is logit {raw_logit:+.2f}, yielding an uncalibrated sigmoid score of "
                f"{raw_sigmoid * 100:.2f}%. Platt temperature scaling (T = {self.gate_temp:.4f}) calibrates this to "
                f"{calibrated_prob * 100:.2f}%. {threshold_verdict} Note that neural network probability reflects "
                f"representation space confidence and must not be conflated with clinical certainty or severity."
            ),
            "architecture_summary": (
                "Multi-modal fusion: 3-layer GATv2Conv graph encoder + 2048-bit Morgan Fingerprint MLP + "
                "12 RDKit physicochemical descriptors fused into a 256-dim embedding, then combined via "
                "symmetric representation [r1+r2, r1*r2, |r1-r2|] into a 768-dim trunk MLP."
            ),
            "symmetry_info": {
                "forward_logit": round(raw_logit, 4),
                "reverse_logit": round(rev_logit, 4),
                "forward_prob": round(calibrated_prob, 4),
                "reverse_prob": round(rev_prob, 4),
                "delta": round(abs(raw_logit - rev_logit), 4),
                "note": "The pair trunk uses a symmetric [r1+r2, r1*r2, |r1-r2|] tensor representation, guaranteeing mathematical order invariance f(A,B) == f(B,A)."
            },
            "attribution_note": (
                "Atom-level Grad-CAM highlights functional groups driving graph embeddings; SHAP values quantify bulk physicochemical descriptor influences; and fingerprint attribution identifies top substructural ECFP4 bit drivers."
            ),
        }

        # Explainability computation (Grad-CAM, SHAP, Morgan fingerprint attribution)
        xai_data = None
        try:
            xai_data = compute_full_explainability(
                self.model,
                graphA, fpA, descA,
                graphB, fpB, descB,
                smiles_a, smiles_b,
            )
        except Exception as xai_err:
            print(f"[XAI Warning] Explainability generation failed: {xai_err}")

        return {
            "interacts": bool(interacts),
            "gate_prob": round(calibrated_prob, 4),
            "raw_logit": round(raw_logit, 4),
            "raw_sigmoid": round(raw_sigmoid, 4),
            "gate_threshold": round(self.gate_threshold, 4),
            "gate_temperature": round(self.gate_temp, 4),
            "risk": risk_data,
            "symmetry": {
                "reverse_logit": round(rev_logit, 4),
                "reverse_prob": round(rev_prob, 4),
                "delta": round(abs(raw_logit - rev_logit), 4),
            },
            "active_interaction_types": active_types,
            "clinical_action": clinical_action_data,
            "predicted_side_effects": side_effects_joint,
            "drug_a_side_effects": side_effects_a,
            "drug_b_side_effects": side_effects_b,
            "molecules": {
                "drug_a": mol_a,
                "drug_b": mol_b,
            },
            "in_dataset": in_dataset,
            "explanation": explanation,
            "xai": xai_data,
        }

    # ------------------------------------------------------------------
    def _check_dataset(self, cid_a: str, cid_b: str) -> Optional[bool]:
        """
        Scan fast precomputed index or raw CSV to verify if (cid_a, cid_b)
        appears as a confirmed pair in training data.
        """
        if self._positive_pair_index is not None:
            return (cid_a, cid_b) in self._positive_pair_index

        if _PAIR_CACHE.exists():
            try:
                with open(_PAIR_CACHE, "rb") as pf:
                    self._positive_pair_index = pickle.load(pf)
                return (cid_a, cid_b) in self._positive_pair_index
            except Exception:
                pass

        if not _RAW_CSV.exists():
            return None
        import pandas as pd
        df = pd.read_csv(_RAW_CSV, usecols=["d1", "d2"])
        pairs = set(zip(df["d1"], df["d2"]))
        pairs |= {(b, a) for a, b in pairs}   # symmetric
        self._positive_pair_index = pairs
        return (cid_a, cid_b) in self._positive_pair_index
