/**
 * Privacy Guard: Background Service Worker
 * Handles the bridge between the browser and the Python FastAPI backend.
 * Updated for Global Session Vault and Stateful Indexing.
 */

// 1. The Redaction Bridge
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "REDACT_TEXT") {
        console.log("Privacy Guard: Request received. Sending to Local Brain...");

        // Connect to the FastAPI server
        // Now includes 'counts' in the request body for stateful indexing
        fetch("http://127.0.0.1:8000/redact", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ 
                text: request.text,
                counts: request.counts, // Point 4: Passing the global index state
                vault: request.vault
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log("Privacy Guard: Redaction complete.");
            
            /**
             * FIX FOR 'UNDEFINED' ERROR:
             * Our FastAPI returns: { "success": true, "data": { "redacted": "...", "vault": {...} } }
             * We send just the inner 'data' object back to interceptor.js
             */
            if (data.success && data.data) {
                sendResponse({ success: true, data: data.data });
            } else {
                // Fallback for different response structures
                sendResponse({ success: true, data: data });
            }
        })
        .catch(error => {
            console.error("Privacy Guard Error (Local Server):", error);
            sendResponse({ success: false, error: error.message });
        });

        // CRITICAL: Tells Chrome to keep the message port open 
        // because we are waiting for an async fetch() result.
        return true; 
    }
});

// 2. The Persistence Heartbeat
// Service Workers sleep after 30s of inactivity. This keeps it "warm."
chrome.alarms.create('keepAlive', { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'keepAlive') {
        // Silent heartbeat to keep the background script ready
    }
});

// 3. Extension Lifecycle
chrome.runtime.onInstalled.addListener(() => {
    // Initialize global storage if it doesn't exist
    chrome.storage.local.get(['globalVault', 'currentCounts'], (result) => {
        if (!result.globalVault) {
            chrome.storage.local.set({ 
                globalVault: {},
                currentCounts: {
                    "PERSON": 0, "LOCATION": 0, "EMAIL_ADDRESS": 0, 
                    "PHONE_NUMBER": 0, "PAN_CARD": 0, "IN_AADHAAR": 0, 
                    "URI_RESOURCE": 0, "SECRET_TOKEN": 0, "IP_ADDRESS": 0
                }
            });
        }
    });
    console.log("Privacy Guard: Extension Loaded & Global Vault Initialized.");
});