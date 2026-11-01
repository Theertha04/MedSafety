/* ═══════════════════════════════════════════════════════════
   InteractomeX – Frontend Application Logic
   ═══════════════════════════════════════════════════════════ */

'use strict';

// ─── State ────────────────────────────────────────────────
const state = {
  mode: 'name',           // 'name' | 'cid' | 'smiles'
  drugList: [],           // [{cid, name}] from /api/drugs
  seShowAll: false,
  lastResult: null,
  typeFilter: 'active',   // 'active' | 'high' | 'all'
  allTypesData: [],
};

// ─── DOM refs ─────────────────────────────────────────────
const $ = id => document.getElementById(id);

const inputA       = $('input-a');
const inputB       = $('input-b');
const acA          = $('ac-a');
const acB          = $('ac-b');
const previewA     = $('smiles-preview-a');
const previewB     = $('smiles-preview-b');
const predictBtn   = $('predict-btn');
const btnText      = $('predict-btn-text');
const btnSpinner   = $('btn-spinner');
const errorBanner  = $('error-banner');
const errorText    = $('error-text');
const resultsSection = $('results-section');

// ─── Init ─────────────────────────────────────────────────
setupAutocomplete(inputA, acA, 'a');
setupAutocomplete(inputB, acB, 'b');

(async function loadDrugList() {
  try {
    const res = await fetch('/api/drugs');
    if (res.ok) {
      const data = await res.json();
      state.drugList = data.drugs || [];
    }
  } catch (e) {
    console.warn('Could not load drug list:', e);
  }
})();

// ─── Input mode tabs ──────────────────────────────────────
// ─── Input mode tabs ──────────────────────────────────────
window.setMode = function(mode) {
  if (mode === 'cid') mode = 'name';
  state.mode = mode;
  ['name', 'smiles'].forEach(m => {
    const tab = $('tab-' + m);
    if (tab) {
      tab.classList.toggle('active', m === mode);
      tab.setAttribute('aria-selected', m === mode);
    }
  });

  const placeholders = {
    name:   ['e.g. Aspirin or CID 2244', 'e.g. Warfarin or CID 5467'],
    smiles: ['Paste SMILES string…', 'Paste SMILES string…'],
  };
  inputA.placeholder = placeholders[mode][0];
  inputB.placeholder = placeholders[mode][1];

  // Hide autocomplete and previews when switching modes
  clearAC(acA); clearAC(acB);
  previewA.hidden = true;
  previewB.hidden = true;
  if ($('cid-pill-a')) $('cid-pill-a').hidden = true;
  if ($('cid-pill-b')) $('cid-pill-b').hidden = true;
  if ($('meta-bar-a')) $('meta-bar-a').hidden = true;
  if ($('meta-bar-b')) $('meta-bar-b').hidden = true;
  inputA.value = ''; inputB.value = '';
};

// ─── Swap ────────────────────────────────────────────────
window.swapDrugs = function() {
  [inputA.value, inputB.value] = [inputB.value, inputA.value];

  const cidA = inputA.dataset.cid, cidB = inputB.dataset.cid;
  const smA = inputA.dataset.smiles, smB = inputB.dataset.smiles;
  if (cidB) inputA.dataset.cid = cidB; else delete inputA.dataset.cid;
  if (cidA) inputB.dataset.cid = cidA; else delete inputB.dataset.cid;
  if (smB) inputA.dataset.smiles = smB; else delete inputA.dataset.smiles;
  if (smA) inputB.dataset.smiles = smA; else delete inputB.dataset.smiles;

  [previewA.textContent, previewB.textContent] = [previewB.textContent, previewA.textContent];
  [previewA.hidden, previewB.hidden] = [previewB.hidden, previewA.hidden];

  const pillA = $('cid-pill-a'), pillB = $('cid-pill-b');
  if (pillA && pillB) {
    [pillA.textContent, pillB.textContent] = [pillB.textContent, pillA.textContent];
    [pillA.hidden, pillB.hidden] = [pillB.hidden, pillA.hidden];
  }
  const barA = $('meta-bar-a'), barB = $('meta-bar-b');
  if (barA && barB) {
    [barA.hidden, barB.hidden] = [barB.hidden, barA.hidden];
  }
};

// ─── Reset & Navigation (No browser refresh required) ────
window.clearInputs = function() {
  inputA.value = '';
  inputB.value = '';
  delete inputA.dataset.cid;
  delete inputA.dataset.smiles;
  delete inputB.dataset.cid;
  delete inputB.dataset.smiles;
  if (previewA) { previewA.textContent = ''; previewA.hidden = true; }
  if (previewB) { previewB.textContent = ''; previewB.hidden = true; }
  if ($('cid-pill-a')) { $('cid-pill-a').textContent = ''; $('cid-pill-a').hidden = true; }
  if ($('cid-pill-b')) { $('cid-pill-b').textContent = ''; $('cid-pill-b').hidden = true; }
  if ($('meta-bar-a')) $('meta-bar-a').hidden = true;
  if ($('meta-bar-b')) $('meta-bar-b').hidden = true;
  clearAC(acA);
  clearAC(acB);
  hideError();
  inputA.focus();
};

window.startNewPrediction = function() {
  window.clearInputs();
  resultsSection.hidden = true;
  state.lastResult = null;
  const inputCard = $('input-card');
  if (inputCard) {
    inputCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  setTimeout(() => inputA.focus(), 350);
};

window.scrollToInputs = function() {
  const inputCard = $('input-card');
  if (inputCard) {
    inputCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  setTimeout(() => inputA.focus(), 350);
};

// ─── Instant Chemical Dictionary (Zero-latency offline cache) ─
const KNOWN_DRUG_SMILES = {
  'aspirin': { cid: 'CID000002244', smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
  'warfarin': { cid: 'CID000005467', smiles: 'CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O' },
  'fentanyl': { cid: 'CID000003345', smiles: 'CCC(=O)N(c1ccccc1)C1CCN(CCc2ccccc2)CC1' },
  'betaine': { cid: 'CID000000247', smiles: 'C[N+](C)(C)CC(=O)[O-]' },
  'metformin': { cid: 'CID000004091', smiles: 'CN(C)C(=N)NC(=N)N' },
  'ibuprofen': { cid: 'CID000003672', smiles: 'CC(C)Cc1ccc(C(C)C(=O)O)cc1' },
  'paracetamol': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'acetaminophen': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'dolo': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'dolo 650': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'dolo-650': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'calpol': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'crocin': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'panadol': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'tylenol': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
  'disprin': { cid: 'CID000002244', smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
  'ecosprin': { cid: 'CID000002244', smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
  'advil': { cid: 'CID000003672', smiles: 'CC(C)Cc1ccc(C(C)C(=O)O)cc1' },
  'brufen': { cid: 'CID000003672', smiles: 'CC(C)Cc1ccc(C(C)C(=O)O)cc1' },
  'ampicillin': { cid: 'CID000002173', smiles: 'CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O' },
  'caffeine': { cid: 'CID000002519', smiles: 'CN1C=NC2=C1C(=O)N(C(=O)N2C)C' },
  'cid000002244': { cid: 'CID000002244', smiles: 'CC(=O)Oc1ccccc1C(=O)O' },
  'cid000005467': { cid: 'CID000005467', smiles: 'CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O' },
  'cid000003345': { cid: 'CID000003345', smiles: 'CCC(=O)N(c1ccccc1)C1CCN(CCc2ccccc2)CC1' },
  'cid000000247': { cid: 'CID000000247', smiles: 'C[N+](C)(C)CC(=O)[O-]' },
  'cid000001983': { cid: 'CID000001983', smiles: 'CC(=O)Nc1ccc(O)cc1' },
};

async function resolveAndShowSmiles(input, which, overrideCid = null) {
  const query = (input.value || '').trim();
  if (!query || state.mode === 'smiles') return;

  const prev = which === 'a' ? previewA : previewB;
  const pill = which === 'a' ? $('cid-pill-a') : $('cid-pill-b');
  const metaBar = which === 'a' ? $('meta-bar-a') : $('meta-bar-b');

  const qLower = query.toLowerCase();
  const cidLower = (overrideCid || input.dataset.cid || '').toLowerCase();

  // 1. Instant check from local dictionary
  const directMatch = KNOWN_DRUG_SMILES[qLower] || KNOWN_DRUG_SMILES[cidLower];
  if (directMatch) {
    input.dataset.cid = directMatch.cid;
    input.dataset.smiles = directMatch.smiles;
    if (pill) {
      pill.textContent = '🏷️ PubChem ' + directMatch.cid;
      pill.hidden = false;
    }
    if (prev) {
      prev.textContent = directMatch.smiles;
      prev.hidden = false;
    }
    if (metaBar) metaBar.hidden = false;
    return;
  }

  // 2. Show loading feedback
  if (metaBar) metaBar.hidden = false;
  if (prev) {
    prev.innerHTML = '<span style="color:var(--text-dim);">⏳ Fetching molecular SMILES…</span>';
    prev.hidden = false;
  }

  const lookupTarget = overrideCid || input.dataset.cid || query;

  // 3. Query backend /api/drug/{target}/smiles
  try {
    const res = await fetch(`/api/drug/${encodeURIComponent(lookupTarget)}/smiles`);
    if (res.ok) {
      const data = await res.json();
      if (data.smiles) {
        input.dataset.smiles = data.smiles;
        if (data.cid) input.dataset.cid = data.cid;
        if (pill && (data.cid || overrideCid)) {
          pill.textContent = '🏷️ PubChem ' + (data.cid || overrideCid);
          pill.hidden = false;
        }
        if (prev) {
          prev.textContent = data.smiles;
          prev.hidden = false;
        }
        return;
      }
    }
  } catch (_) { /* fallback below */ }

  // 4. Direct PubChem query fallback
  try {
    const isNumCid = lookupTarget.replace(/^cid0*/i, '').match(/^\d+$/);
    const pubchemUrl = isNumCid
      ? `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/${lookupTarget.replace(/^cid0*/i, '')}/property/CanonicalSMILES/JSON`
      : `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/${encodeURIComponent(lookupTarget)}/property/CanonicalSMILES,CID/JSON`;

    const res = await fetch(pubchemUrl);
    if (res.ok) {
      const d = await res.json();
      const props = d?.PropertyTable?.Properties?.[0] || {};
      const smiles = props.CanonicalSMILES || props.SMILES;
      const cidNum = props.CID ? `CID${String(props.CID).padStart(9, '0')}` : null;
      if (smiles) {
        input.dataset.smiles = smiles;
        if (cidNum) input.dataset.cid = cidNum;
        if (pill && (cidNum || overrideCid)) {
          pill.textContent = '🏷️ PubChem ' + (cidNum || overrideCid);
          pill.hidden = false;
        }
        if (prev) {
          prev.textContent = smiles;
          prev.hidden = false;
        }
        return;
      }
    }
  } catch (_) { /* ignore */ }

  // 5. Structure will resolve upon prediction submit
  if (prev) {
    prev.innerHTML = '<span style="color:var(--text-dim);font-style:italic;">Structure will resolve upon prediction</span>';
  }
}

function setupAutocomplete(input, box, which) {
  let acIndex = -1;
  let debounceTimer = null;
  let reqSeq = 0;

  async function updateSuggestions() {
    const q = input.value.trim();
    if (!q) { clearAC(box); return; }

    const currentSeq = ++reqSeq;
    const mode = state.mode;

    // In SMILES mode, autocomplete is disabled
    if (mode === 'smiles') { clearAC(box); return; }

    const qLower = q.toLowerCase();

    // 1. Instant local matching
    const prefix = [];
    const sub = [];
    for (const d of (state.drugList || [])) {
      if (!d.name && !d.cid) continue;
      const nl = (d.name || '').toLowerCase();
      const cl = (d.cid || '').toLowerCase();
      const shortCid = cl.replace(/^cid0*/, '');

      if (nl.startsWith(qLower) || cl.startsWith(qLower) || shortCid.startsWith(qLower)) {
        prefix.push(d);
      } else if (nl.includes(qLower) || cl.includes(qLower) || shortCid.includes(qLower)) {
        sub.push(d);
      }
    }
    const localMatches = prefix.concat(sub).slice(0, 10);
    if (localMatches.length > 0) {
      renderACItems(input, box, which, localMatches, q);
    }

    // 2. Query robust backend autocomplete endpoint (/api/autocomplete?q=...)
    try {
      const res = await fetch(`/api/autocomplete?q=${encodeURIComponent(q)}`);
      if (currentSeq !== reqSeq) return;
      if (res.ok) {
        const data = await res.json();
        const serverResults = data.results || [];
        if (serverResults.length > 0) {
          renderACItems(input, box, which, serverResults, q);
        } else if (localMatches.length === 0) {
          clearAC(box);
        }
      }
    } catch (_) {
      if (localMatches.length === 0) clearAC(box);
    }
  }

  function renderACItems(input, box, which, items, query) {
    box.innerHTML = '';
    acIndex = -1;
    items.forEach((drug, i) => {
      const item = document.createElement('div');
      item.className = 'ac-item';
      item.dataset.idx = i;
      const cidTag = drug.cid 
        ? `<div class="ac-cid">${drug.cid}</div>` 
        : `<div class="ac-cid" style="color:var(--indigo);">PubChem Verified</div>`;
      item.innerHTML = `<div>${highlight(drug.name || drug.cid, query)}</div>${cidTag}`;
      item.addEventListener('mousedown', e => {
        e.preventDefault();
        selectAC(input, box, which, drug);
      });
      box.appendChild(item);
    });
    box._matches = items;
  }

  input.addEventListener('input', () => {
    delete input.dataset.smiles;
    const prev = which === 'a' ? previewA : previewB;
    const pill = which === 'a' ? $('cid-pill-a') : $('cid-pill-b');
    const metaBar = which === 'a' ? $('meta-bar-a') : $('meta-bar-b');

    const qLower = input.value.trim().toLowerCase();
    if (KNOWN_DRUG_SMILES[qLower]) {
      resolveAndShowSmiles(input, which);
    } else {
      if (prev) prev.hidden = true;
      if (pill) pill.hidden = true;
      if (metaBar) metaBar.hidden = true;
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      updateSuggestions();
      if (input.value.trim().length >= 3 && !input.dataset.smiles) {
        resolveAndShowSmiles(input, which);
      }
    }, 120);
  });

  input.addEventListener('change', () => {
    if (input.value.trim()) {
      resolveAndShowSmiles(input, which);
    }
  });

  input.addEventListener('focus', () => {
    if (input.value.trim().length >= 1) {
      updateSuggestions();
    }
  });

  input.addEventListener('keydown', e => {
    const items = box.querySelectorAll('.ac-item');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      acIndex = Math.min(acIndex + 1, items.length - 1);
      updateFocus(items, acIndex);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      acIndex = Math.max(acIndex - 1, 0);
      updateFocus(items, acIndex);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (acIndex >= 0 && box._matches && box._matches[acIndex]) {
        selectAC(input, box, which, box._matches[acIndex]);
      } else {
        clearAC(box);
        resolveAndShowSmiles(input, which);
      }
    } else if (e.key === 'Escape') {
      clearAC(box);
    }
  });

  input.addEventListener('blur', () => {
    setTimeout(() => {
      clearAC(box);
      if (input.value.trim() && !input.dataset.smiles) {
        resolveAndShowSmiles(input, which);
      }
    }, 250);
  });

  // Close dropdown on click outside
  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !box.contains(e.target)) {
      clearAC(box);
    }
  });
}

