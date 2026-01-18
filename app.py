from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
from datetime import datetime
from config import *

app = Flask(__name__)
CORS(app)  # enable CORS for all routes

# ----------------------------------------
# Health check route
# ----------------------------------------
@app.route("/")
def home():
    return jsonify({"message": "Netsasa backend is running successfully!"})

# In-memory storage for transactions
TX_STATUS = {}

# -----------------------
# STK Push / Payment Endpoint (Lipana LIVE)
# -----------------------
@app.route("/api/pay", methods=["POST"])
def pay():
    try:
        data = request.get_json()
        phone = data.get("phone")
        amount = data.get("amount")
        package = data.get("packageName")

        if not phone or not amount:
            return jsonify({"success": False, "message": "Missing phone or amount"}), 400

        # Convert 07 or 01 to 254 prefix
        if phone.startswith("0"):
            phone = "254" + phone[1:]

        payload = {
            "phone": phone,
            "amount": amount,
            "package": package
        }

        headers = {
            "Authorization": f"Bearer {LIPANA_SECRET}",
            "Content-Type": "application/json"
        }

        response = requests.post(LIPANA_URL, json=payload, headers=headers)
        res_data = response.json()

        # Log transactions
        with open("transactions.log", "a") as f:
            f.write(json.dumps(res_data, indent=4) + "\n")

        if response.status_code == 200 and res_data.get("transactionId"):
            tx_id = res_data["transactionId"]
            TX_STATUS[tx_id] = "pending"
            return jsonify({
                "success": True,
                "message": "Payment request sent successfully",
                "transactionId": tx_id
            })
        else:
            return jsonify({"success": False, "message": "Payment request failed", "data": res_data}), 500

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# -----------------------
# Callback from Lipana
# -----------------------
@app.route("/api/callback", methods=["POST"])
def callback():
    data = request.get_json()
    with open("callback.log", "a") as f:
        f.write(json.dumps(data, indent=4) + "\n")

    print("✅ Callback received from Lipana:", data)

    tx_id = data.get("transactionId")
    status = data.get("status")  # Lipana might return "success" or "failed"

    if tx_id:
        TX_STATUS[tx_id] = status or "failed"

    return jsonify({"result": "accepted"}), 200

# -----------------------
# Check Payment Status
# -----------------------
@app.route("/api/check/<tx_id>", methods=["GET"])
def check_status(tx_id):
    status = TX_STATUS.get(tx_id, "pending")
    return jsonify({"success": True, "status": status})

# -----------------------
# Run Server
# -----------------------
if __name__ == "__main__":
    print("🚀 NETSASA Backend running on port 5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
