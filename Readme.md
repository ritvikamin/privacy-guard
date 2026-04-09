## 🚦 Getting Started

### 1. Setup Backend (The Engine)
It is highly recommended to use a virtual environment to keep dependencies isolated.

```bash
# Navigate to backend folder
cd backend

# Create a virtual environment
python -m venv venv

# Activate it
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the FastAPI server
uvicorn main:app --reload