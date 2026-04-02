"""
One-time setup script to register your Railway URL as the Telegram bot webhook.
Run this ONCE after deploying to Railway:

  python setup_telegram_webhook.py https://your-app.up.railway.app

This tells Telegram to POST button callbacks to your Railway webhook server.
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()


def setup_webhook(railway_url: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    webhook_url = f"{railway_url.rstrip('/')}/webhook/telegram"

    # Set the webhook
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={"url": webhook_url, "allowed_updates": ["callback_query", "message"]},
    )
    resp.raise_for_status()
    result = resp.json()

    if result.get("ok"):
        print(f"Webhook set successfully!")
        print(f"URL: {webhook_url}")
        print(f"\nTelegram will now POST button callbacks to your Railway server.")
        print(f"Test by tapping an approve/reject button in your Telegram bot chat.")
    else:
        print(f"Failed: {result}")
        sys.exit(1)


def check_webhook():
    """Check current webhook status."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    resp = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
    info = resp.json().get("result", {})
    print(f"Current webhook: {info.get('url', 'none set')}")
    print(f"Pending updates: {info.get('pending_update_count', 0)}")
    if info.get("last_error_message"):
        print(f"Last error: {info['last_error_message']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python setup_telegram_webhook.py https://your-app.up.railway.app")
        print("  python setup_telegram_webhook.py --check")
        sys.exit(1)

    if sys.argv[1] == "--check":
        check_webhook()
    else:
        setup_webhook(sys.argv[1])
