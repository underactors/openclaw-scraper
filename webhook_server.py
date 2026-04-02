"""
RUGGTECH Telegram Webhook Server
Runs on Railway. Routes triggers to the OpenClaw skill_runner.
"""

import os
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from skill_runner import run_agent, handle_webhook, handle_manual

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "ruggtech-marketing-manager",
        "architecture": "openclaw",
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/webhook/telegram", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    if update.get("callback_query"):
        thread = threading.Thread(target=handle_webhook, args=(update,))
        thread.start()
    return jsonify({"ok": True})


@app.route("/run", methods=["POST"])
def manual_run():
    run_key = request.headers.get("X-Run-Key", "")
    expected = os.environ.get("RUN_SECRET", "")
    if not expected or run_key != expected:
        return jsonify({"error": "unauthorized"}), 401

    instruction = request.json.get("instruction") if request.is_json else None
    if instruction:
        result = handle_manual(instruction)
    else:
        result = run_agent(trigger_type="manual")

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[Webhook] Starting server on port {port}")
    app.run(host="0.0.0.0", port=port)