function updateFocus(items, idx) {
  items.forEach((el, i) => el.classList.toggle('focused', i === idx));
}

function highlight(text, q) {
  const re = new RegExp(`(${escRe(q)})`, 'gi');
  return text.replace(re, '<strong>$1</strong>');
}

function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

async function selectAC(input, box, which, drug) {
  let val = drug.name || drug.cid || '';
  if (val.includes(' (')) {
    val = val.split(' (')[0].trim();
  }
  input.value = val;
  clearAC(box);
  if (drug.cid) input.dataset.cid = drug.cid;
  resolveAndShowSmiles(input, which, drug.cid);
}

function clearAC(box) { box.innerHTML = ''; }

// ─── Prediction ───────────────────────────────────────────
window.runPrediction = async function() {
  hideError();
  clearAC(acA);
  clearAC(acB);
  const mode = state.mode;

  // Build request body (automatically checks dataset membership in background)
  const body = {
    check_dataset: true,
  };

  if (mode === 'smiles') {
    const sa = inputA.value.trim();
    const sb = inputB.value.trim();
    if (!sa || !sb) { showError('Please enter SMILES for both drugs.'); return; }
    if (sa === sb) {
      showError('Drug A and Drug B have identical SMILES strings. DDI prediction requires two distinct compounds.');
      return;
    }
    body.smiles_a = sa;
    body.smiles_b = sb;

  } else {
    // Unified Drug Search: Name or PubChem CID
    const nameA = inputA.value.trim();
    const nameB = inputB.value.trim();

    if (!nameA) { showError('Please enter a Drug Name or PubChem CID for Drug A.'); return; }
    if (!nameB) { showError('Please enter a Drug Name or PubChem CID for Drug B.'); return; }

    const smA = inputA.dataset.smiles || null;
    const smB = inputB.dataset.smiles || null;
    const cidA = inputA.dataset.cid || null;
    const cidB = inputB.dataset.cid || null;

    // Duplicate checks
    if (nameA.toLowerCase() === nameB.toLowerCase()) {
      showError(`Drug A and Drug B are identical ("${nameA}"). DDI prediction requires two distinct compounds.`);
      return;
    }
    const numCidA = parseInt((cidA || '').replace(/\D/g, ''), 10);
    const numCidB = parseInt((cidB || '').replace(/\D/g, ''), 10);
    if ((numCidA && numCidB && numCidA === numCidB) || (cidA && cidB && cidA.toUpperCase() === cidB.toUpperCase())) {
      showError(`Drug A and Drug B correspond to the same compound (${nameA} & ${nameB} both map to CID ${numCidA || cidA}). DDI prediction requires two distinct compounds.`);
      return;
    }
    if (smA && smB && smA.trim() === smB.trim()) {
      showError(`Drug A and Drug B have identical chemical structures (${nameA} & ${nameB} share the same molecular SMILES). DDI prediction requires two distinct compounds.`);
      return;
    }

    body.name_a = nameA;
    body.name_b = nameB;
    if (cidA) body.cid_a = cidA;
    if (cidB) body.cid_b = cidB;
    if (smA) body.smiles_a = smA;
    if (smB) body.smiles_b = smB;
  }

  setLoading(true);

  try {
    const res = await fetch('/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Prediction failed');

    state.lastResult = data;
    renderResults(data);

  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
};

// ─── Result Tab Switching ─────────────────────────────────
window.switchResultTab = function(tabName) {
  const tabs = ['overview', 'explain', 'model'];
  tabs.forEach(t => {
    const btn = $('tab-' + t);
    const pane = $('pane-' + t);
    if (btn) btn.classList.toggle('active', t === tabName);
    if (pane) pane.hidden = (t !== tabName);
  });
};

// ─── Render results ───────────────────────────────────────
function renderResults(data) {
  resultsSection.hidden = false;
  resultsSection.classList.add('animate-in');

  // Sync resolved smiles & CIDs back to inputs meta-bars
  if (data.drug_a) {
    if (data.drug_a.smiles && previewA) {
      previewA.textContent = data.drug_a.smiles;
      previewA.hidden = false;
      inputA.dataset.smiles = data.drug_a.smiles;
    }
    if (data.drug_a.cid && $('cid-pill-a')) {
      $('cid-pill-a').textContent = '🏷️ PubChem ' + data.drug_a.cid;
      $('cid-pill-a').hidden = false;
      inputA.dataset.cid = data.drug_a.cid;
    }
    if ($('meta-bar-a')) $('meta-bar-a').hidden = false;
  }
  if (data.drug_b) {
    if (data.drug_b.smiles && previewB) {
      previewB.textContent = data.drug_b.smiles;
      previewB.hidden = false;
      inputB.dataset.smiles = data.drug_b.smiles;
    }
    if (data.drug_b.cid && $('cid-pill-b')) {
      $('cid-pill-b').textContent = '🏷️ PubChem ' + data.drug_b.cid;
      $('cid-pill-b').hidden = false;
      inputB.dataset.cid = data.drug_b.cid;
    }
    if ($('meta-bar-b')) $('meta-bar-b').hidden = false;
  }

  // Gate card
  const gate = data.gate_prob;
  const interacts = data.interacts;
  const thresh = data.gate_threshold !== undefined ? data.gate_threshold : 0.51;
  const gateCard = $('gate-card');
  gateCard.className = 'card gate-card animate-in ' + (interacts ? 'interacts' : 'no-interact');

  $('verdict-icon').textContent  = interacts ? '⚠️' : '✅';
  $('verdict-label').textContent = interacts ? 'Interaction Predicted' : 'No Significant Interaction';
  $('verdict-label').style.color = interacts ? '#f87171' : '#34d399';
  
  // Format score display - prevent misleading 100% certainty display
  let scoreText;
  if (gate >= 0.999) {
    scoreText = '>99.9%';
  } else if (gate >= 0.99) {
    scoreText = (gate * 100).toFixed(1) + '%';
  } else if (gate <= 0.001) {
    scoreText = '<0.1%';
  } else {
    scoreText = (gate * 100).toFixed(1) + '%';
  }

  // Short, clear explanation of the result for visible section
  if ($('verdict-sub')) {
    if (interacts) {
      $('verdict-sub').textContent = `Calibrated interaction probability (${scoreText}) meets or exceeds the decision cutoff (${thresh.toFixed(2)}), indicating significant pharmacological interaction potential between these compounds.`;
    } else {
      $('verdict-sub').textContent = `Calibrated interaction probability (${scoreText}) is below the decision cutoff (${thresh.toFixed(2)}). No significant adverse interaction detected under standard conditions.`;
    }
  }

  // Ring gauge
  const circumference = 2 * Math.PI * 42; // ≈ 264
  const offset = circumference * (1 - Math.min(gate, 0.99));
  const ringFill = $('ring-fill');
  ringFill.style.strokeDashoffset = offset;
  ringFill.style.stroke = interacts
    ? `hsl(${Math.round((1 - gate) * 120)}, 80%, 60%)`
    : '#34d399';
  $('ring-label').textContent = scoreText;
  $('ring-label').style.color = interacts ? '#f87171' : '#34d399';

  // Simple Indicator: Threshold status pill
  const threshPill = $('threshold-indicator-pill');
  if (threshPill) {
    if (interacts) {
      threshPill.className = 'indicator-pill threshold-pill-risk';
      if ($('threshold-indicator-icon')) $('threshold-indicator-icon').textContent = '⚠️';
      if ($('threshold-indicator-text')) $('threshold-indicator-text').textContent = 'Above Decision Cutoff (Interaction)';
    } else {
      threshPill.className = 'indicator-pill threshold-pill-safe';
      if ($('threshold-indicator-icon')) $('threshold-indicator-icon').textContent = '✓';
      if ($('threshold-indicator-text')) $('threshold-indicator-text').textContent = 'Below Decision Cutoff (Safe)';
    }
  }

  // Technical Details: Metrics Breakdown
  if ($('metric-raw-logit')) {
    const rawLogit = data.raw_logit !== undefined ? data.raw_logit : (Math.log(Math.max(gate, 1e-6) / (1 - Math.min(gate, 0.9999))));
    $('metric-raw-logit').textContent = (rawLogit >= 0 ? '+' : '') + rawLogit.toFixed(4);
  }
  if ($('metric-raw-sigmoid')) {
    const rawSig = data.raw_sigmoid !== undefined ? (data.raw_sigmoid * 100).toFixed(2) + '%' : scoreText;
    $('metric-raw-sigmoid').textContent = rawSig;
  }
  if ($('metric-calibrated')) {
    $('metric-calibrated').textContent = scoreText;
    $('metric-calibrated').style.color = interacts ? '#f87171' : '#34d399';
  }
  if ($('metric-calibrated-sub')) {
    const temp = data.gate_temperature !== undefined ? data.gate_temperature : 1.1231;
    $('metric-calibrated-sub').textContent = `T = ${temp.toFixed(4)}`;
  }
  if ($('metric-threshold')) {
    $('metric-threshold').textContent = thresh.toFixed(4);
  }
  if ($('metric-margin')) {
    const diffPct = (gate - thresh) * 100;
    const sign = diffPct >= 0 ? '+' : '';
    $('metric-margin').textContent = `${sign}${diffPct.toFixed(1)}%`;
    $('metric-margin').style.color = diffPct >= 0 ? '#f87171' : '#34d399';
    if ($('metric-margin-sub')) {
      $('metric-margin-sub').textContent = diffPct >= 0 ? 'Above Cutoff (Risk)' : 'Below Cutoff (Safe)';
    }
  }

  // Drug pair summary
  const nameA = (data.molecules?.drug_a?.name) || labelFor(data.drug_a);
  const nameB = (data.molecules?.drug_b?.name) || labelFor(data.drug_b);
  $('pair-summary').innerHTML = `
    <span class="drug-pill drug-pill-a">⬟ ${escHtml(nameA)}</span>
    <span style="color:var(--text-dim)">+</span>
    <span class="drug-pill drug-pill-b">⬟ ${escHtml(nameB)}</span>
  `;

  // Populate 2D Molecular structures directly under drug names in main result card
  if ($('mol-a-name')) $('mol-a-name').textContent = nameA;
  if ($('mol-b-name')) $('mol-b-name').textContent = nameB;
  if (data.molecules?.drug_a) {
    if ($('mol-a-cid')) $('mol-a-cid').textContent = data.molecules.drug_a.cid || 'Custom / Unindexed';
    if ($('mol-a-smiles')) $('mol-a-smiles').textContent = data.molecules.drug_a.smiles || '–';
    if ($('mol-a-svg')) $('mol-a-svg').innerHTML = data.molecules.drug_a.svg || '<div class="empty-state">2D Structure unavailable</div>';
  }
  if (data.molecules?.drug_b) {
    if ($('mol-b-cid')) $('mol-b-cid').textContent = data.molecules.drug_b.cid || 'Custom / Unindexed';
    if ($('mol-b-smiles')) $('mol-b-smiles').textContent = data.molecules.drug_b.smiles || '–';
    if ($('mol-b-svg')) $('mol-b-svg').innerHTML = data.molecules.drug_b.svg || '<div class="empty-state">2D Structure unavailable</div>';
  }

  // Calibration & Uncertainty explanation text in main card
  if ($('gate-expl-text')) {
    if (data.explanation && data.explanation.score_interpretation) {
      $('gate-expl-text').textContent = data.explanation.score_interpretation;
    } else {
      const diffPct = Math.abs((gate - thresh) * 100).toFixed(1);
      const sign = (gate >= thresh) ? '+' : '-';
      const comp = (gate >= thresh)
        ? `meets or exceeds the decision cutoff (${thresh.toFixed(2)}) by ${sign}${diffPct}%`
        : `falls below the decision cutoff (${thresh.toFixed(2)}) by ${sign}${diffPct}%`;
      $('gate-expl-text').textContent = `The calibrated interaction probability is ${scoreText}, which ${comp}. Neural network confidence reflects representation-space embedding similarity from Graph Attention and Morgan fingerprint representations. It should not be conflated with clinical certainty, physiological toxicity, or side-effect severity.`;
    }
  }

  // Dataset badge & Risk badge: Hidden from main card
  const badge = $('dataset-badge');
  if (badge) badge.hidden = true;
  const riskBadge = $('risk-badge');
  if (riskBadge) riskBadge.hidden = true;

  // Render Clinical Advice (v24)
  const actionCard = $('clinical-action-card');
  const actionBadge = $('clinical-action-badge');
  if (actionBadge) actionBadge.hidden = true;

  if (data.clinical_action && data.clinical_action.label) {
    const act = data.clinical_action;
    const tier = act.tier !== undefined ? act.tier : 0;
    const tierColors = ['#34d399', '#38bdf8', '#fbbf24', '#f87171'];

    // Actual predicted clinical action in plain, understandable language (strip "Class X:" prefix)
    const rawLabel = act.label || '';
    const actionLabel = rawLabel.replace(/^Class\s*\d+\s*:\s*/i, '').trim() || 'Clinical Action Available';

    // Plain-language clinical advice narratives focused entirely on administration, schedule, and dosing
    const ELABORATED_ADVICE = {
      0: "These medications can be safely prescribed together using standard dosages. No significant interaction was detected between their chemical properties, requiring no adjustments to dose or schedule.",
      1: "Administer these medications at separate times, at least 2 to 4 hours apart. Spacing the doses prevents absorption conflicts in the gastrointestinal tract and ensures both medications remain effective.",
      2: "Dose adjustment and regular clinical monitoring are advised during concurrent use. Lowering the maintenance dose and checking routine laboratory parameters helps minimize adverse interaction risks.",
      3: "Avoid co-administration of these two medications. Concomitant use carries a high risk of severe toxicity or adverse clinical outcomes. An alternative medication should be selected."
    };

    const explanation = ELABORATED_ADVICE[tier] || "Consult prescribing monographs and clinical reference compendia for specific co-administration protocols.";

    if (actionCard) {
      actionCard.hidden = false;
      if ($('action-tier-title')) {
        $('action-tier-title').textContent = actionLabel;
        $('action-tier-title').style.color = tierColors[tier] || '#f8fafc';
      }
      if ($('action-recommendation')) {
        $('action-recommendation').textContent = explanation;
      }
    }
  } else if (actionCard) {
    // Missing or invalid clinical action: display fallback rather than fabricating an answer
    actionCard.hidden = false;
    if ($('action-tier-title')) {
      $('action-tier-title').textContent = "Clinical Advice Unavailable";
      $('action-tier-title').style.color = "var(--text-muted)";
    }
    if ($('action-recommendation')) {
      $('action-recommendation').textContent = "The clinical prescribing classification model could not establish a definitive action tier for this compound combination. Please consult authoritative clinical pharmacology compendia and product monographs for specific co-prescribing guidance.";
    }
  }

  // Side-Effect Profile (render verified external sources or clean fallback notice)
  if ($('types-count')) $('types-count').textContent = '';
  renderSideEffectProfile(data);

  // Render Explainability & Structures Tab
  if (data.molecules) {
    renderExplainabilityTab(data);
  }

  // Ensure Overview tab is active
  switchResultTab('overview');

  // Scroll to results
  setTimeout(() => {
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 100);
}

function renderExplainabilityTab(data) {
  const molA = data.molecules.drug_a;
  const molB = data.molecules.drug_b;
  const nameA = molA.name || labelFor(data.drug_a);
  const nameB = molB.name || labelFor(data.drug_b);

  // 1. Grad-CAM Heatmaps
  if ($('gradcam-a-name')) $('gradcam-a-name').textContent = nameA;
  if ($('gradcam-a-cid'))  $('gradcam-a-cid').textContent = molA.cid || 'Custom / Unindexed';
  if ($('gradcam-a-smiles')) $('gradcam-a-smiles').textContent = molA.smiles || '–';

  if ($('gradcam-b-name')) $('gradcam-b-name').textContent = nameB;
  if ($('gradcam-b-cid'))  $('gradcam-b-cid').textContent = molB.cid || 'Custom / Unindexed';
  if ($('gradcam-b-smiles')) $('gradcam-b-smiles').textContent = molB.smiles || '–';

  if (data.xai && data.xai.gradcam) {
    const gc = data.xai.gradcam;
    if ($('gradcam-a-svg')) {
      $('gradcam-a-svg').innerHTML = gc.drug_a_svg || molA.svg || '<div class="empty-state">Grad-CAM unavailable</div>';
    }
    if ($('gradcam-b-svg')) {
      $('gradcam-b-svg').innerHTML = gc.drug_b_svg || molB.svg || '<div class="empty-state">Grad-CAM unavailable</div>';
    }
  } else {
    if ($('gradcam-a-svg')) $('gradcam-a-svg').innerHTML = molA.svg || '<div class="empty-state">Grad-CAM unavailable</div>';
    if ($('gradcam-b-svg')) $('gradcam-b-svg').innerHTML = molB.svg || '<div class="empty-state">Grad-CAM unavailable</div>';
  }

  // Initialize interactive touch & mouse slide/pan controls
  initHeatmapInteractivity('a');
  initHeatmapInteractivity('b');

  // 2. Canonical 2D Structure Reference
  $('mol-a-name').textContent = nameA;
  $('mol-a-cid').textContent = molA.cid || 'Custom / Unindexed';
  $('mol-a-smiles').textContent = molA.smiles || '–';
  $('mol-a-svg').innerHTML = molA.svg || '<div class="empty-state">2D Structure unavailable</div>';

  $('mol-b-name').textContent = nameB;
  $('mol-b-cid').textContent = molB.cid || 'Custom / Unindexed';
  $('mol-b-smiles').textContent = molB.smiles || '–';
  $('mol-b-svg').innerHTML = molB.svg || '<div class="empty-state">2D Structure unavailable</div>';

  // 3. SHAP Descriptor Attribution Waterfall Charts
  if (data.xai && data.xai.descriptor_shap) {
    const shap = data.xai.descriptor_shap;
    if ($('shap-title-a')) $('shap-title-a').textContent = `${nameA} — Descriptor SHAP`;
    if ($('shap-title-b')) $('shap-title-b').textContent = `${nameB} — Descriptor SHAP`;

    const renderShapChart = (items, targetId) => {
      const container = $(targetId);
      if (!container) return;
      if (!items || !items.length) {
        container.innerHTML = '<div class="empty-state">No SHAP attributions generated</div>';
        return;
      }
      // Group: all positive (green, promotes interaction) first, descending by magnitude
      // followed by all negative (red, suppresses interaction), descending by magnitude
      const pos = items.filter(d => (d.attribution || 0) >= 0).sort((a, b) => (b.attribution || 0) - (a.attribution || 0));
      const neg = items.filter(d => (d.attribution || 0) < 0).sort((a, b) => Math.abs(b.attribution || 0) - Math.abs(a.attribution || 0));
      const sorted = [...pos, ...neg];
      const maxAbs = Math.max(...sorted.map(d => Math.abs(d.attribution || 0)), 0.001);
      const rows = sorted.map((d, idx) => {
        const val = d.attribution || 0;
        const isPos = val >= 0;
        const pct = Math.min(100, Math.round((Math.abs(val) / maxAbs) * 100));
        const fillClass = isPos ? 'shap-bar-positive' : 'shap-bar-negative';
        const sign = isPos ? '+' : '';
        const isFirstNeg = !isPos && idx === pos.length && pos.length > 0;
        return `
          <div class="shap-bar-row ${isFirstNeg ? 'shap-separator' : ''}">
            <span class="shap-bar-label" title="${escHtml(d.name)}">${escHtml(d.name)}</span>
            <div class="shap-bar-track">
              <div class="shap-bar-fill ${fillClass}" style="width: ${Math.max(4, pct)}%;"></div>
            </div>
            <span class="shap-bar-value ${fillClass}">${sign}${val.toFixed(4)}</span>
          </div>
        `;
      });
      container.innerHTML = rows.join('');
    };

    renderShapChart(shap.drug_a, 'shap-chart-a');
    renderShapChart(shap.drug_b, 'shap-chart-b');
  }

  // 4. Morgan Fingerprint Bit Attribution Tables
  if (data.xai && data.xai.fingerprint_attribution) {
    const fp = data.xai.fingerprint_attribution;
    if ($('fp-title-a')) $('fp-title-a').textContent = `${nameA} — Top 20 Bit Drivers`;
    if ($('fp-title-b')) $('fp-title-b').textContent = `${nameB} — Top 20 Bit Drivers`;

    const renderFpTable = (bits, targetId) => {
      const container = $(targetId);
      if (!container) return;
      if (!bits || !bits.length) {
        container.innerHTML = '<div class="empty-state">No fingerprint bit attribution generated</div>';
        return;
      }
      const maxGrad = Math.max(...bits.map(b => b.abs_gradient || 0), 0.001);
      const rows = bits.map((b, idx) => {
        const pct = Math.min(100, Math.round(((b.abs_gradient || 0) / maxGrad) * 100));
        const isPromotes = b.direction === 'promotes';
        const fillClass = isPromotes ? 'fp-promotes' : 'fp-suppresses';
        const dirLabel = isPromotes ? 'Promotes (+)' : 'Suppresses (−)';
        const statusBadge = b.is_on
          ? '<span class="fp-bit-on">ON</span>'
          : '<span class="fp-bit-off">OFF</span>';

        return `
          <div class="fp-row">
            <span class="fp-rank">#${idx + 1}</span>
            <span class="fp-bit-id">Bit ${b.bit_index}</span>
            <span class="fp-status">${statusBadge}</span>
            <div class="fp-bar-track">
              <div class="fp-bar-fill ${fillClass}" style="width: ${Math.max(4, pct)}%;"></div>
            </div>
            <span class="fp-direction ${fillClass}">${dirLabel}</span>
            <span class="fp-grad-val">${(b.gradient || 0).toFixed(4)}</span>
          </div>
        `;
      });
      container.innerHTML = rows.join('');
    };

    renderFpTable(fp.drug_a, 'fp-table-a');
    renderFpTable(fp.drug_b, 'fp-table-b');
  }

  // 5. Descriptors Table (|A - B| differences, expandable)
  const descBody = $('desc-table-body');
  const descA = molA.descriptors || [];
  const descB = molB.descriptors || [];

  // Reset table expander state
  const wrap = $('desc-table-wrap');
  if (wrap && wrap.classList.contains('expanded')) {
    wrap.classList.remove('expanded');
    if ($('desc-expand-text')) $('desc-expand-text').textContent = 'Show All 12 Descriptors (Expanded View)';
    if ($('desc-expand-icon')) $('desc-expand-icon').textContent = '▼';
  }

  if (descA.length && descB.length) {
    const rows = descA.map((dA, i) => {
      const dB = descB[i] || { value: 0 };
      const diff = Math.abs(dA.value - dB.value);
      const isFloat = dA.value % 1 !== 0;
      const diffStr = isFloat ? diff.toFixed(2) : Math.round(diff);
      const isSecondary = i >= 4;
      return `
        <tr class="${isSecondary ? 'desc-row-secondary' : ''}">
          <td>
            <strong>${escHtml(dA.label)}</strong>
            <span style="display:block; font-size:0.7rem; color:var(--text-dim); font-family:sans-serif;">${escHtml(dA.tooltip)}</span>
          </td>
          <td>${dA.value} ${dA.unit}</td>
          <td>${dB.value} ${dA.unit}</td>
          <td><span class="desc-diff-pill">Δ ${diffStr}${dA.unit ? ' ' + dA.unit : ''}</span></td>
        </tr>
      `;
    });
    descBody.innerHTML = rows.join('');
  } else {
    descBody.innerHTML = '<tr><td colspan="4" style="text-align:center;">Descriptors unavailable for these inputs.</td></tr>';
  }

  // 6. Attribution notes
  if (data.explanation && data.explanation.attribution_note) {
    $('attribution-disclosure-text').textContent = data.explanation.attribution_note;
  }
}

window.toggleDescTable = function() {
  const wrap = $('desc-table-wrap');
  const text = $('desc-expand-text');
  const icon = $('desc-expand-icon');
  if (!wrap) return;

  const isExpanded = wrap.classList.toggle('expanded');
  if (text) {
    text.textContent = isExpanded
      ? 'Show Concise View (Top 4 Descriptors)'
      : 'Show All 12 Descriptors (Expanded View)';
  }
  if (icon) {
    icon.textContent = isExpanded ? '▲' : '▼';
  }
};

// ─── Interactive Grad-CAM Heatmap Pan, Pinch & Slide Controls ──
const heatmapState = {
  a: { scale: 1.0, panX: 0, panY: 0, isDragging: false, startX: 0, startY: 0, touchDist: 0 },
  b: { scale: 1.0, panX: 0, panY: 0, isDragging: false, startX: 0, startY: 0, touchDist: 0 }
};

function updateHeatmapTransform(drug, smooth = false) {
  const container = $(`gradcam-${drug}-svg`);
  if (!container) return;
  const svg = container.querySelector('svg');
  if (!svg) return;
  const s = heatmapState[drug];
  svg.style.transition = smooth ? 'transform 0.22s cubic-bezier(0.2, 0, 0, 1)' : 'none';
  svg.style.transform = `translate(${s.panX}px, ${s.panY}px) scale(${s.scale})`;
  svg.style.transformOrigin = 'center center';

  // Sync zoom slider & label
  const slider = $(`zoom-slider-${drug}`);
  if (slider) slider.value = s.scale.toFixed(2);
  const label = $(`zoom-val-${drug}`);
  if (label) label.textContent = `${Math.round(s.scale * 100)}%`;
}

window.onZoomSlider = function(drug, val) {
  const s = heatmapState[drug];
  if (!s) return;
  s.scale = Math.min(2.5, Math.max(0.5, parseFloat(val) || 1.0));
  updateHeatmapTransform(drug, false);
};

window.zoomHeatmap = function(drug, factor, reset = false) {
  const s = heatmapState[drug];
  if (!s) return;
  if (reset) {
    s.scale = 1.0;
    s.panX = 0;
    s.panY = 0;
  } else {
    s.scale = Math.min(2.5, Math.max(0.5, s.scale * factor));
  }
  updateHeatmapTransform(drug, true);
};

function initHeatmapInteractivity(drug) {
  const container = $(`gradcam-${drug}-svg`);
  if (!container) return;

  // Reset state for new molecule
  heatmapState[drug].scale = 1.0;
  heatmapState[drug].panX = 0;
  heatmapState[drug].panY = 0;
  heatmapState[drug].isDragging = false;
  updateHeatmapTransform(drug, false);

  if (container._interactiveInitialized) return;
  container._interactiveInitialized = true;
  const s = heatmapState[drug];

  // Mouse Drag / Slide Pan
  container.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    s.isDragging = true;
    s.startX = e.clientX - s.panX;
    s.startY = e.clientY - s.panY;
    container.classList.add('is-dragging');
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!s.isDragging) return;
    s.panX = e.clientX - s.startX;
    s.panY = e.clientY - s.startY;
    updateHeatmapTransform(drug, false);
  });

  window.addEventListener('mouseup', () => {
    if (s.isDragging) {
      s.isDragging = false;
      container.classList.remove('is-dragging');
    }
  });

  // Touch Drag & Pinch ("in-touch grad slide")
  container.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      s.isDragging = true;
      s.startX = e.touches[0].clientX - s.panX;
      s.startY = e.touches[0].clientY - s.panY;
      container.classList.add('is-dragging');
    } else if (e.touches.length === 2) {
      s.isDragging = false;
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      s.touchDist = Math.hypot(dx, dy);
    }
  }, { passive: false });

  container.addEventListener('touchmove', (e) => {
    if (e.touches.length === 1 && s.isDragging) {
      e.preventDefault();
      s.panX = e.touches[0].clientX - s.startX;
      s.panY = e.touches[0].clientY - s.startY;
      updateHeatmapTransform(drug, false);
    } else if (e.touches.length === 2 && s.touchDist > 0) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      const factor = dist / s.touchDist;
      s.scale = Math.min(2.5, Math.max(0.5, s.scale * factor));
      s.touchDist = dist;
      updateHeatmapTransform(drug, false);
    }
  }, { passive: false });

  container.addEventListener('touchend', () => {
    s.isDragging = false;
    s.touchDist = 0;
    container.classList.remove('is-dragging');
  });

  // Mouse Wheel Zoom
  container.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    s.scale = Math.min(2.5, Math.max(0.5, s.scale * factor));
    updateHeatmapTransform(drug, false);
  }, { passive: false });

  // Double Click Reset
  container.addEventListener('dblclick', () => {
    window.zoomHeatmap(drug, 1.0, true);
  });
}



