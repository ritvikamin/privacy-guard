/**
 * Privacy Guard: Interceptor Script
 *
 * Catches BOTH ways of sending a prompt:
 *   1. pressing Enter in the chat box
 *   2. clicking the site's Send button
 * Then redacts the text (via background.js -> local server) and sends the clean version.
 */

// ---------------------------------------------------------------------------
// Per-site config: the ONLY place that knows how each site's page is built.
// If a site changes its layout, edit the selectors here. To support a new site,
// add one entry here (and its URL to manifest.json).
// An empty `input` list is fine: the chat box is then found structurally, from the
// Send button's own form, which does not depend on any ID the site could rename.
// ---------------------------------------------------------------------------
const SITES = {
    "chatgpt.com": {
        input: [],   // no verified selector yet: the box is found structurally (see findPromptBox)
        sendButton: ['button[data-testid="send-button"]', 'button[aria-label*="Send"]']
    },
    "gemini.google.com": {
        input: ['rich-textarea .ql-editor', '.ql-editor'],
        sendButton: ['button[aria-label*="Send"]', 'button.send-button']
    }
};

const SITE = SITES[location.hostname] || { input: [], sendButton: [] };
const INPUT_SELECTOR = SITE.input.join(', ');
const SEND_SELECTOR = SITE.sendButton.join(', ');

const PLACEHOLDER = "Processing Privacy...";
const DEFAULT_COUNTS = {
    "PERSON": 0, "LOCATION": 0, "EMAIL_ADDRESS": 0, "PHONE_NUMBER": 0,
    "PAN_CARD": 0, "IN_AADHAAR": 0, "URI_RESOURCE": 0, "SECRET_TOKEN": 0, "IP_ADDRESS": 0
};

let isPausedLocal = false;   // popup toggle
let busy = false;            // a redaction is already in progress
let bypassGuard = false;     // true only while WE click Send, so we don't intercept ourselves

// 1. Pause state: initial sync + live updates from the popup
chrome.storage.local.get(['isPaused'], (data) => {
    isPausedLocal = data.isPaused || false;
});
chrome.storage.onChanged.addListener((changes) => {
    if (changes.isPaused) {
        isPausedLocal = changes.isPaused.newValue;
        console.log(`Privacy Guard: Protection is now ${isPausedLocal ? 'OFF' : 'ON'}`);
    }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns the prompt box element for `el`, or null if `el` isn't the chat box. */
function getPromptBox(el) {
    if (!el || !el.closest) return null;
    // Normal case: the site config matches something on the page, so be precise.
    if (INPUT_SELECTOR && document.querySelector(INPUT_SELECTOR)) {
        return el.closest(INPUT_SELECTOR);
    }
    // Config is stale or the site is unknown: fall back to "any editable box".
    const editable = el.isContentEditable || el.tagName === 'TEXTAREA' || el.getAttribute('role') === 'textbox';
    return editable ? el : null;
}

/** Remembers the last editable box the user focused (a mouse click on Send moves focus away). */
let lastEditable = null;
document.addEventListener('focusin', (e) => {
    const t = e.target;
    if (t && t.getAttribute && (t.isContentEditable || t.tagName === 'TEXTAREA' || t.getAttribute('role') === 'textbox')) {
        lastEditable = t;
    }
}, true);

/**
 * Finds the chat box when the user clicked Send with the mouse. Tries, in order:
 *   1. the site config selector
 *   2. the editable box inside the same <form>/composer as the Send button (structural, survives ID renames)
 *   3. the last editable box the user focused
 *   4. the currently focused element
 */
function findPromptBox(fromButton) {
    if (INPUT_SELECTOR) {
        const el = document.querySelector(INPUT_SELECTOR);
        if (el) return el;
    }
    const form = fromButton && fromButton.closest ? fromButton.closest('form') : null;
    if (form) {
        const el = form.querySelector('[contenteditable="true"]') || form.querySelector('textarea') || form.querySelector('[role="textbox"]');
        if (el) return el;
    }
    if (lastEditable && lastEditable.isConnected) return lastEditable;
    return getPromptBox(document.activeElement);
}

/** Reads the prompt text. innerText keeps line breaks for rich editors. */
function readText(box) {
    return (box.tagName === 'TEXTAREA' ? box.value : box.innerText)
        .replace(/ /g, " ")
        .normalize("NFC")
        .trim();
}

/** Writes text the way real typing would, so the site's editor updates its internal state. */
function setText(box, text) {
    box.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
}

/** Waits until the site's Send button exists and is enabled, then clicks it. */
function clickSendWhenReady(timeoutMs = 3000) {
    return new Promise((resolve) => {
        const started = Date.now();
        const timer = setInterval(() => {
            const btn = SEND_SELECTOR ? document.querySelector(SEND_SELECTOR) : null;
            const ready = btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true';
            if (ready) {
                clearInterval(timer);
                bypassGuard = true;            // let our own click through
                try { btn.click(); } finally { bypassGuard = false; }
                console.log("Privacy Guard: Redacted message sent.");
                resolve(true);
            } else if (Date.now() - started > timeoutMs) {
                clearInterval(timer);
                console.warn("Privacy Guard: Send button not found. The redacted text is in the box; press Send.");
                resolve(false);
            }
        }, 50);
    });
}

// ---------------------------------------------------------------------------
// Entry point 1: Enter key (capture phase = we run before the site's own handlers)
// ---------------------------------------------------------------------------
document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    if (bypassGuard || isPausedLocal) return;

    const box = getPromptBox(document.activeElement);
    if (!box) return;

    event.stopImmediatePropagation();
    event.preventDefault();
    processAndSend(box);
}, true);

// ---------------------------------------------------------------------------
// Entry point 2: Send button click (this was the leak: only Enter was caught before)
// ---------------------------------------------------------------------------
document.addEventListener('click', (event) => {
    if (bypassGuard || isPausedLocal) return;

    const clicked = event.target && event.target.closest ? event.target.closest(SEND_SELECTOR || 'x-none') : null;
    if (!clicked) return;

    const box = findPromptBox(clicked);
    if (!box || !readText(box)) return;   // nothing typed, nothing to protect

    event.stopImmediatePropagation();
    event.preventDefault();
    processAndSend(box);
}, true);

// ---------------------------------------------------------------------------
// The redaction pipeline (shared by both entry points)
// ---------------------------------------------------------------------------
function processAndSend(inputBox) {
    if (busy) return;

    const rawText = readText(inputBox);
    if (!rawText || rawText === PLACEHOLDER) return;

    busy = true;
    setText(inputBox, PLACEHOLDER);   // visible feedback

    chrome.storage.local.get(['globalVault', 'currentCounts'], (store) => {
        const vault = store.globalVault || {};
        const counts = store.currentCounts || { ...DEFAULT_COUNTS };

        chrome.runtime.sendMessage({
            type: "REDACT_TEXT",
            text: rawText,
            counts: counts,
            vault: vault
        }, (response) => {
            void chrome.runtime.lastError;   // mark as handled (e.g. extension was reloaded)

            if (response && response.success && response.data) {
                const result = response.data;
                chrome.storage.local.set({
                    globalVault: result.vault,
                    currentCounts: result.updated_counts
                }, async () => {
                    setText(inputBox, result.redacted);
                    inputBox.dispatchEvent(new Event('input', { bubbles: true }));
                    await clickSendWhenReady();
                    busy = false;
                });
            } else {
                // Server unreachable: put the user's text back untouched (nothing is sent).
                setText(inputBox, rawText);
                inputBox.dispatchEvent(new Event('input', { bubbles: true }));
                busy = false;
            }
        });
    });
}
