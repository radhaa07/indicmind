let contractId = null;
let englishReport = '';
let englishNerHtml = '';
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// Helper for escaping HTML
function escapeHTML(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Marker-pen effect for key facts found in an agreement.
function highlightImportant(value) {
  return value.replace(
    /\b(?:INR|USD|EUR|GBP)\s?[\d,]+(?:\.\d{2})?|[₹$€£]\s?[\d,]+(?:\.\d{2})?|\b\d+\s*\((?:\d+)\)\s*(?:days?|months?|years?)\b|\b(?:\d+\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b|\b(?:termination|terminate|payment|fee|liability|indemnity|confidential(?:ity)?|governing law|jurisdiction|effective date|notice|breach|penalty|renewal|intellectual property|data protection)\b/gi,
    '<mark class="important-highlight">$&</mark>'
  );
}

// Custom simple markdown parser for legal reports
function parseMarkdown(md) {
  if (!md) return "";
  // Render line-by-line so headings, lists, and paragraphs stay valid HTML.
  const inline = value => escapeHTML(value)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\[Clause\s+(\d+)\]/gi, '<span class="citation-tag" onclick="highlightCitation($1)">Clause $1</span>')
    .replace(/(<[^>]+>)|([^<]+)/g, (match, tag, text) => tag || highlightImportant(text));
  const output = [];
  let listOpen = false;
  const closeList = () => { if (listOpen) { output.push('</ul>'); listOpen = false; } };
  md.split(/\r?\n/).forEach(line => {
    // Defense: a translation that flattened newlines arrives as one giant
    // line — re-split run-ons at sentence boundaries (no lookbehind, Safari-safe).
    const sublines = line.length > 500
      ? (line.match(/[^.!?]+[.!?]+["']?(?=\s|$)|\s*[^.!?]+$/g) || [line]).map(s => s.trim()).filter(Boolean)
      : [line];
    sublines.forEach(sub => {
    const heading = sub.match(/^(#{1,3})\s+(.+)$/);
    const item = sub.match(/^\s*[-*]\s+(.+)$/);
    if (heading) {
      closeList();
      // Demote report headings: page already has its H1, so `#` renders as H2 (single-H1 outline).
      const level = Math.min(heading[1].length + 1, 3);
      output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (item) {
      if (!listOpen) { output.push('<ul>'); listOpen = true; }
      output.push(`<li>${inline(item[1])}</li>`);
    } else if (sub.trim()) {
      closeList();
      output.push(`<p>${inline(sub)}</p>`);
    } else {
      closeList();
    }
    });
  });
  closeList();
  return output.join('');
}

// Function to focus and highlight a citation in the citations panel
window.highlightCitation = function (clauseNum) {
  // Switch to QA tab first so user can inspect citations
  switchTab('tab-qa');

  // Look for the citation clause card
  setTimeout(() => {
    const citationCards = $$('#citations article');
    let found = false;
    citationCards.forEach(card => {
      const header = card.querySelector('strong');
      if (header && header.textContent.includes(`Clause ${clauseNum}`)) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.style.borderLeftColor = '#f6db48';
        card.style.background = 'linear-gradient(90deg, #fefce8, transparent)';
        setTimeout(() => {
          card.style.borderLeftColor = '#51c6a5';
          card.style.background = 'linear-gradient(90deg, #effcf5, transparent)';
        }, 3000);
        found = true;
      }
    });
    if (!found) {
      // Suggest search
      $('#question').value = `What does Clause ${clauseNum} state?`;
      $('#ask-form').requestSubmit();
    }
  }, 100);
};

// Drag and drop functionality for the upload dropzone
const dropzone = $('.dropzone');
const fileInput = $('#contract');
const selectedFileSpan = $('#selected-file');
let providerState = { gemini_configured: true, gemini_valid: null, ollama_ready: false };

function updateProviderHelp() {
  const select = $('#upload-provider');
  const help = $('#provider-help');
  if (!select || !help) return;
  if (select.value === 'ollama' && !providerState.ollama_ready) {
    help.textContent = 'Ollama is not running. Choose Gemini Cloud, or start Ollama and install its configured model first.';
    help.classList.add('error');
  } else if (select.value === 'gemini' && !providerState.gemini_configured) {
    help.textContent = 'Gemini Cloud needs a valid GEMINI_API_KEY in the .env file.';
    help.classList.add('error');
  } else if (select.value !== 'ollama' && providerState.gemini_configured && providerState.gemini_valid === false) {
    help.textContent = 'That GEMINI_API_KEY was rejected by Google — get a free key from Google AI Studio, or answers will use local Ollama instead.';
    help.classList.add('error');
  } else {
    help.textContent = 'For Tamil, Kannada, and other languages, Gemini Cloud translates the full document before analysis.';
    help.classList.remove('error');
  }
}

async function loadProviderStatus() {
  try {
    const response = await fetch('/api/providers');
    if (response.ok) providerState = await response.json();
  } catch (_) { /* Upload endpoint still gives the final provider error. */ }
  updateProviderHelp();
}

let analysisStatusTimer = null;
function setAnalysisLoading(visible, customSteps = null) {
  const overlay = $('#analysis-overlay');
  const status = $('#analysis-status');
  const fill = $('#analysis-progress-fill');
  const stepLabels = $$('#analysis-overlay .analysis-steps span');
  if (!overlay || !status) return;
  clearInterval(analysisStatusTimer);
  overlay.hidden = !visible;
  if (!visible) return;
  const steps = customSteps || [
    'Reading the document securely…',
    'Translating Indian languages when needed…',
    'spaCy NER + hybrid retrieval — semantic recognition…',
    'Grounding entities in source clauses…'
  ];
  const setStep = (index) => {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    status.textContent = `${steps[index]} · ${elapsed}s`;
    if (fill) fill.style.width = `${24 + index * 24}%`;
    stepLabels.forEach((label, labelIndex) => label.classList.toggle('active', labelIndex <= index));
  };
  let step = 0;
  const startTime = Date.now();
  setStep(step);
  analysisStatusTimer = setInterval(() => {
    step = (step + 1) % steps.length;
    setStep(step);
  }, 2600);
}

/* Upload jobs: the server answers POST instantly with a job id, then this
   polls staged progress (Reading → Translating → Extracting → Report) and
   drives the overlay with REAL percentages instead of a blind spinner. */
async function pollUploadJob(jobId, maxMs = 7 * 60 * 1000) {
  const t0 = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 2000));
    let job = null;
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      job = await res.json();
      if (!res.ok) throw new Error((job && job.error) || 'Upload status unavailable.');
    } catch (e) {
      if (Date.now() - t0 > maxMs) throw new Error('Taking too long — the server is still working. Please retry in a minute.');
      continue; // transient network blip: keep polling
    }
    if (job.status === 'done' && job.result) return job.result;
    if (job.status === 'error') throw new Error(job.error || 'Analysis failed.');
    const status = $('#analysis-status');
    if (status) status.textContent = `${job.stage || 'Working…'} · ${job.pct || 0}%`;
    const fill = $('#analysis-progress-fill');
    if (fill) fill.style.width = `${job.pct || 5}%`;
    if (Date.now() - t0 > maxMs) throw new Error('Taking too long — the server is still working. Please retry in a minute.');
  }
}

/* Skeleton placeholders that mirror the final content structure.
   Every render target below replaces innerHTML, so these are always
   overwritten by real content (or hidden with their panel on error). */
function skLine(width, extraClass) {
  return '<div class="sk ' + (extraClass || 'sk-l sk-mb') + '" style="width:' + width + '"></div>';
}
function paintWorkspaceSkeletons() {
  const ner = $('#ner-highlighted-container');
  if (ner) ner.innerHTML = skLine('100%') + skLine('92%') + skLine('88%');
  const grid = $('#semantic-visual-grid');
  if (grid) grid.innerHTML = '<div class="sk sk-entity"></div><div class="sk sk-entity"></div><div class="sk sk-entity"></div>';
  const rep = $('#report-container');
  if (rep) rep.innerHTML = '<div class="sk sk-t sk-mb" style="width:42%"></div>' + skLine('100%') + skLine('97%') + skLine('88%') + skLine('60%');
  const cl = $('#clauses-container');
  if (cl) cl.innerHTML = '<div class="sk sk-entity sk-mb"></div><div class="sk sk-entity"></div>';
  ['risks-list', 'missing-list', 'inconsistencies-list'].forEach((id) => {
    const elm = document.getElementById(id);
    if (elm) elm.innerHTML = '<div class="sk sk-audit sk-mb"></div><div class="sk sk-audit"></div>';
  });
}
function paintAnswerSkeletons() {
  const answerCard = $('#answer-card');
  const answer = $('#answer');
  const citations = $('#citations');
  if (answerCard) answerCard.hidden = false;
  if (answer) {
    answer.innerHTML =
      '<div class="sk sk-chip sk-mb" style="width:180px"></div>' +
      skLine('100%') + skLine('96%') + skLine('91%') + skLine('55%') +
      '<div style="display:flex;gap:8px;margin-top:4px"><div class="sk sk-chip" style="width:90px"></div><div class="sk sk-chip" style="width:120px"></div></div>';
  }
  if (citations) citations.innerHTML = '<div class="sk sk-audit sk-mb"></div><div class="sk sk-audit"></div>';
}
function paintHistorySkeletons() {
  const tbody = $('#saved-contracts-list');
  if (!tbody) return;
  let rows = '';
  for (let r = 0; r < 3; r++) {
    rows += '<tr><td><div class="sk sk-l" style="width:75%"></div></td>' +
      '<td><div class="sk sk-chip" style="width:52px"></div></td>' +
      '<td><div class="sk sk-l" style="width:60%"></div></td>' +
      '<td><div style="display:flex;gap:8px"><div class="sk sk-chip" style="width:70px"></div><div class="sk sk-chip" style="width:56px"></div></div></td></tr>';
  }
  tbody.innerHTML = rows;
  const container = $('#saved-contracts-panel');
  if (container) container.style.display = 'block';
}

if (dropzone) {
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, () => dropzone.classList.add('dragover'), false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, () => dropzone.classList.remove('dragover'), false);
  });

  dropzone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      fileInput.files = files;
      displayFileName(files[0].name);
    }
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      displayFileName(e.target.files[0].name);
    }
  });
}

