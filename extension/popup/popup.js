const SERVER = 'http://127.0.0.1:8000/';
const SUPPORTED_TYPES = 11; // keep in sync with backend/main.py default counts

document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  const powerToggle = $('powerToggle');
  const statusBar = $('statusBar');
  const statusLabel = $('statusLabel');
  const statusHint = $('statusHint');
  const toast = $('toast');
  let serverUp = false;
  let paused = false;
  let toastTimer;

  $('supportedCount').textContent = SUPPORTED_TYPES;

  // "<EMAIL_ADDRESS_2>" -> "EMAIL_ADDRESS"
  const categoryOf = (tag) => (tag.match(/^<(.+)_\d+>$/) || [, tag])[1];
  const prettyName = (cat) =>
    cat.toLowerCase().split('_').map((w) => (w === 'ip' || w === 'pan') ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)).join(' ');
  const mask = (v) => v.length <= 4 ? '••••' : v.slice(0, 2) + '•'.repeat(Math.min(v.length - 3, 10)) + v.slice(-1);

  function showToast(msg) {
    toast.textContent = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.textContent = ''), 2500);
  }

  // ---------- status ----------
  function renderStatus() {
    statusBar.className = 'status';
    statusHint.textContent = '';
    if (!serverUp) {
      statusBar.classList.add('offline');
      statusLabel.textContent = 'Backend offline';
      statusHint.innerHTML = 'Start it: <code>cd backend</code> then <code>python -m uvicorn main:app</code>';
    } else if (paused) {
      statusBar.classList.add('paused');
      statusLabel.textContent = 'Paused';
      statusHint.textContent = 'Messages are sent as-is. Flip the switch to protect them.';
    } else {
      statusBar.classList.add('active');
      statusLabel.textContent = 'Active';
      statusHint.textContent = 'Your prompts are scrubbed before sending.';
    }
  }

  async function checkServer() {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      await fetch(SERVER, { signal: ctrl.signal });
      clearTimeout(t);
      serverUp = true;
    } catch { serverUp = false; }
    renderStatus();
  }

  // ---------- vault rendering ----------
  function render(vault) {
    const tags = Object.keys(vault);
    $('entityCount').textContent = tags.length;

    const counts = {};
    tags.forEach((t) => { const c = categoryOf(t); counts[c] = (counts[c] || 0) + 1; });
    const cats = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    $('typeCount').textContent = cats.length;

    const list = $('breakdown-list');
    list.textContent = '';
    if (!cats.length) {
      list.className = 'empty-state';
      list.textContent = 'No PII detected yet';
    } else {
      list.className = '';
      const max = Math.max(...Object.values(counts));
      cats.forEach((c) => {
        const row = document.createElement('div');
        row.className = 'breakdown-item';
        const name = document.createElement('span');
        name.textContent = prettyName(c);
        const bar = document.createElement('div');
        bar.className = 'bar';
        const fill = document.createElement('span');
        fill.style.width = (counts[c] / max) * 100 + '%';
        bar.appendChild(fill);
        const n = document.createElement('span');
        n.className = 'category-count';
        n.textContent = counts[c];
        row.append(name, bar, n);
        list.appendChild(row);
      });
    }

    const vl = $('vaultList');
    vl.textContent = '';
    tags.forEach((tag) => {
      const li = document.createElement('li');
      li.className = 'vault-row';
      const t = document.createElement('span');
      t.className = 'vault-tag';
      t.textContent = tag;
      const v = document.createElement('span');
      v.className = 'vault-val';
      v.textContent = mask(vault[tag]);
      const b = document.createElement('button');
      b.className = 'eye';
      b.textContent = 'Show';
      b.setAttribute('aria-label', 'Show or hide value for ' + tag);
      let shown = false;
      b.addEventListener('click', () => {
        shown = !shown;
        v.textContent = shown ? vault[tag] : mask(vault[tag]);
        b.textContent = shown ? 'Hide' : 'Show';
      });
      li.append(t, v, b);
      vl.appendChild(li);
    });
    $('clearBtn').disabled = !tags.length;
  }

  const refresh = () =>
    chrome.storage.local.get(['globalVault'], (d) => render(d.globalVault || {}));

  // ---------- page reveal / hide ----------
  async function swapOnPage(direction) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const { globalVault } = await chrome.storage.local.get('globalVault');
    if (!tab || !globalVault || !Object.keys(globalVault).length) return showToast('Vault is empty.');
    // longest first so "<PERSON_1>" never clobbers "<PERSON_10>"
    const pairs = Object.entries(globalVault).sort((a, b) =>
      direction === 'reveal' ? b[0].length - a[0].length : b[1].length - a[1].length);
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (pairs, dir) => {
          const walk = (node) => {
            if (node.nodeType === 3) {
              let s = node.textContent;
              pairs.forEach(([tag, orig]) => {
                s = dir === 'reveal' ? s.replaceAll(tag, orig) : s.replaceAll(orig, tag);
              });
              if (s !== node.textContent) node.textContent = s;
            } else if (node.nodeType === 1 && !['SCRIPT', 'STYLE', 'TEXTAREA'].includes(node.tagName)) {
              node.childNodes.forEach(walk);
            }
          };
          walk(document.body);
        },
        args: [pairs, direction],
      });
      showToast(direction === 'reveal' ? 'Revealed on this page.' : 'Hidden on this page.');
    } catch { showToast("Can't run on this tab."); }
  }

  // ---------- events ----------
  powerToggle.addEventListener('change', () => {
    paused = !powerToggle.checked;
    chrome.storage.local.set({ isPaused: paused });
    renderStatus();
  });
  $('revealBtn').addEventListener('click', () => swapOnPage('reveal'));
  $('hideBtn').addEventListener('click', () => swapOnPage('hide'));

  $('clearBtn').addEventListener('click', () => {
    $('confirmRow').hidden = false;
    $('clearBtn').hidden = true;
  });
  $('confirmNo').addEventListener('click', () => {
    $('confirmRow').hidden = true;
    $('clearBtn').hidden = false;
  });
  $('confirmYes').addEventListener('click', () => {
    chrome.storage.local.set({ globalVault: {}, currentCounts: {} }, () => {
      $('confirmRow').hidden = true;
      $('clearBtn').hidden = false;
      showToast('Vault cleared.');
    });
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes.globalVault) refresh();
  });

  // ---------- init ----------
  chrome.storage.local.get(['isPaused'], (d) => {
    paused = !!d.isPaused;
    powerToggle.checked = !paused;
    renderStatus();
  });
  refresh();
  checkServer();
  setInterval(checkServer, 5000);
});
