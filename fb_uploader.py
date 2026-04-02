"""
RUGGTECH Facebook Ads Uploader
Bulk uploads approved ad creatives to Facebook Ads Manager.
Creates campaigns per lane + region, ad sets per content type (pain/product),
and individual ads from approved images.

All ads created as PAUSED (drafts) — Davon publishes via Ads Manager or approval flow.
"""

import os
import json
import time
import requests
from pathlib import Path
from typing import Optional
from tools.pricing_engine import load_regions


FB_API = "https://graph.facebook.com/v19.0"


def fb_request(endpoint: str, method: str = "GET", **kwargs) -> dict:
    token = os.environ["FACEBOOK_ADS_TOKEN"]
    url = f"{FB_API}/{endpoint}"
    kwargs.setdefault("params", {})
    kwargs["params"]["access_token"] = token
    resp = getattr(requests, method.lower())(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


# ─── Campaign Management ─────────────────────────────────────

def get_or_create_campaign(lane_id: str, region_id: str, region: dict) -> str:
    """Get existing campaign or create new one. Returns campaign ID."""
    ad_account = os.environ["META_AD_ACCOUNT_ID"]
    campaign_name = f"RUGGTECH_{lane_id}_{region_id}"
    
    # Check for existing campaign
    existing = fb_request(
        f"{ad_account}/campaigns",
        params={
            "filtering": json.dumps([{"field": "name", "operator": "CONTAIN", "value": campaign_name}]),
            "fields": "id,name,status",
        },
    )
    
    for c in existing.get("data", []):
        if c["name"] == campaign_name:
            return c["id"]
    
    # Create new campaign
    objective = "OUTCOME_ENGAGEMENT" if region["fb_objective"] == "MESSAGES" else "OUTCOME_SALES"
    
    result = fb_request(
        f"{ad_account}/campaigns",
        method="POST",
        json={
            "name": campaign_name,
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": [],
        },
    )
    
    print(f"  Created campaign: {campaign_name} ({result['id']})")
    return result["id"]


def get_or_create_adset(
    campaign_id: str,
    lane_id: str,
    region_id: str,
    content_type: str,
    region: dict
) -> str:
    """Create an ad set for a specific content type within a campaign."""
    ad_account = os.environ["META_AD_ACCOUNT_ID"]
    adset_name = f"RUGGTECH_{lane_id}_{region_id}_{content_type}"
    
    # Check existing
    existing = fb_request(
        f"{ad_account}/adsets",
        params={
            "filtering": json.dumps([{"field": "name", "operator": "CONTAIN", "value": adset_name}]),
            "fields": "id,name",
        },
    )
    
    for a in existing.get("data", []):
        if a["name"] == adset_name:
            return a["id"]
    
    # Daily budget in cents
    daily_budget_cents = int(region["daily_budget_usd"] * 100)
    
    # Targeting
    geo_locations = {"countries": region["fb_geo"]}
    
    targeting = {
        "geo_locations": geo_locations,
        "age_min": 25,
        "age_max": 55,
    }
    
    # Different optimization for pain vs product
    if content_type == "pain":
        optimization_goal = "POST_ENGAGEMENT" if region["fb_objective"] == "MESSAGES" else "LINK_CLICKS"
    else:
        optimization_goal = "CONVERSATIONS" if region["fb_objective"] == "MESSAGES" else "OFFSITE_CONVERSIONS"
    
    result = fb_request(
        f"{ad_account}/adsets",
        method="POST",
        json={
            "name": adset_name,
            "campaign_id": campaign_id,
            "daily_budget": daily_budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization_goal,
            "targeting": targeting,
            "status": "PAUSED",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        },
    )
    
    print(f"  Created ad set: {adset_name} ({result['id']})")
    return result["id"]


# ─── Creative Upload ─────────────────────────────────────────

def upload_image(image_path: str) -> str:
    """Upload an image to the ad account and return the image hash."""
    ad_account = os.environ["META_AD_ACCOUNT_ID"]
    token = os.environ["FACEBOOK_ADS_TOKEN"]
    
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{FB_API}/{ad_account}/adimages",
            params={"access_token": token},
            files={"filename": f},
        )
    resp.raise_for_status()
    data = resp.json()
    
    # Extract hash from response
    images = data.get("images", {})
    for key, val in images.items():
        return val.get("hash", "")
    
    return ""


