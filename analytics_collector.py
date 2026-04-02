"""
RUGGTECH Analytics Collector
Pulls performance metrics from all 6 data sources into one unified structure.
Runs daily at 6:30 AM per schedule.json.

Sources:
  1. Facebook Ads API — ad performance (CTR, CPC, ROAS, conversations)
  2. Instagram Graph API — organic post metrics (reach, saves, shares)
  3. TikTok Business API — organic video metrics (completion rate, views, shares)
  4. WhatsApp Business — conversation stats from wa_responder logs
  5. Website — Meta Pixel data (product views, purchases, bounce rate)
  6. Notion CRM — lead volume, intent scores, source breakdown
"""

import os
import json
import glob
from datetime import datetime, timedelta
from typing import Optional
import requests


FB_API = "https://graph.facebook.com/v19.0"
SANITY_API = "https://{project}.api.sanity.io/v2024-01-01/data/query/{dataset}"
NOTION_API = "https://api.notion.com/v1"


# ─── Facebook Ads Metrics ────────────────────────────────────

def collect_facebook_ads(days_back: int = 1) -> dict:
    """Pull Facebook Ads performance across all RUGGTECH campaigns."""
    token = os.environ.get("FACEBOOK_ADS_TOKEN")
    ad_account = os.environ.get("META_AD_ACCOUNT_ID")
    if not token or not ad_account:
        return {"error": "Missing FACEBOOK_ADS_TOKEN or META_AD_ACCOUNT_ID", "available": False}

    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    until = datetime.now().strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            f"{FB_API}/{ad_account}/insights",
            params={
                "access_token": token,
                "fields": "impressions,clicks,ctr,cpc,cpm,spend,actions,cost_per_action_type,frequency,campaign_name",
                "time_range": json.dumps({"since": since, "until": until}),
                "level": "campaign",
                "limit": 50,
            },
        )
        resp.raise_for_status()
        campaigns = resp.json().get("data", [])

        total_spend = 0
        total_clicks = 0
        total_impressions = 0
        total_conversations = 0
        total_purchases = 0
        campaign_results = []

        for c in campaigns:
            spend = float(c.get("spend", 0))
            impressions = int(c.get("impressions", 0))
            clicks = int(c.get("clicks", 0))
            ctr = float(c.get("ctr", 0))
            frequency = float(c.get("frequency", 0))
            conversations = 0
            purchases = 0

            for action in c.get("actions", []):
                atype = action.get("action_type", "")
                val = int(action.get("value", 0))
                if "messaging_conversation" in atype or "contact" in atype:
                    conversations += val
                elif "purchase" in atype:
                    purchases += val

            total_spend += spend
            total_clicks += clicks
            total_impressions += impressions
            total_conversations += conversations
            total_purchases += purchases

            # Parse lane and region from campaign name
            parts = c.get("campaign_name", "").replace("RUGGTECH_", "").split("_")
            lane_id = parts[0] if parts else "unknown"
            region_id = parts[1] if len(parts) > 1 else "unknown"

            campaign_results.append({
                "name": c.get("campaign_name", ""),
                "lane_id": lane_id,
                "region_id": region_id,
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr,
                "cpc": float(c.get("cpc", 0)),
                "frequency": frequency,
                "conversations": conversations,
                "purchases": purchases,
            })

        avg_ctr = (total_clicks / max(total_impressions, 1)) * 100

        return {
            "available": True,
            "total_spend_usd": round(total_spend, 2),
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "avg_ctr": round(avg_ctr, 2),
            "total_conversations": total_conversations,
            "total_purchases": total_purchases,
            "campaigns": campaign_results,
            "top_campaign": max(campaign_results, key=lambda x: x["ctr"]) if campaign_results else None,
            "worst_campaign": min(campaign_results, key=lambda x: x["ctr"]) if campaign_results else None,
        }

    except Exception as e:
        return {"available": False, "error": str(e)}


# ─── Instagram Organic Metrics ───────────────────────────────

