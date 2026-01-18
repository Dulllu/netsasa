import os

# =========================
# Lipana LIVE configuration
# =========================
LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")

# Public HTTPS webhook URL (Render)
LIPANA_CALLBACK_URL = os.getenv("LIPANA_CALLBACK_URL")

# =========================
# NETSASA Wi-Fi Packages
# =========================
PACKAGES = {
    "p1": {
        "name": "Mwangaza 20",
        "price": 5,
        "minutes": 20,
        "description": "Quick browse & messages"
    },
    "p2": {
        "name": "Sawa 50",
        "price": 10,
        "minutes": 50,
        "description": "Light browsing & social"
    },
    "p3": {
        "name": "Leo 1hr",
        "price": 20,
        "minutes": 60,
        "description": "Streaming lite & browsing"
    },
    "p4": {
        "name": "Kipindi 3hr",
        "price": 50,
        "minutes": 180,
        "description": "Study session"
    },
    "p5": {
        "name": "Siku 1 Day",
        "price": 60,
        "minutes": 1440,
        "description": "All-day access"
    },
    "p6": {
        "name": "Usiku",
        "price": 40,
        "minutes": 540,  # 21:00–06:00
        "description": "Night pack (21:00–06:00)"
    },
    "p7": {
        "name": "Social 1hr",
        "price": 15,
        "minutes": 60,
        "description": "Social apps only"
    },
    "p8": {
        "name": "DataLite 800MB",
        "price": 30,
        "mb": 800,
        "description": "Small data bundle"
    },
    "p9": {
        "name": "Weekend 48hr",
        "price": 150,
        "minutes": 2880,
        "description": "Weekend surf"
    },
    "p10": {
        "name": "Wiki 7 Day",
        "price": 400,
        "minutes": 10080,
        "description": "Weekly plan for heavy users"
    }
}
