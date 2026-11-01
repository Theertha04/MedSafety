"""
InteractomeX – GNN model definition.

Architecture matches the trained weights in ddi_v23_best.pkl.
Uses GATv2Conv layers with edge attributes, multi-modal drug fusion,
and multi-task prediction heads (Gate, Types, Target Side Effects).
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv, global_mean_pool


class DrugEncoder(nn.Module):
    """3-layer GATv2 encoder: atom-features × edge-features → 128-dim embedding."""

    def __init__(self) -> None:
        super().__init__()
        # conv1: (37 → 64, 4 heads, edge_dim=7) → total = 256
        self.conv1 = GATv2Conv(37, 64, heads=4, edge_dim=7, add_self_loops=False)
        # conv2: (256 → 64, 4 heads, edge_dim=7) → total = 256
        self.conv2 = GATv2Conv(256, 64, heads=4, edge_dim=7, add_self_loops=False)
        # conv3: (256 → 128, 1 head, edge_dim=7) → total = 128
        self.conv3 = GATv2Conv(256, 128, heads=1, edge_dim=7, add_self_loops=False)

    def forward(self, x, edge_index, edge_attr, batch):
        x = F.relu(self.conv1(x, edge_index, edge_attr))
        x = F.relu(self.conv2(x, edge_index, edge_attr))
        x = F.relu(self.conv3(x, edge_index, edge_attr))
        return global_mean_pool(x, batch)


class DDIModel(nn.Module):
    """
    Drug–Drug Interaction prediction model.

    Inputs (per drug):
      - Molecular graph  (atom feats: 37-dim, edge feats: 7-dim)
      - Morgan FP        (2048-bit)
      - Descriptors      (12 RDKit values, pre-normalised)

    Outputs:
      - gate_logit  : scalar – binary interaction probability
      - type_logits : (40,)  – per-type interaction probabilities
      - se_logits   : (50,)  – target side-effect probabilities
    """

    def __init__(self) -> None:
        super().__init__()
        self.register_buffer("known_mask", torch.zeros(645, 1))
        self.encoder = DrugEncoder()

        # Fingerprint branch: 2048 → 256 → 128
        self.fp_mlp = nn.Sequential(
            nn.Linear(2048, 256), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(256, 128),  nn.ReLU(),
        )

        # Descriptor branch: 12 → 64 → 32
        self.desc_mlp = nn.Sequential(
            nn.Linear(12, 64), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(64, 32),  nn.ReLU(),
        )

        # Per-drug projection: (128 GNN + 128 fp + 32 desc) = 288 → 256
        self.proj = nn.Sequential(nn.Linear(288, 256), nn.ReLU())

        # Pair trunk: 256×3 = 768 → 256  (symmetric representation: [r1+r2, r1*r2, |r1-r2|])
        self.trunk = nn.Sequential(nn.Linear(768, 256), nn.ReLU())

        # Heads
        self.head_gate  = nn.Linear(256, 1)
        self.head_types = nn.Linear(256, 40)
        # Clinical Prescribing Action Head (v24): hierarchical conditioning on trunk (256) + predicted type probs (40) = 296
        self.head_action = nn.Sequential(
            nn.Linear(296, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 4),
        )

    # ------------------------------------------------------------------
    def _encode_drug(self, graph, fp, desc):
        gnn_emb  = self.encoder(graph.x, graph.edge_index, graph.edge_attr, graph.batch)
        fp_emb   = self.fp_mlp(fp)
        desc_emb = self.desc_mlp(desc)
        return self.proj(torch.cat([gnn_emb, fp_emb, desc_emb], dim=-1))

    def forward(self, graphA, fpA, descA, graphB, fpB, descB):
        eA = self._encode_drug(graphA, fpA, descA)
        eB = self._encode_drug(graphB, fpB, descB)
        # Strictly symmetric pair representation [r1+r2, r1*r2, |r1-r2|] guaranteeing f(A,B) == f(B,A)
        pair = torch.cat([eA + eB, eA * eB, torch.abs(eA - eB)], dim=-1)   # (B, 768)
        h = self.trunk(pair)
        gate_logit = self.head_gate(h)
        type_logits = self.head_types(h)
        type_probs = torch.sigmoid(type_logits)
        # Clinical action head (v24)
        action_input = torch.cat([h, type_probs], dim=-1) # (B, 296)
        action_logits = self.head_action(action_input)
        return gate_logit, type_logits, action_logits