def collect_instagram(days_back: int = 1) -> dict:
    """Pull Instagram organic post metrics via Graph API."""
    ig_id = os.environ.get("INSTAGRAM_BUSINESS_ID")
    token = os.environ.get("FACEBOOK_PAGE_TOKEN")
    if not ig_id or not token:
        return {"available": False, "error": "Missing INSTAGRAM_BUSINESS_ID or token"}

    try:
        # Get recent media
        media_resp = requests.get(
            f"{FB_API}/{ig_id}/media",
            params={
                "access_token": token,
                "fields": "id,caption,timestamp,like_count,comments_count,media_type",
                "limit": 20,
            },
        )
        media_resp.raise_for_status()
        posts = media_resp.json().get("data", [])

        cutoff = datetime.now() - timedelta(days=days_back + 1)
        recent_posts = []
        total_likes = 0
        total_comments = 0
        total_saves = 0
        total_reach = 0
        total_shares = 0

        for post in posts:
            post_time = datetime.fromisoformat(post["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            if post_time < cutoff:
                continue

            # Get insights per post
            try:
                insights_resp = requests.get(
                    f"{FB_API}/{post['id']}/insights",
                    params={
                        "access_token": token,
                        "metric": "reach,saved,shares",
                    },
                )
                insights_resp.raise_for_status()
                insights = {i["name"]: i["values"][0]["value"] for i in insights_resp.json().get("data", [])}
            except Exception:
                insights = {}

            likes = post.get("like_count", 0)
            comments = post.get("comments_count", 0)
            saves = insights.get("saved", 0)
            reach = insights.get("reach", 0)
            shares = insights.get("shares", 0)

            total_likes += likes
            total_comments += comments
            total_saves += saves
            total_reach += reach
            total_shares += shares

            recent_posts.append({
                "id": post["id"],
                "caption": (post.get("caption") or "")[:100],
                "likes": likes,
                "comments": comments,
                "saves": saves,
                "reach": reach,
                "shares": shares,
                "type": post.get("media_type", ""),
            })

        # Sort by saves (highest purchase intent)
        recent_posts.sort(key=lambda x: x["saves"], reverse=True)

        return {
            "available": True,
            "posts_analyzed": len(recent_posts),
            "total_reach": total_reach,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_saves": total_saves,
            "total_shares": total_shares,
            "top_by_saves": recent_posts[0] if recent_posts else None,
            "top_by_reach": max(recent_posts, key=lambda x: x["reach"]) if recent_posts else None,
            "posts": recent_posts,
        }

    except Exception as e:
        return {"available": False, "error": str(e)}


# ─── TikTok Organic Metrics ─────────────────────────────────

def collect_tiktok(days_back: int = 1) -> dict:
    """Pull TikTok organic video metrics via Business API."""
    token = os.environ.get("TIKTOK_BUSINESS_ACCESS_TOKEN")
    if not token:
        return {"available": False, "error": "Missing TIKTOK_BUSINESS_ACCESS_TOKEN"}

    try:
        # TikTok Content Posting API — list videos
        resp = requests.get(
            "https://open.tiktokapis.com/v2/video/list/",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "id,title,create_time,like_count,comment_count,share_count,view_count,duration"},
        )
        resp.raise_for_status()
        videos = resp.json().get("data", {}).get("videos", [])

        cutoff_ts = int((datetime.now() - timedelta(days=days_back + 1)).timestamp())
        recent = [v for v in videos if v.get("create_time", 0) > cutoff_ts]

        total_views = sum(v.get("view_count", 0) for v in recent)
        total_likes = sum(v.get("like_count", 0) for v in recent)
        total_shares = sum(v.get("share_count", 0) for v in recent)
        total_comments = sum(v.get("comment_count", 0) for v in recent)

        video_results = []
        for v in recent:
            views = v.get("view_count", 0)
            video_results.append({
                "id": v.get("id"),
                "title": (v.get("title") or "")[:80],
                "views": views,
                "likes": v.get("like_count", 0),
                "shares": v.get("share_count", 0),
                "comments": v.get("comment_count", 0),
                "duration": v.get("duration", 0),
                "engagement_rate": round(
                    ((v.get("like_count", 0) + v.get("share_count", 0) + v.get("comment_count", 0)) / max(views, 1)) * 100, 2
                ),
            })

        video_results.sort(key=lambda x: x["views"], reverse=True)

        return {
            "available": True,
            "videos_analyzed": len(video_results),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_shares": total_shares,
            "total_comments": total_comments,
            "top_by_views": video_results[0] if video_results else None,
            "top_by_engagement": max(video_results, key=lambda x: x["engagement_rate"]) if video_results else None,
            "spark_ad_candidates": [v for v in video_results if v["views"] >= 50000],
            "videos": video_results,
        }

    except Exception as e:
        return {"available": False, "error": str(e)}


# ─── WhatsApp Stats ──────────────────────────────────────────

def collect_whatsapp(days_back: int = 1) -> dict:
    """Compile WhatsApp conversation stats from wa_responder logs."""
    log_dir = "data/wa_logs"
    if not os.path.exists(log_dir):
        return {"available": True, "total": 0, "auto_handled": 0, "escalated": 0, "categories": {}}

    entries = []
    for d in range(days_back):
        date_str = (datetime.now() - timedelta(days=d)).strftime("%Y%m%d")
        log_path = f"{log_dir}/{date_str}.jsonl"
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))

    categories = {}
    products_asked = {}
    regions = {}
    for e in entries:
        cat = e.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1
        prod = e.get("product_matched")
        if prod:
            products_asked[prod] = products_asked.get(prod, 0) + 1
        reg = e.get("region", "unknown")
        regions[reg] = regions.get(reg, 0) + 1

    auto = sum(1 for e in entries if e.get("auto_handled"))
    categories_sorted = dict(sorted(categories.items(), key=lambda x: x[1], reverse=True))
    top_cat = max(categories, key=categories.get) if categories else "none"
    top_cat_pct = round((categories.get(top_cat, 0) / max(len(entries), 1)) * 100, 1)

    return {
        "available": True,
        "total": len(entries),
        "auto_handled": auto,
        "escalated": len(entries) - auto,
        "auto_rate": round((auto / max(len(entries), 1)) * 100, 1),
        "categories": categories_sorted,
        "top_category": top_cat,
        "top_category_pct": top_cat_pct,
        "top_products_asked": dict(sorted(products_asked.items(), key=lambda x: x[1], reverse=True)[:5]),
        "regions": regions,
    }


