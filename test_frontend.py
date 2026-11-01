with open("frontend/index.html", encoding="utf-8") as f:
    html = f.read()

ids = [
    "input-a", "input-b", "ac-a", "ac-b", "smiles-preview-a", "smiles-preview-b",
    "predict-btn", "predict-btn-text", "btn-spinner", "error-banner", "error-text",
    "results-section", "gate-card", "verdict-icon", "verdict-label", "verdict-sub",
    "ring-fill", "ring-label", "metric-calibrated",
    "metric-threshold", "metric-margin", "gate-expl-text", "pair-summary", "dataset-badge",
    "types-count", "types-list", "se-count", "se-list", "show-more-se",
    "mol-a-name", "mol-a-cid", "mol-a-smiles", "mol-a-svg",
    "mol-b-name", "mol-b-cid", "mol-b-smiles", "mol-b-svg",
    "gradcam-a-name", "gradcam-a-cid", "gradcam-a-svg", "gradcam-a-smiles",
    "gradcam-b-name", "gradcam-b-cid", "gradcam-b-svg", "gradcam-b-smiles",
    "shap-title-a", "shap-title-b", "shap-chart-a", "shap-chart-b",
    "desc-table-body", "attribution-disclosure-text",
    "tab-overview", "tab-explain", "tab-model",
    "pane-overview", "pane-explain", "pane-model",
    "reset-btn", "new-prediction-btn", "nav-back-btn"
]

missing = [i for i in ids if f'id="{i}"' not in html and f"id='{i}'" not in html]
print("Missing IDs:", missing)
assert len(missing) == 0, f"Found missing IDs: {missing}"
print("All IDs verified!")
