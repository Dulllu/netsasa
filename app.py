from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, os, time
from config import *

app = Flask(__name__)
CORS(app)

# ------------------------------
# Health check (Render)
# ------------------------------
@app.route("/")
def home():
    return jsonify({"status": "NETSASA backend running (Lipana LIVE)"})

# ------------------------------
# TEMP SESSION STORE
# (Use Redis / DB later)
# ------------------------------
PAID_SESSIONS = {}

# ------------------------------
# PAY (Lipana STK Push)
# ------------------------------
@app.route("/pay", methods=["POST"])
def pay():
    data = request.json or {}
    phone = data.get("phone")
    package_id = data.get("package")

    if not phone or not package_id:
        return jsonify({"message": "Missing phone or package"}), 400

    if package_id not in PACKAGES:
        return jsonify({"message": "Invalid package"}), 400

    pkg = PACKAGES[package_id]

    payload = {
        "phone": phone,
        "amount": int(pkg["price"]),
        "reference": f"NETSASA-{int(time.time())}",
        "description": pkg["name"],
        "callback_url": LIPANA_CALLBACK_URL
    }

    try:
        r = requests.post(
            "https://api.lipana.dev/v1/transactions/push-stk",
            headers={
                "x-api-key": LIPANA_API_KEY,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=15
        )
        r.raise_for_status()

        return jsonify({
            "message": "STK sent. Approve payment on your phone."
        })

    except requests.exceptions.RequestException as e:
        print("Lipana error:", r.text if 'r' in locals() else e)
        return jsonify({"message": "Payment initiation failed"}), 400

# ------------------------------
# LIPANA WEBHOOK
# ------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.json or {}
    print("Lipana webhook:", payload)

    if payload.get("event") == "payment.success":
        data = payload.get("data", {})
        amount = data.get("amount")

        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0]
            or request.remote_addr
        )

        for pkg in PACKAGES.values():
            if int(pkg["price"]) == int(amount):
                expiry = time.time() + (pkg.get("minutes", 60) * 60)
                PAID_SESSIONS[client_ip] = expiry
                break

    return jsonify({"ok": True})

# ------------------------------
# STATUS (polled by frontend)
# ------------------------------
@app.route("/status")
def status():
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0]
        or request.remote_addr
    )

    expiry = PAID_SESSIONS.get(client_ip)
    if expiry and expiry > time.time():
        remaining = int((expiry - time.time()) / 60)
        return jsonify({
            "access": "granted",
            "remaining_minutes": remaining
        })

    return jsonify({"access": "denied"}), 403

# ------------------------------
# RUN
# ------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