# ─── Website / Meta Pixel ────────────────────────────────────

def collect_website(days_back: int = 1) -> dict:
    """
    Pull website conversion data from Meta Pixel events.
    Meta Pixel tracks: PageView, ViewContent, AddToCart, Purchase.
    """
    pixel_id = os.environ.get("META_PIXEL_ID")
    token = os.environ.get("FACEBOOK_ADS_TOKEN")
    if not pixel_id or not token:
        return {"available": False, "error": "Missing META_PIXEL_ID or token"}

    since = int((datetime.now() - timedelta(days=days_back)).timestamp())
    until = int(datetime.now().timestamp())

    try:
        resp = requests.get(
            f"{FB_API}/{pixel_id}/stats",
            params={
                "access_token": token,
                "start_time": since,
                "end_time": until,
                "aggregation": "event",
            },
        )
        resp.raise_for_status()
        stats = resp.json().get("data", [])

        events = {}
        for s in stats:
            event_name = s.get("event", "unknown")
            count = s.get("count", 0)
            events[event_name] = events.get(event_name, 0) + count

        page_views = events.get("PageView", 0)
        view_content = events.get("ViewContent", 0)
        add_to_cart = events.get("AddToCart", 0)
        purchases = events.get("Purchase", 0)

        return {
            "available": True,
            "page_views": page_views,
            "product_views": view_content,
            "add_to_cart": add_to_cart,
            "purchases": purchases,
            "view_to_cart_rate": round((add_to_cart / max(view_content, 1)) * 100, 1),
            "cart_to_purchase_rate": round((purchases / max(add_to_cart, 1)) * 100, 1),
            "all_events": events,
        }

    except Exception as e:
        return {"available": False, "error": str(e)}


