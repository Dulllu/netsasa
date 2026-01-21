from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import os
from lipana import Lipana, LipanaError
import asyncio

# -------------------- FastAPI Setup --------------------
app = FastAPI()

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
WEBHOOK_SECRET = os.getenv(
    "LIPANA_WEBHOOK_SECRET",
    "d7f5efcab4a3db923edfe8f066294c41613052eb95deee681b785f0770a268ed"
)

if not LIPANA_API_KEY:
    raise Exception("LIPANA_API_KEY not set")

lipana = Lipana(
    api_key=LIPANA_API_KEY,
    environment="production"
)

# -------------------- In-memory store --------------------
checkout_store = {}  # CheckoutRequestID -> {status, transaction_id, raw}

# -------------------- Health --------------------
@app.get("/")
def root():
    return {"message": "NETSASA backend alive"}

# -------------------- Initiate Payment --------------------
@app.post("/api/pay")
async def pay(request: Request):
    data = await request.json()
    phone = data.get("phone")
    amount = data.get("amount")

    if not phone or not amount:
        return {"error": "Phone and amount are required"}

    if int(amount) < 10:
        return {"error": "Minimum transaction amount is Ksh 10"}

    try:
        result = lipana.transactions.initiate_stk_push(
            phone=f"+254{phone[-9:]}",
            amount=int(amount)
        )

        checkout_id = result.get("CheckoutRequestID") or result.get("checkoutRequestID")

        if checkout_id:
            checkout_store[checkout_id] = {
                "status": "pending",
                "raw": result
            }
            asyncio.create_task(auto_cancel_payment(checkout_id))

        return {
            "success": True,
            "CheckoutRequestID": checkout_id,
            "transactionId": result.get("transactionId")
        }

    except LipanaError as err:
        return {"error": err.message}

    except Exception as e:
        return {"error": str(e)}

# -------------------- Auto cancel --------------------
async def auto_cancel_payment(checkout_id: str, delay: int = 120):
    await asyncio.sleep(delay)
    if checkout_id in checkout_store:
        if checkout_store[checkout_id]["status"] == "pending":
            checkout_store[checkout_id]["status"] = "cancelled"
            print(f"[AUTO CANCEL] {checkout_id}")

# -------------------- Status Check --------------------
@app.get("/api/check/{checkout_id}")
def check_status(checkout_id: str):
    if checkout_id not in checkout_store:
        return {"status": "not_found"}

    return {
        "status": checkout_store[checkout_id]["status"]
    }

# -------------------- Webhook --------------------
@app.post("/api/webhook")
async def lipana_webhook(request: Request):
    data = await request.json()

    checkout_id = data.get("CheckoutRequestID") or data.get("checkoutRequestID")
    status = data.get("status")
    transaction_id = data.get("transactionId")

    if checkout_id:
        checkout_store[checkout_id] = {
            "status": status,
            "transaction_id": transaction_id,
            "raw": data
        }
        print(f"[WEBHOOK] {checkout_id} -> {status}")

    return {"received": True}