function displayFileName(name) {
  selectedFileSpan.textContent = name;
  selectedFileSpan.classList.add('show');
}

// Load and render history of saved contracts
async function loadContractsHistory() {
  paintHistorySkeletons();
  try {
    const res = await fetch('/api/contracts');
    if (!res.ok) throw new Error('Could not fetch contract history.');
    const contractsList = await res.json();

    const container = $('#saved-contracts-panel');
    const tbody = $('#saved-contracts-list');

    if (contractsList.length > 0) {
      tbody.innerHTML = '';
      contractsList.forEach(c => {
        const tr = document.createElement('tr');

        // Date parsing
        const dateObj = new Date(c.created_at + 'Z');
        const formattedDate = dateObj.toLocaleDateString(undefined, {
          year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });

        tr.innerHTML = `
          <td style="font-weight: 600; color: var(--ink);">${escapeHTML(c.filename)}</td>
          <td><span class="file-badge badge-${c.file_type}">${c.file_type.toUpperCase()}</span></td>
          <td>${formattedDate}</td>
          <td>
            <div style="display: flex; gap: 16px;">
              <button class="btn-sm load-btn" data-id="${c.id}">View Analysis</button>
              <button class="btn-sm btn-table-danger" data-id="${c.id}">Delete</button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });

      // Hook up actions
      tbody.querySelectorAll('.load-btn').forEach(btn => {
        btn.onclick = () => loadContractSession(btn.dataset.id);
      });
      tbody.querySelectorAll('.btn-table-danger').forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          deleteContract(btn.dataset.id);
        };
      });

      container.style.display = 'block';
    } else {
      container.style.display = 'none';
    }
  } catch (err) {
    console.error('Error loading history:', err);
  }
}

// Load contract data from database
async function loadContractSession(id) {
  // Reveal the workspace immediately with skeletons mirroring the report,
  // entity and risk layouts; renderContractData replaces them on success.
  paintWorkspaceSkeletons();
  $('#dashboard-view').style.display = 'none';
  $('#workspace').hidden = false;
  try {
    const res = await fetch(`/api/contracts/${id}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load contract session.');

    contractId = data.id;
    renderContractData(data);
  } catch (err) {
    $('#workspace').hidden = true;
    $('#dashboard-view').style.display = 'block';
    alert(err.message);
  }
}

// Delete contract
async function deleteContract(id) {
  if (!confirm('Are you sure you want to delete this contract from your saved history?')) return;
  try {
    const res = await fetch(`/api/contracts/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Deletion failed.');

    if (contractId === id) {
      closeSession();
    } else {
      loadContractsHistory();
    }
  } catch (err) {
    alert(err.message);
  }
}

// Close session and reset back to dashboard
function closeSession() {
  contractId = null;
  $('#workspace').hidden = true;
  $('#dashboard-view').style.display = 'block';
  selectedFileSpan.textContent = '';
  selectedFileSpan.classList.remove('show');
  $('#upload-form').reset();
  loadContractsHistory();
}

$('#new-contract').onclick = closeSession;

const deleteCurrentBtn = $('#delete-current-btn');
if (deleteCurrentBtn) {
  deleteCurrentBtn.onclick = () => {
    if (contractId) deleteContract(contractId);
  };
}

const reanalyzeCurrentBtn = $('#reanalyze-current-btn');
if (reanalyzeCurrentBtn) {
  reanalyzeCurrentBtn.onclick = async () => {
    if (!contractId) return;
    const label = reanalyzeCurrentBtn.textContent;
    reanalyzeCurrentBtn.disabled = true;
    reanalyzeCurrentBtn.textContent = 'Reprocessing…';
    try {
      const response = await fetch(`/api/contracts/${contractId}/reanalyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'auto' })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not reprocess this document.');
      renderContractData(data);
    } catch (error) {
      alert(error.message);
    } finally {
      reanalyzeCurrentBtn.disabled = false;
      reanalyzeCurrentBtn.textContent = label;
    }
  };
}

// Render the contract structured analysis
function renderContractData(data) {
  $('#filename').textContent = data.filename;

  // Set Metadata Overview
  const meta = data.analysis.metadata || {};
  $('#meta-type').textContent = meta.agreement_type || 'Unknown';
  $('#meta-parties').textContent = meta.parties ? meta.parties.join(' vs ') : 'Not Specified';
  $('#meta-date').textContent = meta.effective_date || 'Not Specified';
  $('#meta-law').textContent = meta.governing_law || 'Not Specified';

  const entitiesBadge = $('#meta-entities');
  if (entitiesBadge) {
    const allEnts = data.analysis.entities || [];
    const totalCount = allEnts.reduce((a, e) => a + (e.values ? e.values.length : 0), 0);
    entitiesBadge.textContent = `${totalCount} across ${allEnts.length} types`;
  }

  // Language badge: show "Translated from X" when contract was non-English
  const langSpan = $('#meta-lang');
  const origLang = meta.original_language || 'English';
  if (origLang === 'English') {
    langSpan.textContent = 'English';
    langSpan.className = '';
  } else {
    langSpan.innerHTML = `<span class="lang-translated-badge">Translated from ${escapeHTML(origLang)}</span>`;
  }

  // Tab 1: Semantic NER — highlighted (3rd image) + visual grid
  englishReport = data.report || '';
  englishNerHtml = data.analysis.ner_highlighted_html || '';
  const nerContainer = $('#ner-highlighted-container');
  if (nerContainer) {
    nerContainer.innerHTML = englishNerHtml || '<p style="color:var(--ink-soft);font-size:13px">NER view not available for this document.</p>';
  }
  // Visual grid: DOCUMENT ANALYSIS → MULTILINGUAL NER semantic entities
  const visGrid = $('#semantic-visual-grid');
  if (visGrid) {
    const ents = data.analysis.entities || [];
    const colorByType = {Persons:'#FFDAB9', Organizations:'#A0E0E0', Locations:'#FFDC8A', Dates:'#A8D8EA', Amounts:'#FFB6B6', Jurisdictions:'#C1F0C1', Parties:'#E0E0E0', 'Legal References':'#FFC0CB', 'Key topics':'#FFE4B5'};
    const iconByType = {Persons:'👤', Organizations:'🏢', Locations:'📍', Dates:'📅', Amounts:'💰', Jurisdictions:'⚖️', Parties:'🤝', 'Legal References':'📜', 'Key topics':'🔑'};
    if (ents.length) {
      visGrid.innerHTML = ents.map(e => {
        const bg = colorByType[e.type] || '#E6EFE9';
        const icon = iconByType[e.type] || '•';
        return `<div style="background:#FFFEFA;border:1.5px solid #E0D9B8;border-radius:10px;padding:12px 12px;box-shadow:0 4px 12px rgba(14,46,43,.06);height:100%;box-sizing:border-box">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="width:28px;height:28px;border-radius:8px;display:grid;place-items:center;background:${bg};border:1px solid rgba(0,0,0,.06);font-size:14px">${icon}</span>
            <strong style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--w-ink)">${escapeHTML(e.type)}</strong>
            <span style="margin-left:auto;background:var(--w-ink);color:#FFE629;font-size:12px;font-weight:800;padding:2px 7px;border-radius:999px">${e.values.length}</span>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px">${e.values.map(v=>`<span style="background:${bg};border:1px solid rgba(0,0,0,.06);padding:3px 8px;border-radius:999px;font-size:12px;font-weight:600;color:var(--w-ink)">${escapeHTML(v)}</span>`).join('')}</div>
        </div>`;
      }).join('');
    } else {
      visGrid.innerHTML = '<p style="color:var(--ink-soft);font-size:13px">No entities detected.</p>';
    }
  }
  $('#report-container').innerHTML = parseMarkdown(data.report);

  // Tab 2: Entities — IndicMind for Indian Languages (replaces Key Clauses)
  const clausesContainer = $('#clauses-container');
  clausesContainer.innerHTML = '';
  const entitiesTab = data.analysis.entities || [];
  const colorByType2 = {Persons:'#FFDAB9', Organizations:'#A0E0E0', Locations:'#FFDC8A', Dates:'#A8D8EA', Amounts:'#FFB6B6', Jurisdictions:'#C1F0C1', Facilities:'#FCEEB0', Events:'#FFEC8B', Parties:'#E0E0E0', 'Legal References':'#FFC0CB', 'Key topics':'#FFE4B5', Groups:'#FFE4B5', Languages:'#E0E0FF'};
  if (entitiesTab.length > 0) {
    entitiesTab.forEach((e) => {
      const bg = colorByType2[e.type] || '#E6EFE9';
      const details = document.createElement('details');
      details.className = 'clause-accordion';
      details.open = true;
      details.innerHTML = `
        <summary class="clause-summary" style="background:#FFFEFA">
          <div style="display:flex; justify-content:space-between; align-items:center; width: 100%; padding-right: 10px;">
            <strong style="display:flex;align-items:center;gap:8px"><span style="width:26px;height:26px;border-radius:8px;display:grid;place-items:center;background:${bg};border:1px solid rgba(0,0,0,.06);font-size:12px">${e.type.charAt(0)}</span>${escapeHTML(e.type)}</strong>
            <span style="background:${bg};border:1px solid rgba(0,0,0,.06);padding:2px 9px;border-radius:999px;font-size:12px;font-weight:800">${e.values.length} found</span>
          </div>
        </summary>
        <div class="clause-content" style="background:#FFFEFA">
          <div style="display:flex;flex-wrap:wrap;gap:8px">
            ${e.values.map(v=>`<span style="background:${bg};border:1px solid rgba(0,0,0,.06);padding:6px 10px;border-radius:999px;font-size:12px;font-weight:600;color:var(--w-ink)">${escapeHTML(v)}</span>`).join('')}
          </div>
          <p style="margin:10px 0 0;font-size:12px;color:var(--w-muted)">Grounded in source · spaCy + legal regex + LLM correction for Indian languages</p>
        </div>
      `;
      clausesContainer.appendChild(details);
    });
  } else {
    const clauses = data.analysis.key_clauses || [];
    if (clauses.length > 0) {
      clauses.forEach((c, idx) => {
        const details = document.createElement('details');
        details.className = 'clause-accordion';
        details.innerHTML = `
          <summary class="clause-summary">
            <div style="display:flex; justify-content:space-between; align-items:center; width: 100%; padding-right: 10px;">
              <strong>${escapeHTML(c.clause_name)}</strong>
              <span class="badge-${(c.severity || 'low').toLowerCase()} btn-sm" style="border-radius:4px; padding:2px 8px; font-size:10px;">${c.severity || 'Low'} Risk</span>
            </div>
          </summary>
          <div class="clause-content">
            <div class="summary-box">
              <strong>Plain Language Interpretation:</strong>
              <p>${escapeHTML(c.summary)}</p>
          </div>
          <div class="snippet-box">
            <strong>Source excerpt (important words highlighted):</strong>
            <blockquote>${highlightImportant(escapeHTML(c.text_snippet || 'No source excerpt available.'))}</blockquote>
          </div>
        </div>
      `;
      clausesContainer.appendChild(details);
    });
  } else {
    clausesContainer.innerHTML = '<p class="empty-msg">No structured key clauses extracted.</p>';
  }
  }

  // Tab 3: NER Quality & Language Gaps — title-aligned
  const entsForAudit = data.analysis.entities || [];
  const totalEnt = entsForAudit.reduce((a,e)=>a+e.values.length,0);
  const risksList = $('#risks-list');
  risksList.innerHTML = '';
  if (entsForAudit.length) {
    if (totalEnt >= 8) {
      risksList.innerHTML = `<div class="audit-item risk-item" style="border-left-color:#9381FF;background:#F5F0FF"><strong style="color:var(--w-ink)">High coverage — ${totalEnt} entities</strong><p style="margin:4px 0 0;color:var(--w-muted);font-size:13px">Across ${entsForAudit.length} types via spaCy + legal regex + LLM correction for Indian languages. No low-confidence gaps.</p></div>`;
    } else {
      risksList.innerHTML = `<div class="audit-item risk-item" style="border-left-color:#E76F2A;background:#FFF6E8"><strong style="color:var(--w-ink)">Low coverage — ${totalEnt} entities</strong><p style="margin:4px 0 0;color:var(--w-muted);font-size:13px">Try a longer document or include Hindi, Tamil, Kannada etc. for richer NER across 20+ languages.</p></div>`;
    }
  } else {
    risksList.innerHTML = '<p class="empty-msg">No entities detected — upload text with names, places, dates or amounts.</p>';
  }

  // Missing Entity Types
  const missingList = $('#missing-list');
  missingList.innerHTML = '';
  const allTypes = ["Persons","Organizations","Locations","Dates","Amounts","Events","Facilities"];
  const present = new Set(entsForAudit.map(e=>e.type));
  const missingTypes = allTypes.filter(t=>!present.has(t));
  if (missingTypes.length && entsForAudit.length) {
    missingList.innerHTML = missingTypes.map(t=>`
      <div class="audit-item missing-item" style="border-left-color:#E76F2A;background:#FFFEFA">
        <strong style="color:var(--w-ink)">Missing: ${t}</strong>
        <p style="margin:4px 0 0;color:var(--w-muted);font-size:13px">No ${t.toLowerCase()} detected. Add ${t.toLowerCase()} examples to enrich multilingual NER.</p>
      </div>`).join('');
  } else if (!missingTypes.length) {
    missingList.innerHTML = '<p class="empty-msg">✓ All core entity types present — strong Indian language coverage.</p>';
  } else {
    missingList.innerHTML = '<p class="empty-msg">Upload a document to see missing types.</p>';
  }

  // Script & Transliteration Consistency
  const inconsistenciesList = $('#inconsistencies-list');
  inconsistenciesList.innerHTML = '';
  const hasMixed = /[A-Za-z]/.test(JSON.stringify(entsForAudit)) && /[\u0900-\u097F\u0A80-\u0AFF\u0B80-\u0BFF]/.test(JSON.stringify(entsForAudit) + (data.report||""));
  if (hasMixed) {
    inconsistenciesList.innerHTML = `<div class="audit-item inconsistency-item" style="border-left-color:#9381FF;background:#F5F0FF"><p style="margin:0;color:var(--w-ink);font-size:13px">⚡ Mixed scripts — same entity in Latin & Devanagari (e.g., Mumbai/मुंबई). Normalized via translation + spaCy correction.</p></div>`;
  } else {
    inconsistenciesList.innerHTML = '<p class="empty-msg">✓ No script inconsistencies — consistent transliteration & translation.</p>';
  }

  // Clear QA tab answers
  $('#answer-card').hidden = true;
  $('#answer').replaceChildren();
  $('#citations').innerHTML = '';
  $('#question').value = '';

  // Show Workspace and hide upload dashboard
  $('#dashboard-view').style.display = 'none';
  $('#workspace').hidden = false;

  // Set tab back to first tab
  switchTab('tab-report');
}

// Upload Form Submission Handler
// Issue 6: never show backend internals (Argos packs, env vars, rate-limit
// jargon) — map them to one actionable, user-friendly line.
function friendlyUploadError(message) {
  const m = String(message || '');
  if (/argos|translation_provider|mymemory|rate-limit|too many requests|quota|unreachable/i.test(m)) {
    return 'Translation is temporarily unavailable (web translators are rate-limited). Wait a minute and retry, or pick Ollama Local which runs on this machine.';
  }
  return m;
}
$('#upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const chosenProvider = $('#upload-provider').value;
  if (chosenProvider === 'ollama' && !providerState.ollama_ready) {
    $('#upload-error').textContent = 'Ollama is not running. Select Gemini Cloud for translation, or start Ollama first.';
    updateProviderHelp();
    return;
  }
  if (chosenProvider === 'gemini' && !providerState.gemini_configured) {
    $('#upload-error').textContent = 'Gemini Cloud is not configured. Add a valid GEMINI_API_KEY to .env, then restart the app.';
    updateProviderHelp();
    return;
  }
  const button = event.submitter || event.target.querySelector('button');
  const buttonLabel = button.textContent;
  button.disabled = true;
  button.textContent = 'Analyzing with AI...';
  $('#upload-error').textContent = '';
  setAnalysisLoading(true);

  try {
    const formData = new FormData(event.target);
    formData.append('provider', chosenProvider);

    const startRes = await fetch('/api/contracts', { method: 'POST', body: formData });
    const startData = await startRes.json();
    if (!startRes.ok) throw new Error(startData.error);
    if (!startData.job_id) throw new Error('Upload could not start.');

    // Instant structure: stop the cycling timer, reveal the workspace with
    // skeletons right away, then follow the job's real staged progress.
    clearInterval(analysisStatusTimer);
    paintWorkspaceSkeletons();
    $('#dashboard-view').style.display = 'none';
    $('#workspace').hidden = false;

    const data = await pollUploadJob(startData.job_id);
    contractId = data.id;
    renderContractData(data);
  } catch (error) {
    $('#workspace').hidden = true;
    $('#dashboard-view').style.display = 'block';
    $('#upload-error').textContent = friendlyUploadError(error.message);
  } finally {
    setAnalysisLoading(false);
    button.disabled = false;
    button.textContent = buttonLabel;
  }
});