# ─── Notion Lead Stats ───────────────────────────────────────

def collect_notion_leads(days_back: int = 7) -> dict:
    """Pull lead volume and distribution from Notion CRM."""
    api_key = os.environ.get("NOTION_API_KEY")
    db_id = os.environ.get("NOTION_LEADS_DB_ID")
    if not api_key or not db_id:
        return {"available": False, "error": "Missing NOTION_API_KEY or DB ID"}

    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{NOTION_API}/databases/{db_id}/query",
            headers=headers,
            json={
                "filter": {"property": "date_found", "date": {"on_or_after": cutoff}},
                "page_size": 100,
            },
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        categories = {}
        scores = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        platforms = {}

        for page in results:
            props = page.get("properties", {})
            cat = (props.get("category", {}).get("select") or {}).get("name", "unknown")
            score = props.get("intent_score", {}).get("number", 0) or 0
            platform = ""
            for t in props.get("platform", {}).get("rich_text", []):
                platform = t.get("plain_text", "")

            categories[cat] = categories.get(cat, 0) + 1
            if score in scores:
                scores[score] += 1
            platforms[platform] = platforms.get(platform, 0) + 1

        hot_leads = scores.get(5, 0) + scores.get(4, 0)

        return {
            "available": True,
            "total_leads": len(results),
            "hot_leads": hot_leads,
            "by_category": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)),
            "by_score": scores,
            "by_platform": dict(sorted(platforms.items(), key=lambda x: x[1], reverse=True)),
        }

    except Exception as e:
        return {"available": False, "error": str(e)}


# ─── Unified Collection ─────────────────────────────────────

def collect_all(days_back: int = 1) -> dict:
    """
    Pull metrics from all 6 platforms into one unified structure.
    This is the single data object the manager, learning engine,
    and report compiler all read from.
    """
    print("[Analytics] Collecting from all platforms...")

    data = {
        "timestamp": datetime.now().isoformat(),
        "period_days": days_back,
        "facebook_ads": collect_facebook_ads(days_back),
        "instagram": collect_instagram(days_back),
        "tiktok": collect_tiktok(days_back),
        "whatsapp": collect_whatsapp(days_back),
        "website": collect_website(days_back),
        "notion_leads": collect_notion_leads(days_back),
    }

    # Summary counts
    available = sum(1 for k in ["facebook_ads", "instagram", "tiktok", "whatsapp", "website", "notion_leads"]
                    if data[k].get("available"))
    data["platforms_available"] = available
    data["platforms_total"] = 6

    # Save daily snapshot
    os.makedirs("data/analytics", exist_ok=True)
    snapshot_path = f"data/analytics/{datetime.now().strftime('%Y%m%d')}.json"
    with open(snapshot_path, "w") as f:
        json.dump(data, f, indent=2)

    status = []
    for name in ["facebook_ads", "instagram", "tiktok", "whatsapp", "website", "notion_leads"]:
        ok = data[name].get("available", False)
        status.append(f"  {'OK' if ok else 'FAIL':4s} {name}")

    print(f"[Analytics] {available}/6 platforms collected:")
    for s in status:
        print(s)
    print(f"  Saved to {snapshot_path}")

    return data


def load_latest_analytics() -> Optional[dict]:
    """Load the most recent analytics snapshot."""
    files = sorted(glob.glob("data/analytics/*.json"), reverse=True)
    if not files:
        return None
    with open(files[0]) as f:
        return json.load(f)


def load_analytics_range(days: int = 7) -> list:
    """Load multiple days of analytics for trend analysis."""
    snapshots = []
    for d in range(days):
        date_str = (datetime.now() - timedelta(days=d)).strftime("%Y%m%d")
        path = f"data/analytics/{date_str}.json"
        if os.path.exists(path):
            with open(path) as f:
                snapshots.append(json.load(f))
    return snapshots


if __name__ == "__main__":
    result = collect_all(days_back=1)
    print(f"\nPlatforms available: {result['platforms_available']}/6")
