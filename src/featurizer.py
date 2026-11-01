"""
InteractomeX – Drug featurizer.

Converts a SMILES string into:
  1. A PyTorch-Geometric Data object (molecular graph)
  2. A 2048-bit Morgan fingerprint tensor
  3. A 12-dim normalised molecular descriptor tensor

All feature dimensions and normalisation constants must match those
stored in the trained model checkpoint (ddi_v23_best.pkl).
"""

from __future__ import annotations

import numpy as np
import torch
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
from torch_geometric.data import Data

# ---------------------------------------------------------------------------
# Atom feature helpers
# ---------------------------------------------------------------------------

# Atom types seen during training (from common drug-like molecules)
_ATOM_TYPES = [
    'C', 'N', 'O', 'S', 'F', 'Si', 'P', 'Cl', 'Br', 'Mg', 'Na', 'Ca',
    'Fe', 'As', 'Al', 'I',  'B',  'V',  'K',  'Tl', 'Yb', 'Sb', 'Sn',
    'Ag', 'Pd', 'Co', 'Se', 'Ti', 'Zn', 'H',  'Li', 'Ge', 'Cu', 'Au',
    'Ni', 'Cd', 'In',
]  # 37 types → one-hot = 37-dim  ✓ matches conv1.lin_l.weight shape (256, 37)

_BOND_TYPES = [
    Chem.rdchem.BondType.SINGLE,
    Chem.rdchem.BondType.DOUBLE,
    Chem.rdchem.BondType.TRIPLE,
    Chem.rdchem.BondType.AROMATIC,
]  # 4 types + 3 extra flags = 7  ✓ matches lin_edge.weight shape (256, 7)


def _atom_feats(atom: Chem.Atom) -> list[float]:
    """Return 37-dimensional one-hot atom feature vector."""
    symbol = atom.GetSymbol()
    try:
        idx = _ATOM_TYPES.index(symbol)
    except ValueError:
        idx = len(_ATOM_TYPES) - 1  # map unknown → last bucket
    one_hot = [0.0] * len(_ATOM_TYPES)
    one_hot[idx] = 1.0
    return one_hot


def _bond_feats(bond: Chem.Bond) -> list[float]:
    """Return 7-dimensional bond feature vector."""
    bt = bond.GetBondType()
    bt_one_hot = [float(bt == t) for t in _BOND_TYPES]          # 4 dims
    conjugated  = float(bond.GetIsConjugated())                   # 1 dim
    in_ring     = float(bond.IsInRing())                          # 1 dim
    stereo      = float(bond.GetStereo() != Chem.rdchem.BondStereo.STEREONONE)  # 1 dim
    return bt_one_hot + [conjugated, in_ring, stereo]             # 7 dims ✓


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DESC_NAMES = [
    'MolWt', 'LogP', 'TPSA', 'HBD', 'HBA',
    'RotatableBonds', 'RingCount', 'AromaticRings',
    'FractionCSP3', 'HeavyAtomCount', 'AliphaticRings', 'SaturatedRings',
]


def smiles_to_graph(smiles: str) -> Data:
    """Convert SMILES → PyG Data with 37-dim atom features & 7-dim edge features."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smiles!r}")

    atom_features = [_atom_feats(a) for a in mol.GetAtoms()]
    x = torch.tensor(atom_features, dtype=torch.float)

    edge_index, edge_attr = [], []
    for bond in mol.GetBonds():
        i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        feat  = _bond_feats(bond)
        edge_index += [[i, j], [j, i]]
        edge_attr  += [feat, feat]

    if edge_index:
        ei = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
        ea = torch.tensor(edge_attr,  dtype=torch.float)
    else:
        ei = torch.zeros((2, 0), dtype=torch.long)
        ea = torch.zeros((0, 7),  dtype=torch.float)

    return Data(x=x, edge_index=ei, edge_attr=ea)


try:
    from rdkit.Chem import rdFingerprintGenerator
    _morgan_gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
except Exception:
    _morgan_gen = None


def smiles_to_fp(smiles: str) -> torch.Tensor:
    """Convert SMILES → 2048-bit Morgan fingerprint tensor."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smiles!r}")
    if _morgan_gen is not None:
        fp = _morgan_gen.GetFingerprint(mol)
    else:
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
    arr = np.array(fp, dtype=np.float32)
    return torch.tensor(arr).unsqueeze(0)   # (1, 2048)


def smiles_to_desc(
    smiles: str,
    mean: np.ndarray,
    std: np.ndarray,
) -> torch.Tensor:
    """
    Compute 12 RDKit descriptors and z-score normalise using training statistics.

    Parameters
    ----------
    mean, std : ndarray of shape (12,)
        Stored in model['desc_mean'] / model['desc_std'].
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smiles!r}")

    raw = np.array([
        Descriptors.MolWt(mol),
        Descriptors.MolLogP(mol),
        Descriptors.TPSA(mol),
        rdMolDescriptors.CalcNumHBD(mol),
        rdMolDescriptors.CalcNumHBA(mol),
        rdMolDescriptors.CalcNumRotatableBonds(mol),
        rdMolDescriptors.CalcNumRings(mol),
        rdMolDescriptors.CalcNumAromaticRings(mol),
        Descriptors.FractionCSP3(mol),
        float(mol.GetNumHeavyAtoms()),
        rdMolDescriptors.CalcNumAliphaticRings(mol),
        rdMolDescriptors.CalcNumSaturatedRings(mol),
    ], dtype=np.float32)

    normalised = (raw - mean) / (std + 1e-8)
    return torch.tensor(normalised).unsqueeze(0)   # (1, 12)