// Voice-note dictation on the upload card: user speaks content in any language,
// the transcript is analyzed for entities exactly like an uploaded document.
(function setupVoiceNote() {
  const micBtn = $('#voice-note-btn');
  const langSel = $('#voice-note-lang');
  const wrap = $('#voice-note-wrap');
  const textEl = $('#voice-note-text');
  const analyzeBtn = $('#voice-note-analyze');
  const clearBtn = $('#voice-note-clear');
  if (!micBtn || !langSel || !wrap || !textEl || !analyzeBtn || !clearBtn) return;

  micBtn.addEventListener('click', (e) => {
    e.preventDefault();
    wrap.hidden = false;
    if (typeof window.startVoiceInput === 'function') {
      window.startVoiceInput(textEl, micBtn, { lang: langSel.value || 'en-IN', commands: false, continuous: true });
    } else {
      $('#upload-error').textContent = 'Voice input is unavailable in this browser. Please use Chrome or Edge.';
    }
  });

  clearBtn.addEventListener('click', () => {
    textEl.value = '';
    textEl.focus();
  });

  analyzeBtn.addEventListener('click', async () => {
    const text = textEl.value.trim();
    const wordCount = text.split(/\s+/).filter(Boolean).length;
    if (wordCount < 10) {
      $('#upload-error').textContent = `Keep speaking — ${wordCount}/10 words minimum so there is enough content to extract entities from. The mic stays on until you stop it.`;
      textEl.focus();
      return;
    }
    const chosenProvider = $('#upload-provider').value;
    if (chosenProvider === 'ollama' && !providerState.ollama_ready) {
      $('#upload-error').textContent = 'Ollama is not running. Select Gemini Cloud for translation, or start Ollama first.';
      updateProviderHelp();
      return;
    }
    if (chosenProvider === 'gemini' && !providerState.gemini_configured) {
      $('#upload-error').textContent = 'Gemini Cloud is not configured. Add a valid GEMINI_API_KEY to .env, then restart the app.';
      updateProviderHelp();
      return;
    }
    const label = analyzeBtn.textContent;
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing voice note...';
    $('#upload-error').textContent = '';
    setAnalysisLoading(true);
    try {
      const langCode = (langSel.value || 'en-IN').split('-')[0];
      const file = new File([text], `voice-note-${langCode}.txt`, { type: 'text/plain' });
      const formData = new FormData();
      formData.append('contract', file);
      formData.append('provider', chosenProvider);
      const startRes = await fetch('/api/contracts', { method: 'POST', body: formData });
      const startData = await startRes.json();
      if (!startRes.ok) throw new Error(startData.error);
      if (!startData.job_id) throw new Error('Upload could not start.');
      clearInterval(analysisStatusTimer);
      paintWorkspaceSkeletons();
      $('#dashboard-view').style.display = 'none';
      $('#workspace').hidden = false;
      const data = await pollUploadJob(startData.job_id);
      contractId = data.id;
      renderContractData(data);
    } catch (error) {
      $('#workspace').hidden = true;
      $('#dashboard-view').style.display = 'block';
      $('#upload-error').textContent = friendlyUploadError(error.message);
    } finally {
      setAnalysisLoading(false);
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = label;
    }
  });
})();