// ─── Interaction Types: Risk Tiers & Clinical Mechanisms ──
function getMechanismCategory(name) {
  const n = (name || '').toLowerCase();
  if (n.includes('metabolism') || n.includes('metabolite')) return { icon: '🧪', label: 'Metabolic Pathway' };
  if (n.includes('serum concentration') || n.includes('bioavailability')) return { icon: '📈', label: 'Serum Exposure / AUC' };
  if (n.includes('anticoagulant') || n.includes('bleeding') || n.includes('hemorrhage')) return { icon: '🩸', label: 'Hemostasis & Clotting' };
  if (n.includes('therapeutic efficacy') || n.includes('effect')) return { icon: '⚡', label: 'Efficacy Modulation' };
  if (n.includes('excretion') || n.includes('elimination') || n.includes('renal')) return { icon: '🫘', label: 'Renal Clearance' };
  if (n.includes('absorption')) return { icon: '💊', label: 'GI Absorption' };
  if (n.includes('adverse') || n.includes('severity')) return { icon: '⚠️', label: 'Synergistic Toxicity' };
  if (n.includes('hypertens') || n.includes('hypotens') || n.includes('cardio') || n.includes('qt')) return { icon: '💓', label: 'Cardiovascular' };
  if (n.includes('sedat') || n.includes('depress') || n.includes('cns')) return { icon: '🧠', label: 'Central Nervous System' };
  return { icon: '🔬', label: 'Pharmacodynamic Mechanism' };
}

