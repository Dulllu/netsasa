from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import os
from lipana import Lipana, LipanaError

# Initialize FastAPI
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

# Lipana SDK setup
LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")
if not LIPANA_API_KEY:
    raise Exception("LIPANA_API_KEY not set in environment variables.")

lipana = Lipana(
    api_key=LIPANA_API_KEY,
    environment="production"
)

# In‑memory store for status (small‑scale / demo)
checkout_store = {}

@app.get("/")
def root():
    return {"message": "NETSASA backend (Lipana SDK) alive"}

@app.post("/api/pay")
async def pay(request: Request):
    data = await request.json()
    phone = data.get("phone")
    amount = data.get("amount")
    package_name = data.get("packageName", "NETSASA Wi‑Fi Package")

    # Validate
    if not phone or not amount:
        return {"error": "Phone and amount are required."}

    try:
        # Initiate STK push via SDK
        result = lipana.transactions.initiate_stk_push(
            phone=f"+254{phone[-9:]}",  # ensure +254 format
            amount=int(amount)
        )

        # Store pending status
        checkout_id = result.get("checkoutRequestID") or result.get("CheckoutRequestID")
        if checkout_id:
            checkout_store[checkout_id] = {"status": "pending"}
        return {
            "success": True,
            "transactionId": result.get("transactionId"),
            "CheckoutRequestID": checkout_id
        }

    except LipanaError as err:
        # Friendly error info
        return {"error": err.message}

    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@app.get("/api/check/{checkout_id}")
def check_status(checkout_id: str):
    # If not tracked in memory yet
    if checkout_id not in checkout_store:
        return {"status": "not_found"}

    try:
        # Use SDK to check latest status
        status_resp = lipana.transactions.retrieve(checkout_id)
        status = status_resp.get("status") or checkout_store[checkout_id]["status"]
        checkout_store[checkout_id]["status"] = status
        return {"status": status}
    except LipanaError as err:
        return {"error": err.message}
    except Exception as e:
        return {"error": str(e)}
