from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import os
import asyncio
from lipana import Lipana, LipanaError
import json
from typing import Dict

# -------------------- FastAPI Setup --------------------
app = FastAPI(title="NETSASA Backend with SSE")

origins = [
    "https://netsasa.netlify.app",
    "http://localhost:3000"
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
    raise Exception("LIPANA_API_KEY not set in environment variables")

lipana = Lipana(api_key=LIPANA_API_KEY, environment="production")

# -------------------- In-memory store --------------------
checkout_store: Dict[str, Dict] = {}  # {CheckoutRequestID: {"status": str, "transaction_id": str, "raw": dict}}

# SSE subscribers
subscribers: Dict[str, asyncio.Queue] = {}  # checkout_id -> queue


# -------------------- Health Check --------------------
@app.get("/")
def root():
    return {"message": "NETSASA backend with SSE alive"}


# -------------------- Initiate Payment --------------------
@app.post("/api/pay")
async def initiate_payment(request: Request):
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
            checkout_store[checkout_id] = {"status": "pending", "raw": result}
            subscribers[checkout_id] = asyncio.Queue()
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


# -------------------- Auto Cancel --------------------
async def auto_cancel_payment(checkout_id: str, delay: int = 120):
    await asyncio.sleep(delay)
    entry = checkout_store.get(checkout_id)
    if entry and entry["status"] == "pending":
        entry["status"] = "cancelled"
        await notify_subscriber(checkout_id, {"status": "cancelled"})
        print(f"[AUTO CANCEL] {checkout_id} marked as cancelled")


# -------------------- Check Payment Status --------------------
@app.get("/api/check/{checkout_id}")
def check_payment_status(checkout_id: str):
    entry = checkout_store.get(checkout_id)
    if not entry:
        return {"status": "not_found"}
    return {"status": entry["status"]}


# -------------------- Webhook Receiver --------------------
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
        await notify_subscriber(checkout_id, {"status": status})
        print(f"[WEBHOOK] {checkout_id} -> {status}")

    return {"received": True}


# -------------------- SSE Endpoint --------------------
@app.get("/api/stream/{checkout_id}")
async def stream_checkout(checkout_id: str):
    if checkout_id not in subscribers:
        subscribers[checkout_id] = asyncio.Queue()

    async def event_generator():
        queue = subscribers[checkout_id]
        while True:
            try:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.CancelledError:
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# -------------------- Notify Subscriber --------------------
async def notify_subscriber(checkout_id: str, message: dict):
    queue = subscribers.get(checkout_id)
    if queue:
        await queue.put(message)
