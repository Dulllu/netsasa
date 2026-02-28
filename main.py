from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import os
import asyncio
import json
from typing import Dict
from lipana import Lipana, LipanaError

# -------------------- FastAPI Setup --------------------
app = FastAPI(title="NETSASA Backend with Lipana SSE")

origins = [
    "https://netsasa-frontend.onrender.com",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Lipana SDK --------------------
LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")
WEBHOOK_SECRET = os.getenv("LIPANA_WEBHOOK_SECRET", "replace_with_secure_secret")

if not LIPANA_API_KEY:
    raise Exception("LIPANA_API_KEY not set in environment variables")

lipana = Lipana(api_key=LIPANA_API_KEY, environment="production")

# -------------------- In-memory store --------------------
checkout_store: Dict[str, Dict] = {}   # checkout_id -> {status, transaction_id, raw}
subscribers: Dict[str, asyncio.Queue] = {}  # checkout_id -> asyncio.Queue()

# -------------------- Health Check --------------------
@app.get("/")
def root():
    return {"message": "NETSASA backend alive"}

# -------------------- Initiate Payment --------------------
@app.post("/api/pay")
async def initiate_payment(request: Request):
    try:
        data = await request.json()
        phone = data.get("phone")
        package_id = data.get("package_id")
        price_map = {
    "p1": 10,
    "p2": 25,
    "p3": 50,
    "p4": 75,
    "p5": 100,
    "p6": 150,
    "p7": 200,
    "p8": 300,
    "p9": 450,
    "p10": 600
}
        amount = price_map.get(package_id)

        if not phone or not package_id or not amount:
            print("[PAY ERROR] Missing phone or invalid package_id:", data)
            return {"error": "Phone and valid package_id are required"}

        print(f"[PAY INIT] Initiating STK push for {phone}, amount={amount}")
        result = lipana.transactions.initiate_stk_push(
            phone=f"+254{phone[-9:]}",
            amount=amount
        )
        print("[PAY RESULT]", result)

        checkout_id = result.get("CheckoutRequestID") or result.get("checkoutRequestID") or result.get("transactionId")
        if not checkout_id:
            print("[PAY ERROR] No checkout ID returned", result)
            return {"error": "Failed to initiate payment. No checkout ID returned."}

        checkout_store[checkout_id] = {"status": "pending", "raw": result}
        subscribers[checkout_id] = asyncio.Queue()
        asyncio.create_task(auto_cancel_payment(checkout_id))

        return {
            "success": True,
            "CheckoutRequestID": checkout_id,
            "transactionId": result.get("transactionId"),
            "message": result.get("message")
        }

    except LipanaError as err:
        print("[PAY EXCEPTION] LipanaError:", err)
        return {"error": err.message}
    except Exception as e:
        print("[PAY EXCEPTION] Exception:", e)
        return {"error": str(e)}

# -------------------- Auto Cancel --------------------
async def auto_cancel_payment(checkout_id: str, delay: int = 120):
    await asyncio.sleep(delay)
    entry = checkout_store.get(checkout_id)
    if entry and entry["status"] == "pending":
        entry["status"] = "cancelled"
        await notify_subscriber(checkout_id, {"status": "cancelled"})
        print(f"[AUTO CANCEL] {checkout_id} cancelled after timeout")

# -------------------- Check Payment Status --------------------
@app.get("/api/check/{checkout_id}")
def check_status(checkout_id: str):
    entry = checkout_store.get(checkout_id)
    if not entry:
        return {"status": "not_found"}
    return {"status": entry["status"]}

# -------------------- Lipana Webhook --------------------
@app.post("/api/webhook")
async def lipana_webhook(request: Request):
    try:
        data = await request.json()
        checkout_id = data.get("CheckoutRequestID") or data.get("checkoutRequestID") or data.get("transactionId")
        status = data.get("status")
        transaction_id = data.get("transactionId")

        if not checkout_id:
            print("[WEBHOOK ERROR] No checkout ID in webhook:", data)
            return {"error": "No checkout ID in webhook"}

        checkout_store[checkout_id] = {
            "status": status,
            "transaction_id": transaction_id,
            "raw": data
        }
        await notify_subscriber(checkout_id, {"status": status})
        print(f"[WEBHOOK] {checkout_id} -> {status}")

        return {"received": True}

    except Exception as e:
        print("[WEBHOOK EXCEPTION]", e)
        return {"error": str(e)}

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
            except Exception as e:
                print("[SSE EXCEPTION]", e)
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# -------------------- Notify Subscriber --------------------
async def notify_subscriber(checkout_id: str, message: dict):
    queue = subscribers.get(checkout_id)
    if queue:
        try:
            await queue.put(message)
        except Exception as e:
            print("[NOTIFY EXCEPTION]", checkout_id, e)

