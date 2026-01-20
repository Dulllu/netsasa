from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
from dotenv import load_dotenv

# Load local .env (optional, Render will use env vars)
load_dotenv()

app = FastAPI()

# Allow your frontend domain
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

# Lipana STK Push
LIPANA_API_URL = "https://api.lipana.dev/v1/stkpush"
LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")

if not LIPANA_API_KEY:
    print("WARNING: LIPANA_API_KEY not set. STK Push won't work.")

@app.get("/")
async def root():
    return {"message": "NETSASA backend alive"}

@app.post("/api/pay")
async def pay(request: Request):
    data = await request.json()
    phone = data.get("phone")
    amount = data.get("amount")
    package_name = data.get("packageName", "Package")

    if not phone or not amount:
        return {"error": "Phone and amount are required"}

    if not LIPANA_API_KEY:
        return {"error": "Server not configured with LIPANA_API_KEY"}

    payload = {
        "apiKey": LIPANA_API_KEY,
        "phone": phone,
        "amount": amount,
        "account": package_name
    }

    try:
        resp = requests.post(LIPANA_API_URL, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return {"success": True, "CheckoutRequestID": result.get("CheckoutRequestID")}
    except requests.exceptions.RequestException as e:
        print("STK Push ERROR:", e)
        try:
            # Print Lipana response if available
            print("Response content:", e.response.content if e.response else "No response")
        except:
            pass
        return {"error": "Failed to initiate payment. See server logs for details."}
