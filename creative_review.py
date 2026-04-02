"""
RUGGTECH Creative Review
Sends rendered ad creatives to Davon's Telegram for approval.
Pain posts and product posts are sent in separate batches with clear labels.
Uses Telegram inline keyboard buttons for approve/reject per item and batch.
"""

import os
import json
import requests
from pathlib import Path
from typing import Optional
import os
from dotenv import load_dotenv  # <--- Add this

load_dotenv()



TELEGRAM_API = "https://api.telegram.org/bot{token}"


def get_api_url(endpoint: str) -> str:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return f"{TELEGRAM_API.format(token=token)}/{endpoint}"


def send_message(text: str, reply_markup: Optional[dict] = None) -> dict:
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    resp = requests.post(get_api_url("sendMessage"), json=payload)
    resp.raise_for_status()
    return resp.json()


def send_photo(photo_path: str, caption: str, reply_markup: Optional[dict] = None) -> dict:
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        resp = requests.post(get_api_url("sendPhoto"), data=data, files=files)
    resp.raise_for_status()
    return resp.json()


# ─── Gallery Builder ─────────────────────────────────────────

def send_creative_gallery(batch_dir: str) -> dict:
    """
    Send the full creative batch to Davon's Telegram for review.
    Pain posts first, then product posts — clearly separated.
    Returns summary of what was sent.
    """
    batch_path = Path(batch_dir)
    manifest_path = batch_path / "manifest.json"
    
    if not manifest_path.exists():
        return {"error": "No manifest.json found in batch directory"}
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    pain_items = [m for m in manifest if m["content_type"] == "pain"]
    product_items = [m for m in manifest if m["content_type"] == "product"]
    
    summary = {"pain_sent": 0, "product_sent": 0, "errors": []}
    
    # ── Header message ──
    total = len(manifest)
    send_message(
        f"<b>{total} new creatives ready for review.</b>\n\n"
        f"Pain posts: {len(pain_items)}\n"
        f"Product posts: {len(product_items)}\n\n"
        f"Review each one below. Tap Approve or Reject."
    )
    
    # ── Pain posts section ──
    if pain_items:
        send_message(f"━━━ <b>PAIN POSTS ({len(pain_items)})</b> ━━━\nThese speak to the PROBLEM. No product names, no prices.")
        
        for item in pain_items:
            image_path = batch_path / item["filename"]
            if not image_path.exists():
                summary["errors"].append(f"Missing: {item['filename']}")
                continue
            
            caption = (
                f"<b>PAIN</b> | {item['lane_id']} | {item['region_id']}\n"
                f"Platform: {item['platform']}\n"
                f"Angle: {item.get('hook_angle', 'N/A')}\n"
                f"Category: {item.get('pain_category', 'N/A')}\n"
                f"Headline: {item.get('headline', '')[:100]}"
            )
            
            buttons = {
                "inline_keyboard": [[
                    {"text": "Approve", "callback_data": f"approve_pain_{item['filename']}"},
                    {"text": "Reject", "callback_data": f"reject_pain_{item['filename']}"},
                ]]
            }
            
            try:
                send_photo(str(image_path), caption, buttons)
                summary["pain_sent"] += 1
            except Exception as e:
                summary["errors"].append(f"Failed to send {item['filename']}: {e}")
    
    # ── Product posts section ──
    if product_items:
        send_message(f"━━━ <b>PRODUCT POSTS ({len(product_items)})</b> ━━━\nThese SELL the product. Specs, price, CTA.")
        
        for item in product_items:
            image_path = batch_path / item["filename"]
            if not image_path.exists():
                summary["errors"].append(f"Missing: {item['filename']}")
                continue
            
            caption = (
                f"<b>PRODUCT</b> | {item['lane_id']} | {item['region_id']}\n"
                f"Platform: {item['platform']}\n"
                f"Product: {item.get('product_name', 'N/A')}\n"
                f"Price: {item.get('price_display', 'N/A')}\n"
                f"Headline: {item.get('headline', '')[:100]}"
            )
            
            buttons = {
                "inline_keyboard": [[
                    {"text": "Approve", "callback_data": f"approve_product_{item['filename']}"},
                    {"text": "Reject", "callback_data": f"reject_product_{item['filename']}"},
                ]]
            }
            
            try:
                send_photo(str(image_path), caption, buttons)
                summary["product_sent"] += 1
            except Exception as e:
                summary["errors"].append(f"Failed to send {item['filename']}: {e}")
    
    # ── Batch actions ──
    batch_buttons = {
        "inline_keyboard": [[
            {"text": "Approve ALL pain", "callback_data": f"approve_all_pain_{batch_path.name}"},
            {"text": "Approve ALL product", "callback_data": f"approve_all_product_{batch_path.name}"},
        ], [
            {"text": "Approve EVERYTHING", "callback_data": f"approve_all_{batch_path.name}"},
            {"text": "Reject ALL", "callback_data": f"reject_all_{batch_path.name}"},
        ]]
    }
    
    send_message(
        f"<b>Batch actions:</b>\n"
        f"Sent {summary['pain_sent']} pain + {summary['product_sent']} product creatives.\n"
        f"{'Errors: ' + str(len(summary['errors'])) if summary['errors'] else 'No errors.'}",
        batch_buttons
    )
    
    return summary


# ─── Approval Processor ─────────────────────────────────────

def process_approval_callback(callback_data: str, batch_dir: str) -> dict:
    """
    Process Telegram button callback. Updates the manifest with approval status.
    Returns list of approved filenames for the uploader.
    """
    batch_path = Path(batch_dir)
    manifest_path = batch_path / "manifest.json"
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    action = callback_data.split("_")[0]  # approve or reject
    
    if "approve_all_" in callback_data:
        # Approve all of a type or everything
        if "pain" in callback_data:
            for item in manifest:
                if item["content_type"] == "pain":
                    item["approved"] = True
        elif "product" in callback_data:
            for item in manifest:
                if item["content_type"] == "product":
                    item["approved"] = True
        else:
            for item in manifest:
                item["approved"] = True
    
    elif "reject_all" in callback_data:
        for item in manifest:
            item["approved"] = False
    
    else:
        # Individual item
        filename = "_".join(callback_data.split("_")[2:])
        for item in manifest:
            if item["filename"] == filename:
                item["approved"] = (action == "approve")
                break
    
    # Save updated manifest
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    approved = [m for m in manifest if m.get("approved")]
    rejected = [m for m in manifest if m.get("approved") is False]
    pending = [m for m in manifest if m.get("approved") is None]
    
    return {
        "approved": len(approved),
        "rejected": len(rejected),
        "pending": len(pending),
        "approved_files": [m["filename"] for m in approved],
    }


def get_approved_creatives(batch_dir: str) -> list:
    """Return list of approved creative manifest entries for the uploader."""
    manifest_path = Path(batch_dir) / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)
    return [m for m in manifest if m.get("approved")]


if __name__ == "__main__":
    import sys
    batch = sys.argv[1] if len(sys.argv) > 1 else "output/creatives/batch_latest"
    result = send_creative_gallery(batch)
    print(f"Sent: {result}")
