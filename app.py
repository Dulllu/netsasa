from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, os, json, traceback

app = Flask(__name__)
CORS(app)  # allow frontend cross-origin requests

# ----------------------------
# Lipana Config
# ----------------------------
LIPANA_SECRET = os.getenv("LIPANA_SECRET")
LIPANA_URL = os.getenv("LIPANA_URL")
CALLBACK_URL = os.getenv("CALLBACK_URL")  # Lipana should POST here

if not LIPANA_SECRET or not LIPANA_URL:
    raise ValueError("Please set LIPANA_SECRET and LIPANA_URL in environment variables.")

# ----------------------------
# In-memory storage for demo
# ----------------------------
TX_STATUS = {}  # {transaction_id: "pending"|"success"|"failed"}

# ----------------------------
# Health check
# ----------------------------
@app.route("/")
def home():
    return jsonify({"message": "Netsasa backend (Lipana) is running successfully!"})

# ----------------------------
# Payment endpoint
# ----------------------------
@app.route("/api/pay", methods=["POST"])
def pay():
    try:
        data = request.get_json()
        phone = data.get("phone")
        amount = data.get("amount")
        package = data.get("packageName")

        if not phone or not amount:
            return jsonify({"success": False, "message": "Missing phone or amount"}), 400

        # Prepare payload for Lipana
        payload = {
            "amount": amount,
            "phone": phone,
            "package": package,
            "callback_url": CALLBACK_URL
        }

        headers = {
            "Authorization": f"Bearer {LIPANA_SECRET}",
            "Content-Type": "application/json"
        }

        resp = requests.post(LIPANA_URL, json=payload, headers=headers)
        resp.raise_for_status()
        res_data = resp.json()

        tx_id = res_data.get("transaction_id")
        if not tx_id:
            return jsonify({"success": False, "message": res_data}), 500

        TX_STATUS[tx_id] = "pending"
        return jsonify({"success": True, "CheckoutRequestID": tx_id})

    except Exception as e:
        with open("error.log", "a") as f:
            f.write(traceback.format_exc() + "\n")
        return jsonify({"success": False, "message": str(e)}), 500

# ----------------------------
# Callback from Lipana
# ----------------------------
@app.route("/api/callback", methods=["POST"])
def callback():
    try:
        data = request.get_json()
        with open("callback.log", "a") as f:
            json.dump(data, f, indent=4)
            f.write("\n")

        # Lipana should send transaction_id and status
        tx_id = data.get("transaction_id")
        status = data.get("status")

        if tx_id and status:
            if status.lower() == "success":
                TX_STATUS[tx_id] = "success"
            else:
                TX_STATUS[tx_id] = "failed"

        print("✅ Lipana callback received:", data)
        return jsonify({"success": True}), 200

    except Exception as e:
        with open("error.log", "a") as f:
            f.write(traceback.format_exc() + "\n")
        return jsonify({"success": False, "message": str(e)}), 500

# ----------------------------
# Check transaction status
# ----------------------------
@app.route("/api/check/<tx_id>", methods=["GET"])
def check(tx_id):
    status = TX_STATUS.get(tx_id, "pending")
    return jsonify({"success": True, "status": status})

# ----------------------------
# Run server
# ----------------------------
if __name__ == "__main__":
    print("🚀 NETSASA Backend (Lipana) running on port 5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
