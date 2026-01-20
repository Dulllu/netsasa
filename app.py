from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import uuid

app = FastAPI()

# Allow your Netlify frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://netsasa.netlify.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Lipana API config ----------------
LIPANA_API_BASE = "https://api.lipana.dev/v1"
LIPANA_API_KEY = "YOUR_LIPANA_API_KEY"  # Replace with your real API key

# In-memory storage for checkout status
checkout_requests = {}

# ---------------- Models ----------------
class PayRequest(BaseModel):
    phone: str
    amount: float
    packageName: str = None

# ---------------- API Endpoints ----------------
@app.post("/api/pay")
def pay(req: PayRequest):
    phone = req.phone
    amount = req.amount
    packageName = req.packageName or "NETSASA Wi-Fi"

    # Unique checkout ID
    checkout_id = str(uuid.uuid4())

    # Store initial status
    checkout_requests[checkout_id] = {"status": "pending", "phone": phone, "amount": amount}

    # STK Push payload
    payload = {
        "amount": int(amount),
        "msisdn": phone,
        "callback_url": f"https://netsasa-backend.onrender.com/api/callback/{checkout_id}",
        "account_reference": packageName,
        "transaction_desc": f"Purchase {packageName}"
    }

    headers = {"Authorization": f"Bearer {LIPANA_API_KEY}"}

    try:
        res = requests.post(f"{LIPANA_API_BASE}/stkpush", json=payload, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data.get("success"):
            raise HTTPException(status_code=400, detail=data.get("message", "STK push failed"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STK push error: {e}")

    # Return checkout ID for frontend polling
    return {"success": True, "CheckoutRequestID": checkout_id}

@app.get("/api/check/{checkout_id}")
def check_payment(checkout_id: str):
    if checkout_id not in checkout_requests:
        raise HTTPException(status_code=404, detail="Checkout ID not found")
    return {"status": checkout_requests[checkout_id]["status"]}

@app.post("/api/callback/{checkout_id}")
async def mpesa_callback(checkout_id: str, request: Request):
    """
    Lipana will POST payment result here.
    Expected JSON payload: {"result": "success"} or {"result": "failed"}
    """
    if checkout_id not in checkout_requests:
        return {"error": "Unknown checkout id"}

    payload = await request.json()
    result = payload.get("result")
    if result == "success":
        checkout_requests[checkout_id]["status"] = "success"
    else:
        checkout_requests[checkout_id]["status"] = "failed"

    return {"received": True}

