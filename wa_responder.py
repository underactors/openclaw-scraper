"""
RUGGTECH WhatsApp Auto-Responder
Handles incoming WhatsApp messages by:
  1. Identifying the product/category the customer is asking about
  2. Pulling product data from Sanity CMS
  3. Generating a natural response via Claude with regional pricing
  4. Logging question categories and objections for the learning loop
  5. Escalating to Davon when mind.md rules require it

Uses WhatsApp Business Cloud API.
"""

import os
import json
import re
from datetime import datetime
from typing import Optional
import requests
from anthropic import Anthropic
from tools.pricing_engine import calculate_price, load_regions
import os
from dotenv import load_dotenv  # <--- Add this

load_dotenv()



WA_API = "https://graph.facebook.com/v19.0"
SANITY_API = "https://{project}.api.sanity.io/v2024-01-01/data/query/{dataset}"

ESCALATION_KEYWORDS = [
    "wholesale", "dealer", "reseller", "bulk", "distribute",
    "complaint", "broken", "refund", "return", "damaged",
]

QUESTION_CATEGORIES = [
    "pricing", "specs", "stock_availability", "shipping",
    "payment_methods", "warranty", "comparison", "fitment",
    "other",
]


# ─── Message Handling ────────────────────────────────────────

def handle_incoming_message(message: dict) -> dict:
    """
    Process a single incoming WhatsApp message.
    Returns response dict with action taken.
    """
    sender = message.get("from", "")
    text = message.get("text", {}).get("body", "").strip()
    msg_id = message.get("id", "")
    
    if not text:
        return {"action": "ignored", "reason": "empty message"}
    
    # 1. Check for escalation triggers
    text_lower = text.lower()
    for keyword in ESCALATION_KEYWORDS:
        if keyword in text_lower:
            return escalate_to_davon(sender, text, keyword)
    
    # 2. Categorize the question
    category = categorize_question(text)
    
    # 3. Try to identify the product they're asking about
    product = identify_product(text)
    
    # 4. Detect region from phone number prefix
    region = detect_region(sender)
    
    # 5. Generate response via Claude
    response_text = generate_response(text, product, region, category)
    
    # 6. Send the response
    send_whatsapp_message(sender, response_text)
    
    # 7. Log the interaction
    log_entry = log_interaction(sender, text, response_text, category, product, region)
    
    return {
        "action": "auto_responded",
        "sender": sender,
        "category": category,
        "product": product.get("name") if product else None,
        "region": region["id"] if region else "unknown",
    }


# ─── Question Categorization ────────────────────────────────

def categorize_question(text: str) -> str:
    """Categorize the incoming message into a question type for learning loop tracking."""
    text_lower = text.lower()
    
    patterns = {
        "pricing": [r"how much", r"price", r"cost", r"\$", r"ttd", r"usd", r"afford", r"cheap", r"expensive", r"budget"],
        "specs": [r"battery", r"camera", r"screen", r"ram", r"storage", r"waterproof", r"ip\d\d", r"processor", r"spec"],
        "stock_availability": [r"in stock", r"available", r"have any", r"when.*back", r"do you have", r"you carry"],
        "shipping": [r"ship", r"deliver", r"how long", r"arrive", r"where.*from", r"international", r"guyana", r"barbados", r"jamaica"],
        "payment_methods": [r"pay", r"paypal", r"usdt", r"crypto", r"bank transfer", r"cash", r"card"],
        "warranty": [r"warrant", r"guarantee", r"broken.*replace", r"if.*damage", r"return"],
        "comparison": [r"vs", r"versus", r"compare", r"better.*than", r"which.*should", r"difference.*between"],
        "fitment": [r"fit", r"compatible", r"work.*with", r"part.*number", r"model.*year", r"jimny", r"vitara"],
    }
    
    for category, keyword_list in patterns.items():
        for pattern in keyword_list:
            if re.search(pattern, text_lower):
                return category
    
    return "other"


# ─── Product Identification ──────────────────────────────────

def identify_product(text: str) -> Optional[dict]:
    """Try to identify which product the customer is asking about using Sanity search."""
    project = os.environ["SANITY_PROJECT_ID"]
    dataset = os.environ["SANITY_DATASET"]
    token = os.environ["SANITY_API_TOKEN"]
    
    # Extract likely product keywords
    text_clean = re.sub(r'[^\w\s]', '', text.lower())
    
    # Search across all product schemas
    query = f'*[_type in ["product","phone","car","offgrid","agritechPage"] && inStock == true]{{name, slug, price, brand, _type, details, keywoards, partNumber, compatibility}}[0...5]'
    
    url = SANITY_API.format(project=project, dataset=dataset)
    resp = requests.get(url, params={"query": query}, headers={"Authorization": f"Bearer {token}"})
    
    if resp.status_code != 200:
        return None
    
    products = resp.json().get("result", [])
    
    # Simple keyword matching
    best_match = None
    best_score = 0
    
    for product in products:
        score = 0
        name = (product.get("name") or "").lower()
        brand = (product.get("brand") or "").lower()
        keywords = product.get("keywoards", [])
        part_num = (product.get("partNumber") or "").lower()
        
        for word in text_clean.split():
            if word in name:
                score += 3
            if word in brand:
                score += 2
            if word in part_num:
                score += 5
            if any(word in (k or "").lower() for k in keywords):
                score += 1
        
        if score > best_score:
            best_score = score
            best_match = product
    
    return best_match if best_score >= 2 else None


