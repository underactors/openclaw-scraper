"""
RUGGTECH Social Poster
Schedules and publishes organic pain + product posts to:
  - Facebook Page (via Graph API)
  - Instagram (via Instagram Graph API)
  - TikTok (via Content Posting API or saves to drafts folder)

Respects posting ratios from lanes.json per platform.
All posts go through Telegram approval flow before publishing.
"""

import os
import json
import random
from datetime import datetime, timedelta
from typing import Optional
import requests


FB_API = "https://graph.facebook.com/v19.0"


def load_lane(lane_id: str) -> dict:
    with open("config/lanes.json") as f:
        return next(l for l in json.load(f)["lanes"] if l["id"] == lane_id)


# ─── Content Selection ───────────────────────────────────────

def select_posts_for_today(lane_id: str, platform: str) -> list:
    """
    Select the right mix of pain/product posts for today based on lane ratios.
    Pulls from the approved copy pool.
    """
    lane = load_lane(lane_id)
    ratio = lane["posting_ratio"].get(platform, {"pain": 50, "product": 50})
    freq_key = f"{platform}_per_week"
    weekly_count = lane["social_frequency"].get(freq_key, 3)
    
    # Simple daily distribution: weekly / 7, round up some days
    day_of_week = datetime.now().weekday()
    post_days = _distribute_posts(weekly_count)
    
    if day_of_week not in post_days:
        return []
    
    daily_count = post_days.count(day_of_week)
    pain_count = max(1, round(daily_count * ratio["pain"] / 100))
    product_count = daily_count - pain_count
    
    # Load approved copy pool
    pool = _load_copy_pool(lane_id, platform)
    
    pain_pool = [p for p in pool if p["content_type"] == "pain" and not p.get("posted")]
    product_pool = [p for p in pool if p["content_type"] == "product" and not p.get("posted")]
    
    selected = []
    selected.extend(random.sample(pain_pool, min(pain_count, len(pain_pool))))
    selected.extend(random.sample(product_pool, min(product_count, len(product_pool))))
    
    return selected


def _distribute_posts(weekly_count: int) -> list:
    """Distribute N posts across 7 days of the week. Returns list of day indices."""
    if weekly_count >= 7:
        return list(range(7))
    spacing = 7 / weekly_count
    return [int(i * spacing) % 7 for i in range(weekly_count)]


def _load_copy_pool(lane_id: str, platform: str) -> list:
    """Load approved copy items for this lane and platform."""
    pool_path = f"data/approved_pool_{lane_id}.json"
    if not os.path.exists(pool_path):
        return []
    with open(pool_path) as f:
        pool = json.load(f)
    return [p for p in pool if p.get("platform") == platform or p.get("platform") == "all"]


# ─── Facebook Page Posting ───────────────────────────────────

def post_to_facebook_page(post_data: dict) -> dict:
    """Publish a post to the RUGGTECH Facebook Page."""
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    token = os.environ["FACEBOOK_PAGE_TOKEN"]
    
    message = post_data.get("body", "")
    image_url = post_data.get("image_url")
    
    if image_url:
        resp = requests.post(
            f"{FB_API}/{page_id}/photos",
            data={"message": message, "url": image_url, "access_token": token},
        )
    else:
        resp = requests.post(
            f"{FB_API}/{page_id}/feed",
            data={"message": message, "access_token": token},
        )
    
    resp.raise_for_status()
    result = resp.json()
    
    return {
        "platform": "facebook_page",
        "post_id": result.get("id") or result.get("post_id"),
        "content_type": post_data.get("content_type"),
        "posted_at": datetime.now().isoformat(),
    }


# ─── Instagram Posting ───────────────────────────────────────

