from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import json

app = Flask(__name__)
CORS(app)

# -----------------------
# Config from environment
# -----------------------
CALLBACK_URL = os.getenv("CALLBACK_URL")
LIPANA_SECRET = os.getenv("LIPANA_SECRET")
LIPANA_URL = os.getenv("LIPANA_URL")

if not all([CALLBACK_URL, LIPANA_SECRET, LIPANA_URL]):
    print("❌ ERROR: Missing one or more environment variables!")

# -----------------------
# In-memory storage for demo
# -----------------------
STK_STATUS = {}

# -----------------------
# Health check
# -----------------------
@app.route("/")
def home():
    return jsonify({"message": "Netsasa backend is running!"})

# -----------------------
# Normalize phone to 2547XXXXXXXX format
# -----------------------
def normalize_phone(phone: str):
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    elif phone.startswith("7"):
        phone = "254" + phone
    elif phone.startswith("+254"):
        phone = "254" + phone[4:]
    return phone

# -----------------------
# STK Push Endpoint
# -----------------------
@app.route("/api/pay", methods=["POST"])
def pay():
    try:
        data = request.get_json()
        phone = data.get("phone")
        amount = data.get("amount")
        package_name = data.get("packageName", "NETSASA Package")

        if not phone or not amount:
            return jsonify({"success": False, "message": "Missing phone or amount"}), 400

        phone = normalize_phone(phone)

        payload = {
            "phone_number": phone,
            "amount": amount,
            "callback_url": CALLBACK_URL,
            "reference": package_name
        }

        headers = {
            "Authorization": f"Bearer {LIPANA_SECRET}",
            "Content-Type": "application/json"
        }

        print("💡 Sending STK Push to Lipana...")
        print("Payload:", json.dumps(payload))
        print("Headers:", headers)

        response = requests.post(LIPANA_URL, json=payload, headers=headers, timeout=15)
        print("Status code:", response.status_code)
        print("Response:", response.text)

        if response.status_code == 200:
            res_json = response.json()
            checkout_id = res_json.get("checkout_request_id") or res_json.get("CheckoutRequestID")
            if checkout_id:
                STK_STATUS[checkout_id] = "pending"
                return jsonify({
                    "success": True,
                    "message": "STK Push sent successfully",
                    "CheckoutRequestID": checkout_id
                })
            else:
                return jsonify({"success": False, "message": "No CheckoutRequestID in response", "data": res_json}), 500
        else:
            return jsonify({"success": False, "message": "Payment request failed", "data": response.text}), response.status_code

    except Exception as e:
        print("❌ Exception in /api/pay:", str(e))
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# -----------------------
# Callback Endpoint
# -----------------------
@app.route("/api/callback", methods=["POST"])
def callback():
    try:
        data = request.get_json()
        print("✅ Callback received:", json.dumps(data, indent=4))

        checkout_id = data.get("checkout_request_id") or data.get("CheckoutRequestID")
        result_code = data.get("result_code") or data.get("ResultCode")

        if checkout_id:
            if result_code == 0:
                STK_STATUS[checkout_id] = "success"
            else:
                STK_STATUS[checkout_id] = "failed"

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

    except Exception as e:
        print("❌ Exception in /api/callback:", str(e))
        return jsonify({"ResultCode": 1, "ResultDesc": f"Error: {str(e)}"}), 500

# -----------------------
# Check STK Status
# -----------------------
@app.route("/api/check/<checkout_id>", methods=["GET"])
def check_status(checkout_id):
    status = STK_STATUS.get(checkout_id, "pending")
    return jsonify({"success": True, "status": status})

# -----------------------
# Run Server
# -----------------------
if __name__ == "__main__":
    print("🚀 NETSASA Backend running on port 5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
