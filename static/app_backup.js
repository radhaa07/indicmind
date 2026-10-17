let contractId = null;
const $ = (s) => document.querySelector(s);

// Drag and drop functionality
const dropzone = $('.dropzone');
const fileInput = $('#contract');
const selectedFileSpan = $('#selected-file');

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

function displayFileName(name) {
  selectedFileSpan.textContent = name;
  selectedFileSpan.classList.add('show');
}

$('#upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.target.querySelector('button'); button.disabled = true; button.textContent = 'Preparing…';
  $('#upload-error').textContent = '';
  try {
    const response = await fetch('/api/contracts', { method: 'POST', body: new FormData(event.target) });
    const data = await response.json(); if (!response.ok) throw new Error(data.error);
    contractId = data.id; $('#filename').textContent = data.filename;
    $('#risk-card').innerHTML = `<p class="eyebrow">INITIAL REVIEW</p><h2>${data.summary.message}</h2><div class="flags">${data.summary.flags.map(x => `<span>${x}</span>`).join('') || '<span>No common terms flagged</span>'}</div>`;
    const entityList = $('#entity-list'); entityList.replaceChildren();
    data.entities.forEach(group => { const item = document.createElement('article'); const label = document.createElement('strong'); label.textContent = group.type; const values = document.createElement('div'); values.className = 'entity-values'; group.values.forEach(value => { const tag = document.createElement('span'); tag.textContent = value; values.append(tag); }); item.append(label, values); entityList.append(item); });
    $('#entity-card').hidden = data.entities.length === 0;
    $('#upload-card').hidden = true; $('#workspace').hidden = false;
  } catch (error) { $('#upload-error').textContent = error.message; }
  finally { button.disabled = false; button.textContent = 'Prepare contract'; }
});

$('#ask-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const question = $('#question').value.trim(); if (!question) return;
  const button = event.target.querySelector('button'); button.disabled = true; button.textContent = 'Analysing…';
  try {
    const response = await fetch(`/api/contracts/${contractId}/ask`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({question, provider: $('#provider').value})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error);
    $('#answer').replaceChildren(); const mode = document.createElement('span'); mode.className = 'mode'; mode.textContent = data.mode === 'retrieval' ? 'Retrieved clauses' : 'Answered by ' + data.mode; $('#answer').append(mode, document.createTextNode(data.answer)); $('#citations').innerHTML = data.citations.map(c => `<article><strong>Clause ${c.clause} · ${c.relevance}% relevant</strong><p>${c.text}</p></article>`).join(''); $('#answer-card').hidden = false;
  } catch (error) { $('#answer').textContent = error.message; $('#answer-card').hidden = false; }
  finally { button.disabled = false; button.textContent = 'Analyse'; }
});
document.querySelectorAll('[data-q]').forEach(b => b.onclick = () => { $('#question').value = b.dataset.q; $('#ask-form').requestSubmit(); });
$('#new-contract').onclick = () => location.reload();


// Custom cursor effect
(function() {
  // Create cursor element
  const cursor = document.createElement('div');
  cursor.style.cssText = `
    position: fixed;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: rgba(246, 219, 72, 0.6);
    pointer-events: none;
    z-index: 99999;
    transform: translate(-50%, -50%);
    transition: width 0.2s ease, height 0.2s ease;
    mix-blend-mode: screen;
    box-shadow: 0 0 15px rgba(246, 219, 72, 0.8), 0 0 25px rgba(246, 219, 72, 0.5);
  `;
  
  const cursorInner = document.createElement('div');
  cursorInner.style.cssText = `
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 8px;
    height: 8px;
    background: #f6db48;
    border-radius: 50%;
    box-shadow: 0 0 10px #f6db48;
  `;
  cursor.appendChild(cursorInner);
  document.body.appendChild(cursor);

  // Track mouse position
  let mouseX = 0, mouseY = 0, cursorX = 0, cursorY = 0;

  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  // Smooth cursor movement
  function animateCursor() {
    cursorX += (mouseX - cursorX) * 0.15;
    cursorY += (mouseY - cursorY) * 0.15;
    cursor.style.left = cursorX + 'px';
    cursor.style.top = cursorY + 'px';
    requestAnimationFrame(animateCursor);
  }
  animateCursor();

  // Click effect
  document.addEventListener('mousedown', () => {
    cursor.style.width = '30px';
    cursor.style.height = '30px';
    cursor.style.background = 'rgba(246, 219, 72, 0.8)';
  });

  document.addEventListener('mouseup', () => {
    cursor.style.width = '20px';
    cursor.style.height = '20px';
    cursor.style.background = 'rgba(246, 219, 72, 0.6)';
  });

  // Hide default cursor
  document.body.style.cursor = 'none';
  const style = document.createElement('style');
  style.textContent = '* { cursor: none !important; }';
  document.head.appendChild(style);
})();
