from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from engine import PrivacyEngine

app = FastAPI()

# Enable CORS so your extension can talk to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = PrivacyEngine()

# 1. Update the Schema to include 'vault'
class RedactRequest(BaseModel):
    text: str
    # Global state passed from the browser
    counts: dict = {
        "PERSON": 0, "LOCATION": 0, "EMAIL_ADDRESS": 0, 
        "PHONE_NUMBER": 0, "PAN_CARD": 0, "IN_AADHAAR": 0, 
        "URI_RESOURCE": 0, "SECRET_TOKEN": 0
    }
    # This is the key to cross-bubble consistency
    vault: dict = {}

# 2. Status check for the Extension Popup
@app.get("/")
async def root():
    return {"status": "online"}

@app.post("/redact")
async def process_text(payload: RedactRequest):
    # 3. Pass text, counts, AND the current vault to the engine
    # This allows the engine to recognize "Pranesh" from previous messages
    result = engine.redact(
        text=payload.text, 
        current_counts=payload.counts, 
        current_vault=payload.vault
    )
    
    return {
        "success": True,
        "data": result
    }

if __name__ == "__main__":
    import uvicorn
    # Using 127.0.0.1 for local dev stability
    uvicorn.run(app, host="127.0.0.1", port=8000)