function getRiskTier(t) {
  if (!t.is_active) {
    return {
      tier: 'sub',
      borderClass: 'tier-border-sub',
      badgeClass: 'tier-sub',
      icon: '⚪',
      label: 'Sub-threshold'
    };
  }
  if (t.relative_margin >= 0.15) {
    return {
      tier: 'high',
      borderClass: 'tier-border-high',
      badgeClass: 'tier-high',
      icon: '🔴',
      label: 'High Risk Affinity'
    };
  }
  if (t.relative_margin >= 0.05) {
    return {
      tier: 'mod',
      borderClass: 'tier-border-mod',
      badgeClass: 'tier-mod',
      icon: '🟡',
      label: 'Moderate Affinity'
    };
  }
  return {
    tier: 'low',
    borderClass: 'tier-border-low',
    badgeClass: 'tier-low',
    icon: '🔵',
    label: 'Borderline Affinity'
  };
}

function renderSideEffectProfile(data) {
  const typesList = $('types-list');
  if (!typesList) return;

  let effects = [];

  if (data) {
    if (Array.isArray(data.verified_adverse_effects) && data.verified_adverse_effects.length > 0) {
      effects = data.verified_adverse_effects.map(item => ({
        name: item.name || 'Adverse Effect',
        explanation: item.explanation || item.clinical_explanation || ''
      }));
    } else if (Array.isArray(data.external_side_effects) && data.external_side_effects.length > 0) {
      effects = data.external_side_effects.map(item => ({
        name: item.name || 'Adverse Effect',
        explanation: item.explanation || item.clinical_explanation || ''
      }));
    } else if (data.interacts !== false && Array.isArray(data.active_interaction_types)) {
      // Exclude generic mild symptoms (nausea, diarrhea, fever, vomiting, fatigue, headache)
      const MILD_SYMPTOMS = ['nausea', 'vomiting', 'diarrhea', 'diarrhoea', 'fever', 'pyrexia', 'fatigue', 'headache', 'body temperature'];
      const isMild = (name) => {
        const lower = (name || '').toLowerCase();
        return MILD_SYMPTOMS.some(m => lower.includes(m));
      };

      const active = data.active_interaction_types.filter(t => t.is_active && !isMild(t.name));
      // Prioritize High-Risk effects; if none, show clinically significant active effects (e.g. Severe Hypotension, Anaemia, Thrombocytopenia)
      const highRisk = active.filter(t => t.severity_tier === 'High');
      const candidateList = highRisk.length > 0 ? highRisk : active;

      const seen = new Set();
      const selected = [];

      for (const t of candidateList) {
        if (!seen.has(t.name)) {
          seen.add(t.name);
          selected.push({
            name: t.name || 'Adverse Effect',
            explanation: t.clinical_explanation || t.explanation || '',
            severity: t.severity_tier || 'Moderate'
          });
        }
      }

      effects = selected;
    }
  }

  if (effects.length > 0) {
    typesList.innerHTML = `
      <div class="verified-effects-list">
        ${effects.map(item => `
          <div class="verified-effect-row">
            <div class="verified-effect-name">${escHtml(item.name)}</div>
            ${item.explanation ? `<div class="verified-effect-desc">${escHtml(item.explanation)}</div>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  } else {
    // If no adverse effects are available or active for this combination, display the notice
    typesList.innerHTML = `
      <div class="side-effects-notice">
        <span class="notice-icon">ℹ️</span>
        <span>No specific adverse effects are available to display for this drug combination.</span>
      </div>
    `;
  }
}

function renderInteractionTypes() {
  if (state.lastResult) renderSideEffectProfile(state.lastResult);
}

window.setTypeFilter = function() {};
window.toggleSubthresholdTypes = function() {};
// ─── Explainable Side Effects Knowledge Base ──────────────
const SE_KNOWLEDGE_BASE = {
  'orthostatic hypotension': {
    system: '🫀 Cardiovascular',
    mechanism: 'Additive vasodilation or blunted baroreceptor reflex causing abrupt blood pressure drop upon standing.',
    guidance: 'Advise gradual posture changes; monitor supine and standing BP.'
  },
  'cardiac failure': {
    system: '🫀 Cardiovascular',
    mechanism: 'Synergistic negative inotropic depression or fluid retention overloading left ventricular function.',
    guidance: 'Monitor for peripheral edema, dyspnea, and sudden weight gain.'
  },
  'atrial fibrillation': {
    system: '🫀 Cardiovascular',
    mechanism: 'Heterogeneous myocardial repolarization or heightened autonomic sympathetic instability.',
    guidance: 'Perform baseline ECG; monitor pulse regularity and palpitations.'
  },
  'bradycardia': {
    system: '🫀 Cardiovascular',
    mechanism: 'Additive sinoatrial (SA) or atrioventricular (AV) node conduction slowing.',
    guidance: 'Monitor resting heart rate; caution with concurrent beta/calcium channel blockers.'
  },
  'thrombophlebitis': {
    system: '🫀 Vascular System',
    mechanism: 'Endothelial venous inflammation and altered microvascular blood stasis.',
    guidance: 'Inspect intravenous access sites; check for local erythema or localized pain.'
  },
  'vasculitis': {
    system: '🫀 Vascular System',
    mechanism: 'Immune complex deposition inducing vascular wall inflammation and permeability.',
    guidance: 'Monitor for cutaneous purpura, hematuria, or systemic fever.'
  },
  'vascular purpura': {
    system: '🩸 Hematologic',
    mechanism: 'Capillary fragility and microvascular leakage due to endothelial or platelet impairment.',
    guidance: 'Inspect skin and mucous membranes for petechiae and ecchymosis.'
  },
  'ecchymosis': {
    system: '🩸 Hematologic',
    mechanism: 'Synergistic platelet inhibition or clotting cascade suppression leading to subcutaneous extravasation.',
    guidance: 'Monitor bleeding time; caution with concurrent anticoagulants or NSAIDs.'
  },
  'neutropenia': {
    system: '🩸 Hematologic',
    mechanism: 'Suppression of bone marrow granulopoiesis or accelerated peripheral neutrophil destruction.',
    guidance: 'Order periodic CBC with differential; report early signs of fever immediately.'
  },
  'hepatocellular injury': {
    system: '🫘 Hepatic & Liver',
    mechanism: 'Accumulation of reactive toxic metabolites inducing hepatocyte membrane disruption and cytolysis.',
    guidance: 'Monitor serum transaminases (ALT/AST); watch for jaundice, dark urine, or fatigue.'
  },
  'hepatic function abnormal': {
    system: '🫘 Hepatic & Liver',
    mechanism: 'Impaired hepatic clearance or competitive cytochrome P450 overload.',
    guidance: 'Evaluate baseline liver panel; consider dose titration of hepatically cleared agents.'
  },
  'liver function test abnormal': {
    system: '🫘 Hepatic & Liver',
    mechanism: 'Elevations in ALT, AST, or bilirubin secondary to combined hepatic drug load.',
    guidance: 'Schedule follow-up LFT panel; withhold if transaminases exceed 3x upper limit of normal.'
  },
  'hepatitis': {
    system: '🫘 Hepatic & Liver',
    mechanism: 'Drug-induced immune or toxic inflammatory response across hepatic parenchyma.',
    guidance: 'Immediate clinical evaluation if right upper quadrant abdominal tenderness occurs.'
  },
  'blood alkaline phosphatase increased': {
    system: '🫘 Hepatic / Biliary',
    mechanism: 'Canalicular membrane irritation or early intrahepatic cholestatic outflow resistance.',
    guidance: 'Assess GGT and bilirubin to differentiate biliary from bone origin.'
  },
  'renal failure acute': {
    system: '🫘 Renal & Excretion',
    mechanism: 'Renal vasoconstriction, tubulotoxicity, or altered intraglomerular hemodynamics.',
    guidance: 'Track serum creatinine, eGFR, and hourly urine output; ensure hydration.'
  },
  'polyuria': {
    system: '🫘 Renal & Excretion',
    mechanism: 'Impaired renal tubular reabsorption or osmotic diuresis affecting fluid homeostasis.',
    guidance: 'Check electrolyte panel (sodium/potassium) and maintain fluid balance.'
  },
  'fluid retention': {
    system: '🫘 Renal & Fluid Dynamics',
    mechanism: 'Secondary sodium reabsorption in renal distal tubules or arteriolar vasodilation.',
    guidance: 'Examine for pretibial edema and rapid changes in daily weight.'
  },
  'convulsion': {
    system: '🧠 Neurological',
    mechanism: 'Lowered seizure threshold via GABA-ergic antagonism or excessive central excitability.',
    guidance: 'Avoid in seizure-prone individuals; monitor for pre-ictal aura or muscle twitching.'
  },
  'disorientation': {
    system: '🧠 Neurological & Cognitive',
    mechanism: 'Central cholinergic blockade or synergistic blood-brain barrier penetration.',
    guidance: 'Evaluate mental status orientation (time/place); avoid heavy machinery operation.'
  },
  'coma': {
    system: '🧠 Neurological & Cognitive',
    mechanism: 'Severe profound multi-agent central nervous system depression of the reticular activating system.',
    guidance: 'Critical emergency warning: avoid combining high-dose CNS depressants or sedatives.'
  },
  'lethargy': {
    system: '🧠 Neurological & Cognitive',
    mechanism: 'Additive central sedative burden blunting cortical alertness and neuromuscular tone.',
    guidance: 'Assess daytime sleepiness; consider evening dosing schedule if applicable.'
  },
  'sleep disorder': {
    system: '🧠 Neurological',
    mechanism: 'Disruption of circadian REM/non-REM sleep architecture or monoamine receptor stimulation.',
    guidance: 'Avoid evening administration; evaluate sleep hygiene and daytime fatigue.'
  },
  'depression': {
    system: '🧠 Psychological',
    mechanism: 'Modulation of central monoaminergic neurotransmission (serotonin/norepinephrine depletion).',
    guidance: 'Screen for mood shifts, anhedonia, or emotional blunting.'
  },
  'irritability': {
    system: '🧠 Psychological',
    mechanism: 'Central sympathomimetic or neuro-endocrine receptor disinhibition.',
    guidance: 'Evaluate dose-timing; reduce stimulants or interacting neuro-active substances.'
  },
  'tension': {
    system: '🧠 Psychological',
    mechanism: 'Autonomic nervous system arousal and generalized peripheral vasoconstrictive tone.',
    guidance: 'Assess psychomotor agitation and resting vital signs.'
  },
  'photophobia': {
    system: '👁️ Sensory / Ophthalmic',
    mechanism: 'Anticholinergic pupillary dilation (mydriasis) impairing normal light constriction reflexes.',
    guidance: 'Advise protective sunglasses in bright outdoor environments.'
  },
  'hearing impaired': {
    system: '👂 Sensory / Otic',
    mechanism: 'Cochlear hair cell outer membrane injury or altered endolymph electrolyte balance.',
    guidance: 'Report new-onset tinnitus or ear fullness promptly to prevent irreversible ototoxicity.'
  },
  'bronchospasm': {
    system: '🫁 Pulmonary / Airway',
    mechanism: 'Bronchial smooth muscle constriction via beta-2 receptor blockade or leukotriene pathway shunting.',
    guidance: 'Extreme caution in asthma/COPD; have rescue bronchodilators available.'
  },
  'upper respiratory tract infection': {
    system: '🫁 Pulmonary / Airway',
    mechanism: 'Mucosal barrier alterations or mild transient immunosuppressive modulation.',
    guidance: 'Monitor for rhinorrhea, sore throat, and persistent fevers.'
  },
  'nasal congestion': {
    system: '🫁 Pulmonary / Airway',
    mechanism: 'Local venous sinusoidal engorgement from peripheral alpha-adrenergic blockade.',
    guidance: 'Consider saline irrigation; avoid overusing rebound-causing decongestants.'
  },
  'oropharyngeal pain': {
    system: '🫁 Upper Airway',
    mechanism: 'Local mucosal tissue irritation or xerostomia-induced mucosal vulnerability.',
    guidance: 'Encourage frequent hydration; assess for secondary candidiasis or ulcerations.'
  },
  'abdominal discomfort': {
    system: '🍽️ Gastrointestinal',
    mechanism: 'Direct gastric epithelial irritation or prostaglandin synthesis inhibition reducing mucosal protection.',
    guidance: 'Administer with meals; consider co-prescription of gastroprotective agents (PPIs).'
  },
  'abdominal distension': {
    system: '🍽️ Gastrointestinal',
    mechanism: 'Delayed gastric emptying and impaired smooth muscle intestinal transit.',
    guidance: 'Monitor bowel frequency; promote dietary fiber and adequate ambulation.'
  },
  'salivary hypersecretion': {
    system: '🍽️ Gastrointestinal',
    mechanism: 'Parasympathetic cholinergic hyperstimulation of submandibular and parotid glands.',
    guidance: 'Monitor airway protection in sedated patients; report swallowing difficulties.'
  },
  'angioedema': {
    system: '🛡️ Immunologic / Allergic',
    mechanism: 'Bradykinin accumulation or mast-cell histamine release triggering submucosal swelling.',
    guidance: 'Emergency precaution: seek immediate medical care if lip, tongue, or airway swelling develops.'
  },
  'anaphylactoid reaction': {
    system: '🛡️ Immunologic / Allergic',
    mechanism: 'Non-IgE mediated direct degranulation of basophils and mast cells with systemic vasoactive release.',
    guidance: 'Keep emergency epinephrine and antihistamines readily accessible.'
  },
  'erythema': {
    system: '🧴 Dermatologic',
    mechanism: 'Cutaneous microvascular dilatation and inflammatory cytokine extravasation.',
    guidance: 'Inspect skin for expanding rash; distinguish benign flushing from hypersensitivity.'
  },
  'dermatitis contact': {
    system: '🧴 Dermatologic',
    mechanism: 'Type IV delayed cell-mediated immune hypersensitivity within epidermal keratinocytes.',
    guidance: 'Identify localized triggering agents; topical emollients may relieve symptoms.'
  },
  'dermatitis exfoliative': {
    system: '🧴 Dermatologic',
    mechanism: 'Widespread epidermal shedding and cutaneous barrier failure from toxic erythema.',
    guidance: 'Urgent dermatological assessment required; monitor fluid and electrolyte loss.'
  },
  'dermatitis bullous': {
    system: '🧴 Dermatologic',
    mechanism: 'Autoimmune epidermal-dermal detachment with subepithelial blister and bullae formation.',
    guidance: 'Immediately discontinue offending agents; evaluate for Stevens-Johnson syndrome.'
  },
  'alopecia': {
    system: '🧴 Dermatologic',
    mechanism: 'Disruption of rapidly dividing hair follicle matrix cells during anagen growth phase.',
    guidance: 'Reassure patient that hair thinning is typically reversible upon discontinuation.'
  },
  'hypoglycaemia': {
    system: '🧪 Metabolic & Endocrine',
    mechanism: 'Potentiated pancreatic insulin secretion or blunted hepatic gluconeogenesis recovery.',
    guidance: 'Monitor blood glucose regularly; carry fast-acting carbohydrates (glucose tablets).'
  },
  'blood uric acid increased': {
    system: '🧪 Metabolic & Renal',
    mechanism: 'Competitive inhibition of organic anion transporters reducing renal urate clearance.',
    guidance: 'Ensure liberal fluid intake; monitor for acute podagra or gout flare-ups.'
  },
  'gynaecomastia': {
    system: '🧪 Endocrine',
    mechanism: 'Altered estrogen-to-androgen balance via peripheral androgen receptor blockade.',
    guidance: 'Examine for breast tissue tenderness; review endocrine medications.'
  },
  'flushing': {
    system: '🫀 Vascular / Vasomotor',
    mechanism: 'Cutaneous vasodilation of facial and neck capillary beds via prostaglandin/histamine release.',
    guidance: 'Benign vasomotor reaction; avoid concurrent alcohol or hot liquids.'
  },
  'hot flush': {
    system: '🫀 Vascular / Thermoregulatory',
    mechanism: 'Hypothalamic thermoregulatory center reset inducing episodic peripheral vasodilation.',
    guidance: 'Wear layered clothing; discuss thermoregulatory stabilizers if disruptive.'
  },
  'chills': {
    system: '🌡️ Thermoregulatory',
    mechanism: 'Involuntary shivering response triggered by acute hypothalamic set-point elevation.',
    guidance: 'Take body temperature to rule out concurrent pyrogenic infection.'
  },
  'injury': {
    system: '⚠️ Clinical Event',
    mechanism: 'Secondary physical trauma or falls resulting from interaction-induced dizziness, ataxia, or hypotension.',
    guidance: 'Implement fall precautions in elderly patients; review ambulation safety.'
  },
  'vasodilation procedure': {
    system: '🫀 Vascular Procedure',
    mechanism: 'Surrogate medical coding marker indicating clinical requirement for vasodilator interventions.',
    guidance: 'Evaluate overall cardiovascular hemodynamics and anti-hypertensive regimen.'
  }
};

function formatSEName(s) {
  if (!s) return '';
  return s.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
}

function renderSE(effects, showAll) {
  if (!effects || !effects.length) {
    $('se-count').textContent = '0';
    $('se-list').innerHTML = '<div class="empty-state">No adverse reactions predicted.</div>';
    $('show-more-se').hidden = true;
    return;
  }

  // Top 5 most prominent signals
  const topSignals = effects.slice(0, 5);
  const remainingSignals = effects.slice(5);
  $('se-count').textContent = `${topSignals.length} top signals / ${effects.length} total`;

  const topCardsHtml = topSignals.map(se => {
    const rawKey = (se.name || '').toLowerCase().trim();
    const info = SE_KNOWLEDGE_BASE[rawKey] || {
      system: '💊 Pharmacological Effect',
      mechanism: 'Drug-drug interaction metabolic or target pathway cross-reactivity.',
      guidance: 'Monitor patient tolerance and report persistent discomfort.'
    };
    const probPct = (se.prob * 100).toFixed(1);
    const signalTier = se.prob >= 0.35 ? 'signal-high' : (se.prob >= 0.20 ? 'signal-mod' : 'signal-low');
    const signalLabel = se.prob >= 0.35 ? '🔴 High Signal' : (se.prob >= 0.20 ? '🟡 Moderate Signal' : '🟢 Elevated Signal');

    return `
      <div class="se-explain-card ${signalTier}">
        <div class="se-card-header">
          <span class="se-system-tag">${info.system}</span>
          <span class="se-signal-badge ${signalTier}">${signalLabel} (${probPct}%)</span>
        </div>
        <div class="se-title">${escHtml(formatSEName(se.name))}</div>
        <div class="se-mechanism-text"><strong>Mechanism:</strong> ${escHtml(info.mechanism)}</div>
        <div class="se-guidance-box">
          <span>💡</span>
          <span><strong>Precaution:</strong> ${escHtml(info.guidance)}</span>
        </div>
      </div>
    `;
  }).join('');

  let secondaryHtml = '';
  if (showAll && remainingSignals.length > 0) {
    secondaryHtml = `
      <div class="se-secondary-wrap">
        <div class="se-secondary-title">All Secondary Adverse Reaction Heads (${remainingSignals.length} Remaining)</div>
        <div class="se-secondary-grid">
          ${remainingSignals.map(se => `
            <div class="se-pill-item">
              <span>${escHtml(formatSEName(se.name))}</span>
              <span class="se-prob">${(se.prob * 100).toFixed(1)}%</span>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  $('se-list').innerHTML = topCardsHtml + secondaryHtml;

  const showMoreBtn = $('show-more-se');
  if (effects.length > 5) {
    showMoreBtn.hidden = false;
    showMoreBtn.textContent = showAll 
      ? '▲ Collapse to Top Signaled Only' 
      : `▼ Show Full 50-Head Spectrum (Remaining ${remainingSignals.length})`;
  } else {
    showMoreBtn.hidden = true;
  }
}

window.setSEView = function(view) {
  state.seView = view || 'joint';
  ['joint', 'a', 'b'].forEach(v => {
    const btn = $(`se-tab-${v}`);
    if (btn) btn.classList.toggle('active', v === state.seView);
  });
  if (!state.lastResult) return;
  let effects = state.lastResult.predicted_side_effects;
  if (state.seView === 'a' && state.lastResult.drug_a_side_effects) {
    effects = state.lastResult.drug_a_side_effects;
  } else if (state.seView === 'b' && state.lastResult.drug_b_side_effects) {
    effects = state.lastResult.drug_b_side_effects;
  }
  renderSE(effects, state.seShowAll);
};

window.toggleSE = function() {
  state.seShowAll = !state.seShowAll;
  if (state.lastResult) {
    let effects = state.lastResult.predicted_side_effects;
    if (state.seView === 'a' && state.lastResult.drug_a_side_effects) {
      effects = state.lastResult.drug_a_side_effects;
    } else if (state.seView === 'b' && state.lastResult.drug_b_side_effects) {
      effects = state.lastResult.drug_b_side_effects;
    }
    renderSE(effects, state.seShowAll);
  }
};

// ─── Helpers ──────────────────────────────────────────────
function labelFor(drug) {
  if (!drug) return 'Unknown';
  if (drug.name) return drug.name;
  if (drug.cid) {
    const found = state.drugList.find(d => d.cid === drug.cid);
    if (found?.name) return found.name;
    return drug.cid;
  }
  return drug.smiles ? drug.smiles.slice(0, 30) + '…' : 'Unknown';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function setLoading(on) {
  predictBtn.disabled = on;
  btnText.textContent  = on ? 'Predicting…' : 'Predict Interaction';
  btnSpinner.hidden    = !on;
}

function showError(msg) {
  errorText.textContent = msg;
  errorBanner.hidden = false;
}

window.hideError = function() { errorBanner.hidden = true; };

// ─── Report Download & Export ─────────────────────────────
window.toggleReportMenu = function(e) {
  if (e) e.stopPropagation();
  const dropdown = $('report-dropdown');
  const btn = $('download-report-btn');
  const caret = $('report-caret');
  if (!dropdown) return;
  const isHidden = dropdown.hidden;
  dropdown.hidden = !isHidden;
  if (btn) btn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
  if (caret) caret.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
};

document.addEventListener('click', (e) => {
  const group = $('report-download-group');
  const dropdown = $('report-dropdown');
  const caret = $('report-caret');
  const btn = $('download-report-btn');
  if (dropdown && !dropdown.hidden && group && !group.contains(e.target)) {
    dropdown.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
    if (caret) caret.style.transform = 'rotate(0deg)';
  }
});

function downloadBlob(content, filename, contentType) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

window.downloadReport = function(format = 'html') {
  const data = state.lastResult;
  if (!data) {
    showError('No prediction result available to download. Please run a prediction first.');
    return;
  }

  const nameA = labelFor(data.drug_a) || 'Drug_A';
  const nameB = labelFor(data.drug_b) || 'Drug_B';
  const safeA = nameA.replace(/[^a-zA-Z0-9_-]/g, '_');
  const safeB = nameB.replace(/[^a-zA-Z0-9_-]/g, '_');
  const dateStr = new Date().toISOString().slice(0, 10);

  if (format === 'json') {
    const jsonStr = JSON.stringify(data, null, 2);
    downloadBlob(jsonStr, `InteractomeX_${safeA}_${safeB}_${dateStr}.json`, 'application/json');
    return;
  }

  if (format === 'md') {
    const md = generateMarkdownReport(data, nameA, nameB);
    downloadBlob(md, `InteractomeX_${safeA}_${safeB}_${dateStr}.md`, 'text/markdown;charset=utf-8');
    return;
  }

  // Default: Clinical Report (.html / PDF)
  const html = generateHtmlReport(data, nameA, nameB);
  const filename = `InteractomeX_Clinical_Report_${safeA}_${safeB}_${dateStr}.html`;

  // Trigger file download
  downloadBlob(html, filename, 'text/html;charset=utf-8');

  // Also open directly in a new tab for instant view & PDF print
  try {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
  } catch (err) {
    console.log('Opened report via direct download:', err);
  }
};

function generateMarkdownReport(data, nameA, nameB) {
  const dateStr = new Date().toLocaleString();
  const interacts = data.interacts;
  const gatePct = (data.gate_prob * 100).toFixed(1);
  const thresholdPct = ((data.gate_threshold || 0.48) * 100).toFixed(1);

  let datasetStatus = 'Not checked';
  if (data.in_dataset === true) datasetStatus = 'Confirmed: Pair appears in benchmark training dataset';
  else if (data.in_dataset === false) datasetStatus = 'Novel Pair: Not found in training dataset (Generalised Inference)';

  const types = data.active_interaction_types || [];
  const MILD_SYMPTOMS = ['nausea', 'vomiting', 'diarrhea', 'diarrhoea', 'fever', 'pyrexia', 'fatigue', 'headache', 'body temperature'];
  const isMild = (name) => {
    const lower = (name || '').toLowerCase();
    return MILD_SYMPTOMS.some(m => lower.includes(m));
  };
  const activeSignificant = types.filter(t => t.is_active && !isMild(t.name));
  const highRiskOnly = activeSignificant.filter(t => t.severity_tier === 'High');
  const highRiskTypes = highRiskOnly.length > 0 ? highRiskOnly : activeSignificant;
  const molA = data.molecules?.drug_a;
  const molB = data.molecules?.drug_b;

  const act = data.clinical_action || {};
  const rawLabel = act.label || '';
  const actionLabel = rawLabel.replace(/^Class\s*\d+\s*:\s*/i, '').trim() || (interacts ? 'Clinical Review Recommended' : 'Safe Concomitant Use');
  const ELABORATED_ADVICE = {
    0: "These medications can be safely prescribed together using standard dosages. No significant interaction was detected between their chemical properties, requiring no adjustments to dose or schedule.",
    1: "Administer these medications at separate times, at least 2 to 4 hours apart. Spacing the doses prevents absorption conflicts in the gastrointestinal tract and ensures both medications remain effective.",
    2: "Dose adjustment and regular clinical monitoring are advised during concurrent use. Lowering the maintenance dose and checking routine laboratory parameters helps minimize adverse interaction risks.",
    3: "Avoid co-administration of these two medications. Concomitant use carries a high risk of severe toxicity or adverse clinical outcomes. An alternative medication should be selected."
  };
  const actionAdvice = ELABORATED_ADVICE[act.tier] || "Consult prescribing monographs and clinical reference compendia for specific co-administration protocols.";

  let md = `# InteractomeX – Drug–Drug Interaction Clinical Report\n\n`;
  md += `**Date:** ${dateStr}  \n`;
  md += `**Model:** InteractomeX Multi-Modal GATv2 Deep Neural Network  \n`;
  md += `**Compound A:** ${nameA} (${data.drug_a?.cid || 'N/A'})  \n`;
  md += `**Compound B:** ${nameB} (${data.drug_b?.cid || 'N/A'})  \n\n`;

  md += `## 1. Executive Summary\n\n`;
  md += `* **Overall Verdict:** ${interacts ? '⚠️ INTERACTION DETECTED' : '✅ NO SIGNIFICANT INTERACTION'}\n`;
  md += `* **Calibrated Confidence Score:** ${gatePct}% (Decision Threshold: ${thresholdPct}%)\n`;
  if (data.risk) {
    md += `* **Rule-Based Clinical Risk Tier:** ${data.risk.label} Risk (Severity Score: ${data.risk.score !== undefined ? data.risk.score : 'N/A'})\n`;
  }
  md += `* **Training Dataset Provenance:** ${datasetStatus}\n`;
  md += `* **Score Interpretation:** ${data.explanation?.score_interpretation || 'N/A'}\n\n`;

  md += `## 2. Clinical Prescribing Guidance\n\n`;
  md += `### ${actionLabel}\n`;
  md += `${actionAdvice}\n\n`;

  md += `## 3. Physicochemical Descriptors Comparison\n\n`;
  const listA = molA?.descriptors || [];
  const listB = molB?.descriptors || [];
  if (listA.length && listB.length) {
    md += `| Descriptor | ${nameA} | ${nameB} | Difference (|A - B|) |\n`;
    md += `| :--- | :--- | :--- | :--- |\n`;
    listA.forEach((dA, i) => {
      const dB = listB[i] || { value: 0 };
      const diff = Math.abs(dA.value - dB.value);
      const isFloat = dA.value % 1 !== 0;
      const diffStr = isFloat ? diff.toFixed(2) : Math.round(diff);
      const unitStr = dA.unit ? ` ${dA.unit}` : '';
      md += `| ${dA.label} | ${dA.value}${unitStr} | ${dB.value}${unitStr} | Δ ${diffStr}${unitStr} |\n`;
    });
    md += `\n`;
  }

  md += `## 4. High-Risk Side-Effect Profile\n\n`;
  if (highRiskTypes.length === 0) {
    md += `*No specific adverse effects are available to display for this drug combination.*\n\n`;
  } else {
    md += `| Adverse Reaction | Clinical Mechanism | Probability | Cutoff |\n`;
    md += `| :--- | :--- | :--- | :--- |\n`;
    highRiskTypes.forEach(t => {
      md += `| ${t.name} | ${t.clinical_explanation || 'Synergistic physiological toxicity'} | ${(t.prob * 100).toFixed(1)}% | ${(t.threshold * 100).toFixed(1)}% |\n`;
    });
    md += `\n`;
  }

  if (data.xai?.descriptor_shap) {
    const shap = data.xai.descriptor_shap;
    md += `## 5. Explainability Summary (KernelSHAP Feature Attribution)\n\n`;
    const formatShapMd = (items, label) => {
      if (!items || !items.length) return '';
      const pos = items.filter(d => (d.attribution || 0) >= 0).sort((a,b) => (b.attribution||0) - (a.attribution||0)).slice(0, 3);
      const neg = items.filter(d => (d.attribution || 0) < 0).sort((a,b) => Math.abs(b.attribution||0) - Math.abs(a.attribution||0)).slice(0, 2);
      let s = `**${label}:**\n`;
      if (pos.length) s += `* *Promotes Interaction (+):* ${pos.map(p => `${p.name} (+${p.attribution.toFixed(4)})`).join(', ')}\n`;
      if (neg.length) s += `* *Suppresses Interaction (−):* ${neg.map(n => `${n.name} (${n.attribution.toFixed(4)})`).join(', ')}\n`;
      return s;
    };
    md += formatShapMd(shap.drug_a, nameA);
    md += formatShapMd(shap.drug_b, nameB);
    md += `\n`;
  }

  md += `## 6. Chemical Structures & SMILES\n\n`;
  md += `* **${nameA} SMILES:** \`${data.drug_a?.smiles || 'N/A'}\`\n`;
  md += `* **${nameB} SMILES:** \`${data.drug_b?.smiles || 'N/A'}\`\n\n`;

  md += `---\n*Disclaimer: InteractomeX is an AI-assisted computational pharmacology research tool. Model predictions provide quantitative risk hypotheses and representation affinities; they do not replace licensed clinical judgement or laboratory assays.*`;
  return md;
}

function generateHtmlReport(data, nameA, nameB) {
  const dateStr = new Date().toLocaleString();
  const interacts = data.interacts;
  const gatePct = (data.gate_prob * 100).toFixed(1);
  const thresholdPct = ((data.gate_threshold || 0.48) * 100).toFixed(1);

  let datasetBadgeHtml = '';
  if (data.in_dataset === true) {
    datasetBadgeHtml = '<span class="badge badge-confirmed">📋 Confirmed in benchmark dataset</span>';
  } else if (data.in_dataset === false) {
    datasetBadgeHtml = '<span class="badge badge-novel">🔬 Novel Pair (Generalised Inference)</span>';
  }

  const types = data.active_interaction_types || [];
  const MILD_SYMPTOMS = ['nausea', 'vomiting', 'diarrhea', 'diarrhoea', 'fever', 'pyrexia', 'fatigue', 'headache', 'body temperature'];
  const isMild = (name) => {
    const lower = (name || '').toLowerCase();
    return MILD_SYMPTOMS.some(m => lower.includes(m));
  };
  const activeSignificant = types.filter(t => t.is_active && !isMild(t.name));
  const highRiskOnly = activeSignificant.filter(t => t.severity_tier === 'High');
  const highRiskTypes = highRiskOnly.length > 0 ? highRiskOnly : activeSignificant;

  const molA = data.molecules?.drug_a;
  const molB = data.molecules?.drug_b;
  const listA = molA?.descriptors || [];
  const listB = molB?.descriptors || [];

  // Clinical Advice
  const act = data.clinical_action || {};
  const rawLabel = act.label || '';
  const actionLabel = rawLabel.replace(/^Class\s*\d+\s*:\s*/i, '').trim() || (interacts ? 'Clinical Review Recommended' : 'Safe Concomitant Use');
  const ELABORATED_ADVICE = {
    0: "These medications can be safely prescribed together using standard dosages. No significant interaction was detected between their chemical properties, requiring no adjustments to dose or schedule.",
    1: "Administer these medications at separate times, at least 2 to 4 hours apart. Spacing the doses prevents absorption conflicts in the gastrointestinal tract and ensures both medications remain effective.",
    2: "Dose adjustment and regular clinical monitoring are advised during concurrent use. Lowering the maintenance dose and checking routine laboratory parameters helps minimize adverse interaction risks.",
    3: "Avoid co-administration of these two medications. Concomitant use carries a high risk of severe toxicity or adverse clinical outcomes. An alternative medication should be selected."
  };
  const tierAdvice = ELABORATED_ADVICE[act.tier] || "Consult prescribing monographs and clinical reference compendia for specific co-administration protocols.";

  // Descriptors Table rows (Fixed - reading array items directly)
  let descRows = '';
  if (listA.length && listB.length) {
    descRows = listA.map((dA, i) => {
      const dB = listB[i] || { value: 0 };
      const diff = Math.abs(dA.value - dB.value);
      const isFloat = dA.value % 1 !== 0;
      const diffStr = isFloat ? diff.toFixed(2) : Math.round(diff);
      const unitStr = dA.unit ? ' ' + dA.unit : '';
      return `
        <tr>
          <td>
            <strong>${escHtml(dA.label)}</strong>
            <span style="display:block;font-size:0.73rem;color:#6b7280;">${escHtml(dA.tooltip || '')}</span>
          </td>
          <td>${dA.value}${unitStr}</td>
          <td>${dB.value}${unitStr}</td>
          <td><span style="font-weight:700;color:#4f46e5;">Δ ${diffStr}${unitStr}</span></td>
        </tr>
      `;
    }).join('');
  } else {
    descRows = '<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:1rem;">Descriptors unavailable for these inputs.</td></tr>';
  }

  // Side-Effect Profile rows (Filtered strictly to true High-Risk)
  let typesRows = '';
  if (highRiskTypes.length === 0) {
    typesRows = '<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:1.2rem;">No specific adverse effects are available to display for this drug combination.</td></tr>';
  } else {
    highRiskTypes.forEach(t => {
      typesRows += `
        <tr>
          <td style="font-weight:700;color:#991b1b;">${escHtml(t.name)}</td>
          <td style="color:#4b5563;font-size:0.83rem;">${escHtml(t.clinical_explanation || 'Combined pharmacological exposure increases susceptibility to adverse outcomes.')}</td>
          <td style="font-weight:600;">${(t.prob * 100).toFixed(1)}%</td>
          <td style="color:#6b7280;">${(t.threshold * 100).toFixed(1)}%</td>
        </tr>
      `;
    });
  }

  // Explainability Summary (KernelSHAP)
  let shapSummaryHtml = '';
  if (data.xai?.descriptor_shap) {
    const shap = data.xai.descriptor_shap;
    const formatTopShap = (items, drugLabel) => {
      if (!items || !items.length) return '';
      const pos = items.filter(d => (d.attribution || 0) >= 0).sort((a,b) => (b.attribution||0) - (a.attribution||0)).slice(0, 3);
      const neg = items.filter(d => (d.attribution || 0) < 0).sort((a,b) => Math.abs(b.attribution||0) - Math.abs(a.attribution||0)).slice(0, 2);
      return `
        <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:1rem; flex:1; min-width:260px;">
          <div style="font-weight:700; font-size:0.88rem; margin-bottom:0.5rem; color:#111827;">${escHtml(drugLabel)} — Key Physicochemical Drivers</div>
          <div style="font-size:0.8rem; margin-bottom:0.35rem;"><strong style="color:#059669;">Promotes Interaction (+):</strong> ${pos.map(p => `${p.name} (+${p.attribution.toFixed(4)})`).join(', ') || 'None'}</div>
          <div style="font-size:0.8rem;"><strong style="color:#dc2626;">Suppresses Interaction (−):</strong> ${neg.map(n => `${n.name} (${n.attribution.toFixed(4)})`).join(', ') || 'None'}</div>
        </div>
      `;
    };
    shapSummaryHtml = `
      <div class="section-title">Explainability Summary (KernelSHAP Feature Attribution)</div>
      <div style="display:flex; gap:1rem; margin-bottom:2rem; flex-wrap:wrap;">
        ${formatTopShap(shap.drug_a, nameA)}
        ${formatTopShap(shap.drug_b, nameB)}
      </div>
    `;
  }

  // Risk badge in verdict
  const riskTier = data.risk?.label || (interacts ? 'Moderate' : 'None');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>InteractomeX Clinical Report – ${escHtml(nameA)} + ${escHtml(nameB)}</title>
  <style>
    :root {
      --primary: #4f46e5;
      --text: #1f2937;
      --text-muted: #4b5563;
      --bg: #f9fafb;
      --card-bg: #ffffff;
      --border: #e5e7eb;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 2.5rem 1rem;
    }
    .report-container {
      max-width: 960px;
      margin: 0 auto;
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
      padding: 2.5rem;
    }
    .report-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 2px solid var(--border);
      padding-bottom: 1.5rem;
      margin-bottom: 2rem;
    }
    .brand { font-size: 1.6rem; font-weight: 800; color: #1e1b4b; letter-spacing: -0.02em; }
    .brand span { color: var(--primary); }
    .meta { font-size: 0.85rem; color: var(--text-muted); text-align: right; }
    .print-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: var(--primary);
      color: white;
      border: none;
      border-radius: 6px;
      padding: 0.55rem 1.1rem;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      margin-top: 0.5rem;
    }
    .print-btn:hover { background: #4338ca; }
    .verdict-box {
      border-radius: 10px;
      padding: 1.5rem;
      margin-bottom: 1.75rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: ${interacts ? '#fef2f2' : '#ecfdf5'};
      border: 1px solid ${interacts ? '#fecaca' : '#a7f3d0'};
    }
    .verdict-title {
      font-size: 1.3rem;
      font-weight: 800;
      color: ${interacts ? '#991b1b' : '#065f46'};
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .verdict-sub {
      font-size: 0.95rem;
      color: ${interacts ? '#b91c1c' : '#047857'};
      margin-top: 0.3rem;
    }
    .score-badge {
      font-size: 1.8rem;
      font-weight: 800;
      color: ${interacts ? '#dc2626' : '#059669'};
      text-align: right;
    }
    .score-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); }
    .section-title {
      font-size: 1.1rem;
      font-weight: 700;
      color: #111827;
      margin-bottom: 1rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.4rem;
    }
    .badge {
      display: inline-block;
      padding: 0.25rem 0.65rem;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .badge-confirmed { background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
    .badge-novel { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    .badge-risk { background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
    .advice-box {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid var(--primary);
      border-radius: 8px;
      padding: 1.25rem 1.5rem;
      margin-bottom: 2rem;
    }
    .advice-title { font-size: 1.1rem; font-weight: 800; color: #1e1b4b; margin-bottom: 0.4rem; }
    .advice-desc { font-size: 0.88rem; color: #374151; line-height: 1.6; }
    .structures-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.5rem;
      margin-bottom: 2rem;
    }
    .drug-box {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      background: #fafafa;
    }
    .drug-title { font-size: 1.05rem; font-weight: 700; color: #111827; }
    .drug-cid { font-size: 0.8rem; color: #6b7280; margin-bottom: 0.75rem; }
    .drug-svg {
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      height: 180px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      margin-bottom: 0.75rem;
    }
    .drug-svg svg { max-width: 100%; max-height: 100%; }
    .smiles-code {
      font-family: monospace;
      font-size: 0.75rem;
      background: #f3f4f6;
      padding: 0.4rem;
      border-radius: 4px;
      word-break: break-all;
    }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-bottom: 2rem; }
    th { background: #f3f4f6; text-align: left; padding: 0.65rem 0.75rem; color: #374151; font-weight: 600; border-bottom: 1px solid var(--border); }
    td { padding: 0.65rem 0.75rem; border-bottom: 1px solid var(--border); color: #374151; }
    .expl-box {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 1rem 1.25rem;
      font-size: 0.85rem;
      color: #334155;
      line-height: 1.6;
      margin-bottom: 2rem;
    }
    .footer {
      border-top: 1px solid var(--border);
      padding-top: 1.25rem;
      font-size: 0.75rem;
      color: #9ca3af;
      text-align: center;
    }
    @media print {
      body { background: white; padding: 0; }
      .report-container { box-shadow: none; border: none; padding: 0; max-width: 100%; }
      .print-btn { display: none; }
      .advice-box, .verdict-box, table, .structures-grid { page-break-inside: avoid; }
    }
  </style>
</head>
<body>
  <div class="report-container">
    <div class="report-header">
      <div>
        <div class="brand">Interactome<span>X</span></div>
        <div style="font-size:0.88rem;color:#4b5563;font-weight:500;">Clinical & Computational Drug–Drug Interaction Analysis</div>
      </div>
      <div class="meta">
        <div><strong>Generated:</strong> ${dateStr}</div>
        <div><strong>Architecture:</strong> GATv2 Multi-Modal Deep Neural Network</div>
        <button class="print-btn" onclick="window.print()">🖨️ Print / Save as PDF</button>
      </div>
    </div>

    <div class="verdict-box">
      <div>
        <div class="verdict-title">${interacts ? '⚠️ INTERACTION DETECTED' : '✅ NO SIGNIFICANT INTERACTION'}</div>
        <div class="verdict-sub">Evaluation for <strong>${escHtml(nameA)}</strong> + <strong>${escHtml(nameB)}</strong></div>
        <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; margin-top:0.6rem;">
          ${datasetBadgeHtml}
          ${data.risk?.label ? `<span class="badge badge-risk">🛡️ Clinical Risk Tier: <strong>${escHtml(data.risk.label)} Risk</strong></span>` : ''}
        </div>
      </div>
      <div>
        <div class="score-badge">${gatePct}%</div>
        <div class="score-label">Calibrated Confidence (Cutoff: ${thresholdPct}%)</div>
      </div>
    </div>

    <!-- Clinical Prescribing Guidance -->
    <div class="advice-box">
      <div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--primary); font-weight:700; margin-bottom:0.25rem;">Clinical Prescribing Guidance</div>
      <div class="advice-title">${escHtml(actionLabel)}</div>
      <p class="advice-desc">${escHtml(tierAdvice)}</p>
    </div>

    <div class="expl-box">
      <strong>Score Interpretation:</strong><br>
      ${escHtml(data.explanation?.score_interpretation || '')}
    </div>

    <div class="section-title">Compound Chemical Profiles</div>
    <div class="structures-grid">
      <div class="drug-box">
        <div class="drug-title">${escHtml(nameA)}</div>
        <div class="drug-cid">${escHtml(molA?.cid || data.drug_a?.cid || 'Custom Molecule')}</div>
        <div class="drug-svg">${molA?.svg || '<span style="color:#9ca3af">Structure visualizer unavailable</span>'}</div>
        <div class="smiles-code"><strong>SMILES:</strong> ${escHtml(molA?.smiles || data.drug_a?.smiles || 'N/A')}</div>
      </div>
      <div class="drug-box">
        <div class="drug-title">${escHtml(nameB)}</div>
        <div class="drug-cid">${escHtml(molB?.cid || data.drug_b?.cid || 'Custom Molecule')}</div>
        <div class="drug-svg">${molB?.svg || '<span style="color:#9ca3af">Structure visualizer unavailable</span>'}</div>
        <div class="smiles-code"><strong>SMILES:</strong> ${escHtml(molB?.smiles || data.drug_b?.smiles || 'N/A')}</div>
      </div>
    </div>

    <div class="section-title">Physicochemical Descriptors & Pair Divergence (|A − B|)</div>
    <table>
      <thead>
        <tr>
          <th>Descriptor</th>
          <th>${escHtml(nameA)}</th>
          <th>${escHtml(nameB)}</th>
          <th>Difference (|A − B|)</th>
        </tr>
      </thead>
      <tbody>
        ${descRows}
      </tbody>
    </table>

    <div class="section-title">Side-Effect Profile (High-Risk Adverse Events: ${highRiskTypes.length})</div>
    <table>
      <thead>
        <tr>
          <th style="width:28%;">Adverse Reaction</th>
          <th style="width:46%;">Clinical Mechanism / Explanation</th>
          <th style="width:13%;">Model Prob.</th>
          <th style="width:13%;">Cutoff</th>
        </tr>
      </thead>
      <tbody>
        ${typesRows}
      </tbody>
    </table>

    ${shapSummaryHtml}

    <div class="footer">
      InteractomeX Clinical & Computational Research Platform • GATv2 Multi-Modal Deep Neural Network • For clinical reference and pharmacological exploration use only.
    </div>
  </div>
</body>
</html>`;
}

