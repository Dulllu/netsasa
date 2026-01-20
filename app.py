# app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import uuid

app = FastAPI()

# Allow your frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://netsasa.yourdomain.com"],  # replace with your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Replace these with your Lipana credentials
LIPANA_API_BASE = "https://api.lipana.dev/v1"
LIPANA_API_KEY = "YOUR_LIPANA_API_KEY"  # secure this!

# For storing temporary checkout requests (in-memory)
checkout_requests = {}

class PayRequest(BaseModel):
    phone: str
    amount: float
    packageName: str = None

@app.post("/api/pay")
def pay(req: PayRequest):
    phone = req.phone
    amount = req.amount
    packageName = req.packageName or "NETSASA Wi-Fi"
    
    # Create a unique checkout id for tracking
    checkout_id = str(uuid.uuid4())
    
    # Store initial status
    checkout_requests[checkout_id] = {"status": "pending", "phone": phone, "amount": amount}

    # Make STK Push request to Lipana
    payload = {
        "amount": int(amount),
        "msisdn": phone,
        "callback_url": f"https://netsasa-api.yourdomain.com/api/callback/{checkout_id}",
        "account_reference": packageName,
        "transaction_desc": f"Purchase {packageName}"
    }

    headers = {"Authorization": f"Bearer {LIPANA_API_KEY}"}
    try:
        res = requests.post(f"{LIPANA_API_BASE}/stkpush", json=payload, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data.get("success"):
            raise HTTPException(status_code=400, detail=data.get("message","STK push failed"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STK push error: {e}")

    # Return checkout id to frontend
    return {"success": True, "CheckoutRequestID": checkout_id}

@app.get("/api/check/{checkout_id}")
def check_payment(checkout_id: str):
    # Check in-memory status
    if checkout_id not in checkout_requests:
        raise HTTPException(status_code=404, detail="Checkout ID not found")
    return {"status": checkout_requests[checkout_id]["status"]}

@app.post("/api/callback/{checkout_id}")
def mpesa_callback(checkout_id: str, payload: dict):
    """
    Lipana will POST payment result here.
    Payload example: {"result": "success"} or {"result":"failed"}
    """
    if checkout_id not in checkout_requests:
        return {"error": "Unknown checkout id"}

    result = payload.get("result")
    if result == "success":
        checkout_requests[checkout_id]["status"] = "success"
    else:
        checkout_requests[checkout_id]["status"] = "failed"

    return {"received": True}
