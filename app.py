from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
from datetime import datetime
import json
from config import *

app = Flask(__name__)
CORS(app)  # enable CORS for all routes

# ----------------------------------------
# Health check route (for Render)
# ----------------------------------------
@app.route("/")
def home():
    return jsonify({"message": "Netsasa backend is running successfully!"})

# In-memory storage for STK statuses (for demo)
STK_STATUS = {}

# -----------------------
# Generate Access Token
# -----------------------
def get_access_token():
    auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(auth_url, auth=(CONSUMER_KEY, CONSUMER_SECRET))
    data = response.json()
    return data.get("access_token")

# -----------------------
# STK Push Endpoint
# -----------------------
@app.route("/api/pay", methods=["POST"])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone")
        amount = data.get("amount")
        package = data.get("packageName")

        if not phone or not amount:
            return jsonify({"success": False, "message": "Missing phone or amount"}), 400

        if phone.startswith("0"):
            phone = "254" + phone[1:]

        access_token = get_access_token()
        if not access_token:
            return jsonify({"success": False, "message": "Failed to get access token"}), 500

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode((SHORTCODE + PASSKEY + timestamp).encode()).decode()

        stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        payload = {
            "BusinessShortCode": SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": SHORTCODE,
            "PhoneNumber": phone,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": "NETSASA_WIFI",
            "TransactionDesc": f"Buy {package}"
        }

        response = requests.post(stk_url, json=payload, headers=headers)
        res_data = response.json()

        # Log response
        with open("transactions.log", "a") as f:
            f.write(json.dumps(res_data, indent=4) + "\n")

        if response.status_code == 200 and "CheckoutRequestID" in res_data:
            checkout_id = res_data["CheckoutRequestID"]
            # Save initial status
            STK_STATUS[checkout_id] = "pending"
            return jsonify({
                "success": True,
                "message": "STK Push sent successfully",
                "CheckoutRequestID": checkout_id
            })
        else:
            return jsonify({"success": False, "message": "STK request failed", "data": res_data}), 500

    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# -----------------------
# Callback URL
# -----------------------
@app.route("/api/callback", methods=["POST"])
def callback():
    data = request.get_json()
    with open("callback.log", "a") as f:
        f.write(json.dumps(data, indent=4) + "\n")

    print("✅ Callback received from Safaricom:", data)

    # Update STK_STATUS based on callback
    result_code = data.get("Body", {}).get("stkCallback", {}).get("ResultCode", 1)
    checkout_id = data.get("Body", {}).get("stkCallback", {}).get("CheckoutRequestID")
    if checkout_id:
        if result_code == 0:
            STK_STATUS[checkout_id] = "success"
        else:
            STK_STATUS[checkout_id] = "failed"

    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

# -----------------------
# Check STK Status Endpoint
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

