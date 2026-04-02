"""
RUGGTECH Copywriter Agent
Generates two types of ad copy:
  1. Pain point posts — from clustered pain data (pain_researcher output)
  2. Product posts — from Sanity CMS product data

Each variation is tagged with content_type, platform, region, and lane.
Output feeds into the renderer (Phase 3) and social poster (Phase 4).
"""

import os
import json
import csv
from datetime import datetime
from typing import Optional
import requests
from anthropic import Anthropic
from tools.pricing_engine import format_for_ad, load_regions
import os
from dotenv import load_dotenv  # <--- Add this

load_dotenv()



SANITY_API = "https://{project}.api.sanity.io/v2024-01-01/data/query/{dataset}"


def load_lane(lane_id: str) -> dict:
    with open("config/lanes.json") as f:
        return next(l for l in json.load(f)["lanes"] if l["id"] == lane_id)


# ─── Sanity Product Fetch ────────────────────────────────────

def fetch_products_from_sanity(lane: dict, limit: int = 20) -> list:
    """Fetch in-stock products from Sanity for this lane."""
    project = os.environ["SANITY_PROJECT_ID"]
    dataset = os.environ["SANITY_DATASET"]
    token = os.environ["SANITY_API_TOKEN"]
    
    query = lane["sanity_filter"]
    if limit:
        query += f"[0...{limit}]"
    
    url = SANITY_API.format(project=project, dataset=dataset)
    resp = requests.get(url, params={"query": query}, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    
    return resp.json().get("result", [])


# ─── Pain Point Copy Generation ──────────────────────────────

def generate_pain_copy(
    pain_data: dict,
    lane: dict,
    regions: Optional[list] = None,
    variations_per_point: int = 3
) -> list:
    """
    Generate pain point ad copy from clustered pain research.
    Returns list of copy dicts tagged with content_type='pain'.
    """
    if regions is None:
        regions = [r for r in load_regions() if r.get("active")]
    
    client = Anthropic()
    all_copy = []
    
    for category in pain_data.get("pain_categories", [])[:5]:
        # More variations for higher-frequency categories
        num_variations = min(variations_per_point + category["frequency"], 8)
        
        pain_points_text = "\n".join(
            f"- \"{pp['pain_statement']}\" (trigger: {pp['emotional_trigger']}, angle: {pp['ad_hook_angle']})"
            for pp in category["pain_points"][:6]
        )
        
        for region in regions:
            prompt = f"""You are a direct-response copywriter for RUGGTECH, a Caribbean e-commerce company. 
Write {num_variations} pain point ad variations for the "{category['category']}" pain cluster.

PRODUCT LINE: {lane['display_name']}
REGION: {region['name']}
TONE: {region['tone']}
PLATFORM TARGETS: Facebook (long-form ok), Instagram (shorter, hashtag-ready), TikTok (script format, hook in first line)

PAIN POINTS FROM REAL CUSTOMERS:
{pain_points_text}

RULES:
- Use the customer's actual language where possible — it's more authentic than marketing speak
- Each variation should use a DIFFERENT hook angle (question, stat, before/after, social proof, meme/relatable)
- Pain posts do NOT sell the product directly. They speak to the PROBLEM.
- Soft CTA only: "Comment if this is you", "Follow for the solution", "Tag someone"
- No product names, no prices, no specs. Just the pain.
- For TikTok: write as a 15-second script with [Hook 0-2s], [Build 2-10s], [Turn 10-15s] format
- For Instagram: write as carousel slide text (5 slides) or short reel caption

Return ONLY valid JSON array, no markdown:
[
  {{
    "headline": "string (for FB/IG — the hook line)",
    "body": "string (the full post text)",
    "platform": "facebook|instagram|tiktok",
    "hook_angle": "question|stat|before_after|social_proof|meme_relatable",
    "pain_category": "{category['category']}",
    "source_pain": "string (the original customer quote this is based on)"
  }}
]"""

            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=3000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                
                variations = json.loads(text)
                for v in variations:
                    v["content_type"] = "pain"
                    v["lane_id"] = lane["id"]
                    v["region_id"] = region["id"]
                    v["region_name"] = region["name"]
                    v["generated_at"] = datetime.now().isoformat()
                
                all_copy.extend(variations)
                
            except Exception as e:
                print(f"[Copywriter] Error generating pain copy for {category['category']} / {region['id']}: {e}")
                continue
    
    return all_copy


# ─── Product Post Copy Generation ────────────────────────────

def generate_product_copy(
    products: list,
    lane: dict,
    regions: Optional[list] = None,
    variations_per_product: int = 3
) -> list:
    """
    Generate product ad copy from Sanity CMS data.
    Returns list of copy dicts tagged with content_type='product'.
    """
    if regions is None:
        regions = [r for r in load_regions() if r.get("active")]
    
    client = Anthropic()
    all_copy = []
    
    for product in products[:10]:  # Cap at 10 products per batch
        name = product.get("name", "Unknown Product")
        specs = product.get("specifications", product.get("details", ""))
        features = product.get("features", product.get("keywoards", []))
        brand = product.get("brand", "")
        
        if isinstance(features, list):
            features = ", ".join(features[:10])
        
        supplier_cost = product.get("price", 0)
        if not supplier_cost:
            continue
        
        for region in regions:
            ad_pricing = format_for_ad(supplier_cost, region)
            
            prompt = f"""You are a direct-response copywriter for RUGGTECH, a Caribbean e-commerce company.
Write {variations_per_product} product ad variations for this product.

PRODUCT: {name}
BRAND: {brand}
KEY SPECS: {str(specs)[:500]}
FEATURES: {features}
PRICE: {ad_pricing['display']}
SHIPPING: {ad_pricing['shipping']}
PAYMENT: {ad_pricing['payment_line']}
CTA: {ad_pricing['cta_text']}
REGION: {region['name']}
TONE: {region['tone']}

RULES:
- Product posts SELL the product. Show specs, price, and clear CTA.
- Lead with the strongest benefit, not the brand name
- Price must be prominent — include currency and amount
- Include shipping info and payment methods
- For Facebook: image ad format, headline + body + CTA
- For Instagram: reel caption or carousel specs layout
- For TikTok: product demo script format — show don't tell, 20 seconds
- Each variation should highlight a DIFFERENT key feature/benefit

Return ONLY valid JSON array, no markdown:
[
  {{
    "headline": "string",
    "body": "string",
    "platform": "facebook|instagram|tiktok",
    "featured_benefit": "string (the key selling point of this variation)",
    "product_name": "{name}",
    "product_slug": "{product.get('slug', {}).get('current', '')}"
  }}
]"""

            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=3000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                
                variations = json.loads(text)
                for v in variations:
                    v["content_type"] = "product"
                    v["lane_id"] = lane["id"]
                    v["region_id"] = region["id"]
                    v["region_name"] = region["name"]
                    v["price_display"] = ad_pricing["display"]
                    v["cta_text"] = ad_pricing["cta_text"]
                    v["generated_at"] = datetime.now().isoformat()
                
                all_copy.extend(variations)
                
            except Exception as e:
                print(f"[Copywriter] Error generating product copy for {name} / {region['id']}: {e}")
                continue
    
    return all_copy


# ─── Export ──────────────────────────────────────────────────

def save_copy_batch(copy_items: list, lane_id: str) -> str:
    """Save generated copy to JSON + CSV for renderer and review."""
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    # JSON (full data)
    json_path = f"data/copy_{lane_id}_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(copy_items, f, indent=2)
    
    # CSV (for spreadsheet review)
    csv_path = f"data/copy_{lane_id}_{timestamp}.csv"
    if copy_items:
        keys = ["content_type", "lane_id", "region_id", "platform", "headline", "body",
                "hook_angle", "pain_category", "product_name", "price_display", "cta_text"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(copy_items)
    
    pain_count = sum(1 for c in copy_items if c["content_type"] == "pain")
    product_count = sum(1 for c in copy_items if c["content_type"] == "product")
    print(f"[Copywriter] Saved {pain_count} pain + {product_count} product variations to {json_path}")
    
    return json_path


# ─── Main Entry ──────────────────────────────────────────────

def run_copywriter(lane_id: str, pain_data_path: Optional[str] = None) -> str:
    """
    Full copywriter pipeline for a lane:
    1. Load pain research data
    2. Fetch products from Sanity
    3. Generate pain copy variations
    4. Generate product copy variations
    5. Save combined batch
    """
    lane = load_lane(lane_id)
    print(f"\n[Copywriter] Generating copy for: {lane['display_name']}")
    
    # Load pain data
    pain_data = {"pain_categories": []}
    if pain_data_path:
        with open(pain_data_path) as f:
            pain_data = json.load(f)
    else:
        # Find most recent pain data file
        import glob
        files = sorted(glob.glob(f"data/pain_points_{lane_id}_*.json"), reverse=True)
        if files:
            with open(files[0]) as f:
                pain_data = json.load(f)
            print(f"  Using pain data: {files[0]}")
    
    # Fetch products
    products = fetch_products_from_sanity(lane)
    print(f"  Products from Sanity: {len(products)}")
    
    # Generate both types
    pain_copy = generate_pain_copy(pain_data, lane)
    print(f"  Pain variations: {len(pain_copy)}")
    
    product_copy = generate_product_copy(products, lane)
    print(f"  Product variations: {len(product_copy)}")
    
    # Combine and save
    combined = pain_copy + product_copy
    output_path = save_copy_batch(combined, lane_id)
    
    return output_path


if __name__ == "__main__":
    import sys
    lane = sys.argv[1] if len(sys.argv) > 1 else "rugged-phones"
    pain_path = sys.argv[2] if len(sys.argv) > 2 else None
    run_copywriter(lane, pain_path)
