document.addEventListener('DOMContentLoaded', async () => {
  const revealBtn = document.getElementById('revealBtn');
  const hideBtn = document.getElementById('hideBtn');
  const clearBtn = document.getElementById('clearBtn');
  const powerToggle = document.getElementById('powerToggle');
  const statusText = document.getElementById('backend-check');
  const entityDisplay = document.getElementById('entityCount');
  const vaultDisplay = document.getElementById('vaultCount');
  const breakdownList = document.getElementById('breakdown-list');

  // --- 1. UI UPDATE LOGIC ---

  function updateUI() {
    chrome.storage.local.get(['globalVault'], (data) => {
      const vault = data.globalVault || {};
      const totalEntities = Object.keys(vault).length;

      // Update the top stat cards
      entityDisplay.innerText = totalEntities;
      vaultDisplay.innerText = totalEntities;

      // Update the Breakdown Section
      renderBreakdown(vault);
    });
  }

  function renderBreakdown(vault) {
    // Count occurrences of each category (e.g., PERSON, EMAIL_ADDRESS)
    const categories = {};
    Object.keys(vault).forEach(tag => {
      // Clean tag: "<PERSON_1>" -> "PERSON"
      const category = tag.replace(/[<>\d_]/g, '');
      categories[category] = (categories[category] || 0) + 1;
    });

    const categoryKeys = Object.keys(categories);

    if (categoryKeys.length > 0) {
      breakdownList.innerHTML = '';
      breakdownList.classList.remove('empty-state');

      categoryKeys.forEach(cat => {
        const item = document.createElement('div');
        item.className = 'breakdown-item';
        // Formatting the name: EMAIL_ADDRESS -> EMAIL ADDRESS
        const displayName = cat.replace(/([A-Z])/g, ' $1').trim();

        item.innerHTML = `
                    <span class="category-name">${displayName}</span>
                    <span class="category-count">${categories[cat]}</span>
                `;
        breakdownList.appendChild(item);
      });
    } else {
      breakdownList.innerHTML = 'No PII detected yet in this session';
      breakdownList.classList.add('empty-state');
    }
  }

  // --- 2. INITIALIZATION ---

  // Health Check
  fetch("http://127.0.0.1:8000/")
    .then(() => {
      statusText.innerText = "ONLINE";
      statusText.style.color = "#34a853";
    })
    .catch(() => {
      statusText.innerText = "OFFLINE";
      statusText.style.color = "#d93025";
    });

  // Load Power State
  chrome.storage.local.get(['isPaused'], (data) => {
    powerToggle.checked = !data.isPaused;
    if (data.isPaused) {
      statusText.innerText = "PAUSED";
      statusText.style.opacity = "0.5";
    }
  });

  // Run initial UI Sync
  updateUI();

  // --- 3. EVENT LISTENERS ---

  powerToggle.addEventListener('change', () => {
    const isPaused = !powerToggle.checked;
    chrome.storage.local.set({ isPaused: isPaused });

    if (isPaused) {
      statusText.innerText = "PAUSED";
      statusText.style.color = "#707a8a";
      statusText.style.opacity = "0.5";
    } else {
      statusText.innerText = "ONLINE";
      statusText.style.color = "#34a853";
      statusText.style.opacity = "1";
    }
  });

  revealBtn.addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const { globalVault } = await chrome.storage.local.get('globalVault');
    if (!globalVault || Object.keys(globalVault).length === 0) return;

    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (vault) => {
        const walk = (node) => {
          if (node.nodeType === 3) {
            Object.entries(vault).forEach(([tag, original]) => {
              node.textContent = node.textContent.replaceAll(tag, original);
            });
          } else if (node.nodeType === 1 && !['SCRIPT', 'STYLE'].includes(node.tagName)) {
            node.childNodes.forEach(walk);
          }
        };
        walk(document.body);
      },
      args: [globalVault]
    });
  });

  hideBtn.addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const { globalVault } = await chrome.storage.local.get('globalVault');

    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (vault) => {
        const walk = (node) => {
          if (node.nodeType === 3) {
            Object.entries(vault).forEach(([tag, original]) => {
              node.textContent = node.textContent.replaceAll(original, tag);
            });
          } else if (node.nodeType === 1 && !['SCRIPT', 'STYLE'].includes(node.tagName)) {
            node.childNodes.forEach(walk);
          }
        };
        walk(document.body);
      },
      args: [globalVault]
    });
  });

  clearBtn.addEventListener('click', () => {
    if (confirm("Permanently clear the session vault?")) {
      chrome.storage.local.set({ globalVault: {}, currentCounts: {} }, () => {
        updateUI();
      });
    }
  });
});