def post_to_instagram(post_data: dict) -> dict:
    """Publish a post to Instagram via the Graph API (requires image URL)."""
    ig_id = os.environ["INSTAGRAM_BUSINESS_ID"]
    token = os.environ["FACEBOOK_PAGE_TOKEN"]
    
    image_url = post_data.get("image_url")
    caption = post_data.get("body", "")
    
    if not image_url:
        return {"error": "Instagram requires an image URL"}
    
    # Step 1: Create media container
    container_resp = requests.post(
        f"{FB_API}/{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
    )
    container_resp.raise_for_status()
    container_id = container_resp.json()["id"]
    
    # Step 2: Publish
    publish_resp = requests.post(
        f"{FB_API}/{ig_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
    )
    publish_resp.raise_for_status()
    
    return {
        "platform": "instagram",
        "post_id": publish_resp.json().get("id"),
        "content_type": post_data.get("content_type"),
        "posted_at": datetime.now().isoformat(),
    }


# ─── TikTok Posting ──────────────────────────────────────────

def save_tiktok_draft(post_data: dict) -> dict:
    """
    Save TikTok content to drafts folder for manual posting or API posting.
    TikTok Content Posting API requires video — so for image-based ads,
    we save the script + image for video creation (ffmpeg slideshow or manual).
    """
    drafts_dir = "output/tiktok_drafts"
    os.makedirs(drafts_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    draft_name = f"{post_data.get('content_type', 'post')}_{post_data.get('lane_id', '')}_{timestamp}"
    
    draft = {
        "script": post_data.get("body", ""),
        "headline": post_data.get("headline", ""),
        "content_type": post_data.get("content_type"),
        "lane_id": post_data.get("lane_id"),
        "image_path": post_data.get("image_path"),
        "suggested_audio": post_data.get("audio_suggestion", "trending audio"),
        "created_at": datetime.now().isoformat(),
        "status": "draft",
    }
    
    draft_path = f"{drafts_dir}/{draft_name}.json"
    with open(draft_path, "w") as f:
        json.dump(draft, f, indent=2)
    
    return {
        "platform": "tiktok",
        "draft_path": draft_path,
        "content_type": post_data.get("content_type"),
        "status": "saved_as_draft",
    }


# ─── Queue Management ────────────────────────────────────────

def queue_days_posts(lane_id: str) -> dict:
    """
    Queue today's posts for all platforms for a specific lane.
    Returns summary of what was queued.
    """
    summary = {"queued": 0, "by_platform": {}}
    
    for platform in ["facebook_page", "instagram", "tiktok"]:
        posts = select_posts_for_today(lane_id, platform)
        
        if posts:
            queue_path = f"data/queue_{lane_id}_{platform}_{datetime.now().strftime('%Y%m%d')}.json"
            os.makedirs("data", exist_ok=True)
            with open(queue_path, "w") as f:
                json.dump(posts, f, indent=2)
            
            summary["queued"] += len(posts)
            summary["by_platform"][platform] = len(posts)
    
    return summary


def publish_queue(lane_id: str, platform: str) -> list:
    """Publish all queued posts for a lane + platform."""
    queue_path = f"data/queue_{lane_id}_{platform}_{datetime.now().strftime('%Y%m%d')}.json"
    
    if not os.path.exists(queue_path):
        return []
    
    with open(queue_path) as f:
        queue = json.load(f)
    
    results = []
    for post_data in queue:
        try:
            if platform == "facebook_page":
                result = post_to_facebook_page(post_data)
            elif platform == "instagram":
                result = post_to_instagram(post_data)
            elif platform == "tiktok":
                result = save_tiktok_draft(post_data)
            else:
                result = {"error": f"Unknown platform: {platform}"}
            
            results.append(result)
        except Exception as e:
            results.append({"error": str(e), "post": post_data.get("headline", "")})
    
    return results


if __name__ == "__main__":
    import sys
    lane = sys.argv[1] if len(sys.argv) > 1 else "rugged-phones"
    summary = queue_days_posts(lane)
    print(f"Queued for {lane}: {summary}")