// Q&A Form Submission Handler
$('#ask-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (!question) return;
  const button = event.target.querySelector('button');
  button.disabled = true;
  button.textContent = 'Analyzing…';
  // Local models answer slowly (~6 tok/s here) — show elapsed time so the
  // wait feels alive instead of stuck.
  const askT0 = Date.now();
  const askTick = setInterval(() => {
    button.textContent = `Analyzing… ${Math.floor((Date.now() - askT0) / 1000)}s`;
  }, 1000);
  paintAnswerSkeletons();

  try {
    const response = await fetch(`/api/contracts/${contractId}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, provider: $('#provider').value })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);

    $('#answer').replaceChildren();
    const mode = document.createElement('span');
    mode.className = 'mode';
    const isRetrieval = data.mode === 'retrieval';
    mode.textContent = isRetrieval ? 'Retrieved clauses — semantic' : 'Answered by ' + data.mode + ' · grounded';
    mode.style.cssText = isRetrieval ? 'background:#FFF6E8;border:1px solid #F0D9C6;color:var(--w-muted);padding:3px 8px;border-radius:999px;font-size:12px;font-weight:800' : 'background:#F5F0FF;border:1px solid #E0D9FF;color:var(--w-muted);padding:3px 8px;border-radius:999px;font-size:12px;font-weight:800';
    const answerBody = document.createElement('div');
    answerBody.className = 'markdown-content chat-answer-markdown';
    answerBody.style.marginTop = '10px';
    answerBody.innerHTML = parseMarkdown(data.answer);
    $('#answer').append(mode, answerBody);
    $('#citations').innerHTML = data.citations.map(c => `
      <article style="border-left:3px solid ${c.relevance>40 ? '#9381FF' : '#E0D9B8'};background:${c.relevance>40 ? '#F5F0FF' : '#FFFEFA'};border-radius:8px;padding:10px 14px">
        <strong style="color:var(--w-ink);font-size:12px;letter-spacing:.04em">Clause ${c.clause} · ${c.relevance}% relevant ${c.relevance>40 ? '●' : '○'}</strong>
        <p style="margin:6px 0 0;font-size:13px;line-height:1.6;color:var(--w-ink)">${escapeHTML(c.text).replace(/\n/g,'<br>')}</p>
      </article>
    `).join('');

    $('#answer-card').hidden = false;
    $('#answer-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (error) {
    $('#answer').textContent = error.message;
    $('#answer-card').hidden = false;
  } finally {
    clearInterval(askTick);
    button.disabled = false;
    button.textContent = 'Analyse';
  }
});

// Suggestion buttons click handler
$$('[data-q]').forEach(b => b.onclick = () => {
  $('#question').value = b.dataset.q;
  $('#ask-form').requestSubmit();
});

// Print report handler — prints the VISIBLE result (metadata, highlighted
// entities, entity cards, full report), never the hidden audit JSON.
const printBtn = $('#print-report-btn');
if (printBtn) {
  printBtn.onclick = () => {
    const filename = $('#filename').textContent;
    const metaText = (id) => ((document.getElementById(id) || {}).textContent || '-').trim();
    const metaRows = [
      ['Document', filename],
      ['Document Language', metaText('meta-lang')],
      ['Entities Found', metaText('meta-entities')],
    ].map(([k, v]) => `<tr><th>${escapeHTML(k)}</th><td>${escapeHTML(v)}</td></tr>`).join('');
    // Website-style highlights: copy the colored HTML, not plain text.
    const highlighted = (($('#ner-highlighted-container') || {}).innerHTML || '<p>Not available.</p>');
    const legend = [['PERSON', '#FFDAB9'], ['ORG', '#A0E0E0'], ['GPE', '#FFDC8A'], ['LOC', '#C1F0C1'], ['DATE', '#A8D8EA'], ['MONEY', '#FFB6B6'], ['PERCENT', '#D8BFD8']]
      .map(([k, bg]) => `<span class="lg" style="background:${bg}">${k}</span>`).join('');
    const entCards = [...document.querySelectorAll('#semantic-visual-grid > div')].map((d) =>
      `<div class="ent">${escapeHTML(d.innerText || '').trim().replace(/\n/g, '<br>')}</div>`
    ).join('') || '<p>No entities detected.</p>';
    const fullReport = (typeof englishReport === 'string' && englishReport.trim())
      ? parseMarkdown(englishReport)
      : '<p>Report not available.</p>';
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
      <html>
        <head>
          <title>NER Report - ${escapeHTML(filename)}</title>
          <style>
            body { font-family: 'Plus Jakarta Sans', system-ui, sans-serif; line-height: 1.6; padding: 40px; color: #0B1526; max-width: 800px; margin: 0 auto; }
            h1 { font-size: 26px; letter-spacing: -.02em; border-bottom: 3px solid #6C5CFF; padding-bottom: 10px; }
            h2 { font-size: 18px; margin-top: 28px; color: #3B32B0; }
            table.meta { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; }
            table.meta th, table.meta td { text-align: left; padding: 7px 10px; border: 1px solid #E6EAF2; }
            table.meta th { background: #F4F2FF; width: 180px; }
            .hl { background: #fff; border: 1px solid #E6EAF2; padding: 14px 16px; font-size: 13.5px; line-height: 2; }
            .hl > div { max-height: none !important; overflow: visible !important; }
            .legend { margin: 0 0 10px; }
            .lg { display: inline-block; font-size: 11px; font-weight: 800; padding: 2px 8px; margin: 0 4px 4px 0; border: 1px solid rgba(0,0,0,.08); }
            .ent { border: 1px solid #E6EAF2; padding: 10px 12px; margin-bottom: 8px; font-size: 13px; }
            .report { font-size: 14px; }
            .foot { margin-top: 30px; font-size: 11px; color: #94A3B8; border-top: 1px solid #E6EAF2; padding-top: 10px; }
          </style>
        </head>
        <body>
          <h1>Multilingual NER Report</h1>
          <table class="meta">${metaRows}</table>
          <h2>Highlighted entities</h2>
          <div class="legend">${legend}</div>
          <div class="hl">${highlighted}</div>
          <h2>Entities by type</h2>
          ${entCards}
          <h2>Full report</h2>
          <div class="report">${fullReport}</div>
          <div class="foot">IndicMind · For informational analysis only.</div>
          <script>window.onload = function () { window.print(); };<\/script>
        </body>
      </html>
    `);
    printWindow.document.close();
  };
}