# ─── Region Detection ────────────────────────────────────────

def detect_region(phone_number: str) -> dict:
    """Detect region from phone number country code."""
    regions = load_regions()
    
    prefix_map = {
        "1868": "tt", "592": "caribbean", "246": "caribbean",
        "876": "caribbean", "473": "caribbean", "758": "caribbean",
        "1": "us", "44": "uk", "49": "eu", "31": "eu",
        "234": "africa", "254": "africa", "233": "africa", "27": "africa",
    }
    
    for prefix, region_id in prefix_map.items():
        if phone_number.startswith(prefix):
            return next((r for r in regions if r["id"] == region_id), regions[0])
    
    return regions[0]  # Default to TT


# ─── Response Generation ─────────────────────────────────────

def generate_response(
    question: str,
    product: Optional[dict],
    region: dict,
    category: str
) -> str:
    """Generate a natural WhatsApp response using Claude."""
    client = Anthropic()
    
    product_context = ""
    if product:
        pricing = calculate_price(product.get("price", 0), region)
        product_context = f"""
Product found: {product.get('name', 'Unknown')}
Brand: {product.get('brand', '')}
Price: {pricing['display']}
In stock: Yes
Specs: {str(product.get('details', ''))[:300]}
Part number: {product.get('partNumber', 'N/A')}
Compatibility: {product.get('compatibility', 'N/A')}
"""
    else:
        product_context = "No specific product matched. Give a general response about our catalog and ask what they're looking for."
    
    prompt = f"""You are a friendly sales assistant for RUGGTECH, a Caribbean e-commerce company. You're responding on WhatsApp.

Customer's message: "{question}"
Question category: {category}

{product_context}

Region: {region['name']}
Shipping: {region['shipping_note']}
Payment: {', '.join(region['payment_methods'])}
Website: ruggtech.com

RULES:
- Be warm, helpful, and concise. This is WhatsApp, not email.
- Caribbean casual tone if customer is from TT/Caribbean. Professional if international.
- If you have the product info, give it directly — don't make them ask again.
- Always include the price if a product was identified.
- Always mention shipping timeline for international customers.
- If they ask about something you don't have data on, say "Let me check with the team and get back to you" — don't make up specs.
- Keep response under 200 words. WhatsApp is for quick answers.
- End with a soft next step: "Want me to send you more photos?" or "Anything else you'd like to know?"
- Never use formal closings like "Best regards" — this is WhatsApp.

Respond as the RUGGTECH sales assistant. No quotes around the response."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    
    return response.content[0].text.strip()


# ─── WhatsApp API ────────────────────────────────────────────

def send_whatsapp_message(to: str, text: str) -> dict:
    """Send a WhatsApp message via the Cloud API."""
    phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    token = os.environ["WHATSAPP_ACCESS_TOKEN"]
    
    resp = requests.post(
        f"{WA_API}/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        },
    )
    resp.raise_for_status()
    return resp.json()


# ─── Escalation ──────────────────────────────────────────────

def escalate_to_davon(sender: str, text: str, trigger_keyword: str) -> dict:
    """Send escalation alert to Davon's Telegram."""
    from tools.creative_review import send_message
    
    send_message(
        f"<b>WhatsApp escalation</b>\n\n"
        f"From: {sender}\n"
        f"Trigger: \"{trigger_keyword}\"\n"
        f"Message: \"{text[:300]}\"\n\n"
        f"This needs your personal attention."
    )
    
    return {
        "action": "escalated",
        "sender": sender,
        "trigger": trigger_keyword,
    }


# ─── Interaction Logging ─────────────────────────────────────

def log_interaction(
    sender: str, question: str, response: str,
    category: str, product: Optional[dict], region: Optional[dict]
) -> dict:
    """Log the interaction for the learning loop. Appends to daily log file."""
    log_dir = "data/wa_logs"
    os.makedirs(log_dir, exist_ok=True)
    
    log_path = f"{log_dir}/{datetime.now().strftime('%Y%m%d')}.jsonl"
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "sender_hash": hash(sender) % 10**8,  # Privacy — don't store full numbers
        "question": question[:500],
        "response": response[:500],
        "category": category,
        "product_matched": product.get("name") if product else None,
        "region": region["id"] if region else "unknown",
        "auto_handled": True,
    }
    
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    return entry


def get_daily_stats() -> dict:
    """Get today's WhatsApp stats for the morning report."""
    log_path = f"data/wa_logs/{datetime.now().strftime('%Y%m%d')}.jsonl"
    
    if not os.path.exists(log_path):
        return {"total": 0, "auto_handled": 0, "escalated": 0, "categories": {}}
    
    entries = []
    with open(log_path) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    
    categories = {}
    for e in entries:
        cat = e.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1
    
    auto = sum(1 for e in entries if e.get("auto_handled"))
    
    return {
        "total": len(entries),
        "auto_handled": auto,
        "escalated": len(entries) - auto,
        "categories": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)),
        "top_category": max(categories, key=categories.get) if categories else "none",
    }


if __name__ == "__main__":
    stats = get_daily_stats()
    print(f"Today's WhatsApp stats: {json.dumps(stats, indent=2)}")
