/**
 * Privacy Guard: Interceptor Script
 * Optimized for state synchronization and newline preservation.
 */

let isPausedLocal = false;

// 1. Initial State Sync
chrome.storage.local.get(['isPaused'], (data) => {
    isPausedLocal = data.isPaused || false;
});

// 2. Real-time Sync
chrome.storage.onChanged.addListener((changes) => {
    if (changes.isPaused) {
        isPausedLocal = changes.isPaused.newValue;
        console.log(`Privacy Guard: Protection is now ${isPausedLocal ? 'OFF' : 'ON'}`);
    }
});

/**
 * Global Event Listener (Capture Phase)
 */
document.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
        
        if (isPausedLocal) return;

        const activeElem = document.activeElement;
        const isInput = activeElem.isContentEditable || 
                        activeElem.tagName === 'TEXTAREA' || 
                        activeElem.getAttribute('role') === 'textbox';

        if (activeElem && isInput) {
            // Check for Gemini or ChatGPT input areas
            const isLLMInput = activeElem.placeholder?.toLowerCase().includes("prompt") || 
                               activeElem.closest('[contenteditable="true"]') ||
                               window.location.hostname.includes("chatgpt.com");

            if (isLLMInput) {
                // BLOCK NATIVE SEND
                event.stopImmediatePropagation();
                event.preventDefault();
                
                processAndSend(activeElem);
            }
        }
    }
}, true);

async function processAndSend(inputBox) {
    // 1. CAPTURE: innerText is best for getting multiline strings from contenteditables
    let rawText = (inputBox.tagName === 'TEXTAREA' ? inputBox.value : inputBox.innerText)
                   .replace(/\u00a0/g, " ")
                   .normalize("NFC")
                   .trim();

    if (!rawText || rawText === "Processing Privacy...") return;

    // 2. STATUS FEEDBACK: Use execCommand to "type" the status
    // This clears the box and tells the site "something changed"
    inputBox.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, "Processing Privacy...");

    chrome.storage.local.get(['globalVault', 'currentCounts'], (store) => {
        const vault = store.globalVault || {};
        const counts = store.currentCounts || {
            "PERSON": 0, "LOCATION": 0, "EMAIL_ADDRESS": 0,
            "PHONE_NUMBER": 0, "PAN_CARD": 0, "IN_AADHAAR": 0,
            "URI_RESOURCE": 0, "SECRET_TOKEN": 0
        };

        // 3. Send to Background -> Backend
        chrome.runtime.sendMessage({ 
            type: "REDACT_TEXT", 
            text: rawText, 
            counts: counts,
            vault: vault 
        }, (response) => {
            if (response && response.success && response.data) {
                const result = response.data; 

                chrome.storage.local.set({
                    globalVault: result.vault,
                    currentCounts: result.updated_counts
                }, () => {
                    // 4. THE FIX: Focus and "Type" the redacted text
                    // This preserves newlines perfectly and doesn't break Gemini's UI
                    inputBox.focus();
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, result.redacted);

                    // Force the site to recognize the change
                    inputBox.dispatchEvent(new Event('input', { bubbles: true }));

                    // 5. Trigger Native Send
                    setTimeout(() => {
                        const sendBtn = document.querySelector(
                            'button[aria-label*="Send"], [data-testid*="send"], .send-button, [aria-label="Send prompt"]'
                        );
                        if (sendBtn) {
                            sendBtn.click();
                            console.log("Privacy Guard: Redacted message sent.");
                        }
                    }, 250); 
                });
            } else {
                // Recovery: Put back what we had
                inputBox.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, rawText);
                inputBox.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
    });
}