const translateReportBtn = $('#translate-report-btn');
const restoreReportBtn = $('#restore-report-btn');
if (translateReportBtn) {
  translateReportBtn.onclick = async () => {
    const language = $('#report-language').value.trim();
    if (!language) {
      $('#report-language').focus();
      return;
    }
    const label = translateReportBtn.textContent;
    translateReportBtn.disabled = true;
    translateReportBtn.textContent = 'Translating…';
    setAnalysisLoading(true, [
      `Preparing the ${language} report…`,
      'Preserving dates, amounts and clause references…',
      'Translating the plain-language explanation…',
      'Finalizing your translated report…'
    ]);
    try {
      const response = await fetch(`/api/contracts/${contractId}/translate-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language, provider: 'auto' })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not translate this report.');
      $('#report-container').innerHTML = parseMarkdown(data.report);
      // Update NER highlighted view too — was staying English in 2nd image
      const nerC = $('#ner-highlighted-container');
      if (nerC && data.ner_highlighted_html) {
        nerC.innerHTML = data.ner_highlighted_html;
      } else if (nerC && language.toLowerCase().startsWith('hi')) {
        nerC.style.opacity = '0.7';
      }
      // Translate kicker/title: DOCUMENT ANALYSIS → MULTILINGUAL NER
      if (data.kicker) {
        const kickerEl = $('#report-kicker');
        if (kickerEl) kickerEl.textContent = data.kicker;
      }
      if (data.title) {
        const titleEl = $('#report-title');
        if (titleEl) titleEl.textContent = data.title;
      }
      restoreReportBtn.hidden = false;
      translateReportBtn.textContent = `Translated: ${language}`;
    } catch (error) {
      alert(error.message);
    } finally {
      setAnalysisLoading(false);
      translateReportBtn.disabled = false;
      if (!restoreReportBtn || restoreReportBtn.hidden) translateReportBtn.textContent = label;
    }
  };
}
if (restoreReportBtn) {
  restoreReportBtn.onclick = () => {
    $('#report-container').innerHTML = parseMarkdown(englishReport);
    const nerC2 = $('#ner-highlighted-container');
    if (nerC2 && englishNerHtml) nerC2.innerHTML = englishNerHtml;
    if (nerC2) nerC2.style.opacity = '1';
    // Restore original kicker/title
    const kickerEl2 = $('#report-kicker');
    if (kickerEl2) kickerEl2.textContent = kickerEl2.dataset.original;
    const titleEl2 = $('#report-title');
    if (titleEl2) titleEl2.textContent = titleEl2.dataset.original;
    restoreReportBtn.hidden = true;
    translateReportBtn.textContent = 'Translate report';
  };
}

// Workspace tab navigation
function switchTab(tabId) {
  $$('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  $$('.tab-content').forEach(content => {
    content.hidden = content.id !== tabId;
  });
}

$$('.tab-btn').forEach(btn => {
  btn.onclick = () => switchTab(btn.dataset.tab);
});

// Chatbot Drawer & Toggle Interactivity
const chatbotToggle = $('#chatbot-toggle');
const chatbotWidget = $('#chatbot-widget');
const closeChatbot = $('#close-chatbot');
const chatbotForm = $('#chatbot-form');
const chatbotInput = $('#chatbot-input');
const chatbotMessages = $('#chatbot-messages');

if (chatbotToggle) {
  chatbotToggle.addEventListener('click', () => {
    chatbotWidget.hidden = !chatbotWidget.hidden;
    if (!chatbotWidget.hidden && chatbotInput) {
      chatbotInput.focus();
    }
  });
}

if (closeChatbot) {
  closeChatbot.addEventListener('click', () => {
    chatbotWidget.hidden = true;
  });
}

// Quick chips — strong interaction for IndicMind
document.querySelectorAll('.chat-quick').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    const q = btn.dataset.q;
    if(!q) return;
    chatbotInput.value = q;
    chatbotForm.requestSubmit();
    btn.style.transform='scale(0.96)';
    setTimeout(()=>btn.style.transform='',140);
    chatbotInput.focus();
  });
});

if (chatbotForm) {
  chatbotForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = chatbotInput.value.trim();
    if (!query) return;

    const userMsg = document.createElement('div');
    userMsg.className = 'chat-msg user-msg';
    userMsg.replaceChildren(document.createTextNode(query));
    chatbotMessages.appendChild(userMsg);
    chatbotInput.value = '';
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;

    if (contractId) {
      const aiMsg = document.createElement('div');
      aiMsg.className = 'chat-msg ai-msg';
      aiMsg.innerHTML = '<div class="sk sk-l sk-mb" style="width:88%"></div><div class="sk sk-l sk-mb" style="width:64%"></div><div class="sk sk-l" style="width:41%"></div>';
      aiMsg.style.background = '#F5F0FF';
      aiMsg.style.borderColor = '#E0D9FF';
      chatbotMessages.appendChild(aiMsg);
      chatbotMessages.scrollTop = chatbotMessages.scrollHeight;

      try {
        const res = await fetch(`/api/contracts/${contractId}/ask`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: query, provider: 'auto' })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        aiMsg.innerHTML = parseMarkdown(data.answer);
        aiMsg.classList.add('chat-answer-markdown');
      } catch (err) {
        aiMsg.textContent = 'Error: ' + err.message;
      }
    } else {
      const aiMsg = document.createElement('div');
      aiMsg.className = 'chat-msg ai-msg';
      aiMsg.innerHTML = 'Please upload a document in <strong>Hindi, Tamil, Kannada</strong> or any of 20+ Indian languages first — then I\'ll extract <span style="background:#FFDAB9;padding:1px 4px;border-radius:3px">Persons</span> <span style="background:#A0E0E0;padding:1px 4px;border-radius:3px">Orgs</span> <span style="background:#A8D8EA;padding:1px 4px;border-radius:3px">Dates</span> and more for you!';
      aiMsg.style.background = '#FFFEFA';
      aiMsg.style.borderColor = '#F0D9C6';
      chatbotMessages.appendChild(aiMsg);
    }
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;
  });
}

// On document load, fetch the history of contracts and check URL params
document.addEventListener('DOMContentLoaded', () => {
  loadContractsHistory();
  loadProviderStatus();
  const urlParams = new URLSearchParams(window.location.search);
  const idParam = urlParams.get('id');
  if (idParam) {
    loadContractSession(idParam);
  }
});

const uploadProvider = $('#upload-provider');
if (uploadProvider) uploadProvider.addEventListener('change', updateProviderHelp);

// Custom cursor - highly visible ring + dot design
(function () {
  const ring = document.createElement('div');
  ring.style.cssText = [
    'position:fixed',
    'top:0', 'left:0',
    'width:36px', 'height:36px',
    'border-radius:50%',
    'border:2.5px solid rgba(246,219,72,1)',
    'pointer-events:none',
    'z-index:999999',
    'will-change:transform',
    'transition:width .12s ease,height .12s ease,border-color .12s ease,opacity .12s ease',
    'transform:translate(-50%,-50%)',
    'box-shadow:0 0 12px rgba(246,219,72,0.7)',
    'opacity:0',
  ].join(';');

  const dot = document.createElement('div');
  dot.style.cssText = [
    'position:fixed',
    'top:0', 'left:0',
    'width:8px', 'height:8px',
    'border-radius:50%',
    'background:#f6db48',
    'pointer-events:none',
    'z-index:999999',
    'will-change:transform',
    'transform:translate(-50%,-50%)',
    'box-shadow:0 0 6px rgba(246,219,72,0.9)',
    'opacity:0',
  ].join(';');

  document.body.appendChild(ring);
  document.body.appendChild(dot);

  const s = document.createElement('style');
  s.textContent = '*{cursor:none!important}';
  document.head.appendChild(s);

  let cx = -200, cy = -200, rafId = null;

  function move() {
    const tx = `translate(${cx}px,${cy}px)`;
    ring.style.transform = `${tx} translate(-50%,-50%)`;
    dot.style.transform = `${tx} translate(-50%,-50%)`;
    rafId = null;
  }

  function isClickable(el) {
    return el.matches('button,a,label,.dropzone,.upload-title,.upload-subtitle,.upload-icon,select,textarea,.chatbot-toggle-btn,.chatbot-close-btn,.chatbot-send-btn,#chatbot-input,[role="button"],summary,.clause-summary,.citation-tag,.mic-btn,.hint-tag,.voice-cmd-toggle-btn')
      || el.closest('button,a,label,.dropzone,.chatbot-toggle-btn,[role="button"],summary,.clause-summary,.citation-tag,.mic-btn,.hint-tag,.voice-cmd-toggle-btn');
  }

  document.addEventListener('mousemove', e => {
    cx = e.clientX; cy = e.clientY;
    ring.style.opacity = '1';
    dot.style.opacity = '1';

    if (isClickable(e.target)) {
      ring.style.width = '48px';
      ring.style.height = '48px';
      ring.style.borderColor = 'rgba(18,191,162,1)';
      ring.style.boxShadow = '0 0 16px rgba(18,191,162,0.8)';
      dot.style.background = '#12bfa2';
      dot.style.boxShadow = '0 0 8px rgba(18,191,162,0.9)';
    } else {
      ring.style.width = '36px';
      ring.style.height = '36px';
      ring.style.borderColor = 'rgba(246,219,72,1)';
      ring.style.boxShadow = '0 0 12px rgba(246,219,72,0.7)';
      dot.style.background = '#f6db48';
      dot.style.boxShadow = '0 0 6px rgba(246,219,72,0.9)';
    }

    if (!rafId) rafId = requestAnimationFrame(move);
  }, { passive: true });

  document.addEventListener('mousedown', () => {
    ring.style.width = '28px';
    ring.style.height = '28px';
  }, { passive: true });

  document.addEventListener('mouseup', () => {
    ring.style.width = '36px';
    ring.style.height = '36px';
  }, { passive: true });

  document.addEventListener('mouseleave', () => {
    ring.style.opacity = '0';
    dot.style.opacity = '0';
  }, { passive: true });

  document.addEventListener('mouseenter', () => {
    ring.style.opacity = '1';
    dot.style.opacity = '1';
  }, { passive: true });
})();