def create_ad(
    adset_id: str,
    image_hash: str,
    creative_data: dict,
    region: dict
) -> str:
    """Create a single ad within an ad set."""
    ad_account = os.environ["META_AD_ACCOUNT_ID"]
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    
    content_type = creative_data.get("content_type", "product")
    headline = creative_data.get("headline", "RUGGTECH")
    body = creative_data.get("body", "")
    
    # Build CTA based on region and content type
    if region["cta_type"] == "WHATSAPP_MESSAGE":
        call_to_action = {
            "type": "WHATSAPP_MESSAGE",
            "value": {"whatsapp_number": os.environ.get("RUGGTECH_WHATSAPP_NUMBER", "18683661212")},
        }
    else:
        call_to_action = {
            "type": "SHOP_NOW",
            "value": {"link": os.environ.get("RUGGTECH_WEBSITE", "https://ruggtech.com")},
        }
    
    ad_name = f"{content_type}_{creative_data.get('lane_id', '')}_{creative_data.get('filename', '')[:30]}"
    
    # Create ad creative
    creative_result = fb_request(
        f"{ad_account}/adcreatives",
        method="POST",
        json={
            "name": ad_name,
            "object_story_spec": {
                "page_id": page_id,
                "link_data": {
                    "image_hash": image_hash,
                    "message": body[:500],
                    "name": headline[:100],
                    "call_to_action": call_to_action,
                    "link": os.environ.get("RUGGTECH_WEBSITE", "https://ruggtech.com"),
                },
            },
        },
    )
    
    creative_id = creative_result["id"]
    
    # Create the ad itself (PAUSED)
    ad_result = fb_request(
        f"{ad_account}/ads",
        method="POST",
        json={
            "name": ad_name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
    )
    
    return ad_result["id"]


# ─── Bulk Upload Pipeline ────────────────────────────────────

def upload_approved_batch(batch_dir: str) -> dict:
    """
    Upload all approved creatives from a batch to Facebook Ads Manager.
    Creates campaigns/ad sets as needed. All ads start PAUSED.
    """
    batch_path = Path(batch_dir)
    manifest_path = batch_path / "manifest.json"
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    approved = [m for m in manifest if m.get("approved")]
    if not approved:
        print("[Uploader] No approved creatives to upload.")
        return {"uploaded": 0}
    
    regions = {r["id"]: r for r in load_regions()}
    results = {"uploaded": 0, "errors": [], "campaigns": {}, "ads": []}
    
    # Group by lane + region + content type
    groups = {}
    for item in approved:
        key = (item["lane_id"], item["region_id"], item["content_type"])
        groups.setdefault(key, []).append(item)
    
    for (lane_id, region_id, content_type), items in groups.items():
        region = regions.get(region_id)
        if not region:
            results["errors"].append(f"Unknown region: {region_id}")
            continue
        
        if not region.get("active"):
            print(f"  Skipping inactive region: {region_id}")
            continue
        
        print(f"\n[Uploader] {lane_id} / {region_id} / {content_type}: {len(items)} creatives")
        
        try:
            # Get or create campaign and ad set
            campaign_id = get_or_create_campaign(lane_id, region_id, region)
            adset_id = get_or_create_adset(campaign_id, lane_id, region_id, content_type, region)
            
            results["campaigns"][f"{lane_id}_{region_id}"] = campaign_id
            
            for item in items:
                image_path = batch_path / item["filename"]
                if not image_path.exists():
                    results["errors"].append(f"Missing image: {item['filename']}")
                    continue
                
                try:
                    image_hash = upload_image(str(image_path))
                    ad_id = create_ad(adset_id, image_hash, item, region)
                    results["ads"].append({"filename": item["filename"], "ad_id": ad_id})
                    results["uploaded"] += 1
                    time.sleep(1)  # Rate limit respect
                except Exception as e:
                    results["errors"].append(f"Failed {item['filename']}: {e}")
        
        except Exception as e:
            results["errors"].append(f"Failed group {lane_id}/{region_id}/{content_type}: {e}")
    
    print(f"\n[Uploader] Done: {results['uploaded']} ads uploaded, {len(results['errors'])} errors")
    return results


if __name__ == "__main__":
    import sys
    batch = sys.argv[1] if len(sys.argv) > 1 else "output/creatives/batch_latest"
    upload_approved_batch(batch)
