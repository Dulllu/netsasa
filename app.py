from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests

# -----------------------------
# Load Lipana Live Config
# -----------------------------
LIPANA_SECRET = os.getenv("LIPANA_SECRET")
LIPANA_URL = os.getenv("LIPANA_URL")  # For live, usually https://api.lipana.dev/v1/transactions/push
CALLBACK_URL = os.getenv("CALLBACK_URL")

if not LIPANA_SECRET or not LIPANA_URL or not CALLBACK_URL:
    raise ValueError("Please set LIPANA_SECRET, LIPANA_URL, and CALLBACK_URL in environment variables.")

# In-memory storage for payment statuses
PAYMENT_STATUS = {}

# -----------------------------
# Health Check
# -----------------------------
@app.route("/")
def home():
    return jsonify({"message": "Netsasa backend is running!"})

# -----------------------------
# STK Push Endpoint
# -----------------------------
@app.route("/api/pay", methods=["POST"])
def pay():
    try:
        data = request.get_json()
        phone = data.get("phone")
        amount = data.get("amount")
        package = data.get("packageName")

        if not phone or not amount:
            return jsonify({"success": False, "message": "Missing phone or amount"}), 400

        # Convert 07xxx format to 2547xxx
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        elif phone.startswith("o"):  # in case user types o1
            phone = "254" + phone[1:]

        payload = {
            "amount": amount,
            "phone": phone,
            "callback_url": CALLBACK_URL,
            "description": f"Buy {package}"
        }

        headers = {
            "Authorization": f"Bearer {LIPANA_SECRET}",
            "Content-Type": "application/json"
        }

        response = requests.post(LIPANA_URL, json=payload, headers=headers)
        res_data = response.json()

        # Log response for debugging
        with open("transactions.log", "a") as f:
            f.write(f"{datetime.now()} | {json.dumps(res_data)}\n")

        if response.status_code == 200 and "transaction_id" in res_data:
            tx_id = res_data["transaction_id"]
            PAYMENT_STATUS[tx_id] = "pending"
            return jsonify({"success": True, "message": "STK Push sent successfully", "transaction_id": tx_id})
        else:
            return jsonify({"success": False, "message": "Payment request failed", "data": res_data}), 500

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# -----------------------------
# Callback Endpoint
# -----------------------------
@app.route("/api/callback", methods=["POST"])
def callback():
    data = request.get_json()
    # Log callback
    with open("callback.log", "a") as f:
        f.write(f"{datetime.now()} | {json.dumps(data)}\n")

    tx_id = data.get("transaction_id")
    status = data.get("status")  # success / failed
    if tx_id:
        PAYMENT_STATUS[tx_id] = status

    print(f"✅ Callback received: {tx_id} -> {status}")
    return jsonify({"success": True, "message": "Callback received"})

# -----------------------------
# Check Payment Status
# -----------------------------
@app.route("/api/status/<tx_id>", methods=["GET"])
def status(tx_id):
    status = PAYMENT_STATUS.get(tx_id, "pending")
    return jsonify({"success": True, "status": status})

# -----------------------------
# Run Server
# -----------------------------
if __name__ == "__main__":
    print("🚀 Netsasa Backend running on port 5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
