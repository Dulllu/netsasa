from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import os
from lipana import Lipana, LipanaError

# -------------------- FastAPI Setup --------------------
app = FastAPI()

# CORS config (only your frontend)
origins = [
    "https://netsasa.netlify.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Lipana SDK Setup --------------------
LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")
WEBHOOK_SECRET = os.getenv("LIPANA_WEBHOOK_SECRET", "d7f5efcab4a3db923edfe8f066294c41613052eb95deee681b785f0770a268ed")

if not LIPANA_API_KEY:
    raise Exception("LIPANA_API_KEY not set in environment variables.")

lipana = Lipana(
    api_key=LIPANA_API_KEY,
    environment="production"
)

# -------------------- In-memory store --------------------
checkout_store = {}  # key: CheckoutRequestID, value: dict(status, transaction_id, raw_data)

# -------------------- Health Check --------------------
@app.get("/")
def root():
    return {"message": "NETSASA backend (Lipana SDK) alive"}

# -------------------- Initiate Payment --------------------
@app.post("/api/pay")
async def pay(request: Request):
    data = await request.json()
    phone = data.get("phone")
    amount = data.get("amount")
    package_name = data.get("packageName", "NETSASA Wi‑Fi Package")

    # Validation
    if not phone or not amount:
        return {"error": "Phone and amount are required."}
    if int(amount) < 10:
        return {"error": "Minimum transaction amount is Ksh 10."}

    try:
        # Initiate STK push via Lipana SDK
        result = lipana.transactions.initiate_stk_push(
            phone=f"+254{phone[-9:]}",  # ensure +254 format
            amount=int(amount),
            description=package_name
        )

        # Store pending status
        checkout_id = result.get("checkoutRequestID") or result.get("CheckoutRequestID")
        if checkout_id:
            checkout_store[checkout_id] = {"status": "pending", "raw": result}

        return {
            "success": True,
            "transactionId": result.get("transactionId"),
            "CheckoutRequestID": checkout_id
        }

    except LipanaError as err:
        return {"error": err.message}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

# -------------------- Check Payment Status --------------------
@app.get("/api/check/{checkout_id}")
def check_status(checkout_id: str):
    if checkout_id not in checkout_store:
        return {"status": "not_found"}

    return {"status": checkout_store[checkout_id]["status"]}

# -------------------- Webhook Endpoint --------------------
@app.post("/api/webhook")
async def lipana_webhook(request: Request):
    """
    Lipana sends a POST request here for every transaction update.
    This updates checkout_store in real-time.
    """
    data = await request.json()

    # Optional: Verify secret (if Lipana sends it in headers)
    # signature = request.headers.get("X-Lipana-Signature")
    # if signature != WEBHOOK_SECRET:
    #     return {"error": "Invalid webhook signature"}, 400

    checkout_id = data.get("CheckoutRequestID") or data.get("checkoutRequestID")
    status = data.get("status")  # "success", "failed", etc.
    transaction_id = data.get("transactionId")

    if checkout_id:
        checkout_store[checkout_id] = {
            "status": status,
            "transaction_id": transaction_id,
            "raw": data
        }

    return {"received": True}
