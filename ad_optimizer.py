"""
RUGGTECH Ad Optimizer
Daily cycle that:
  1. Pulls performance data from Facebook Ads API for all active campaigns
  2. Applies kill thresholds from mind.md (separate for pain vs product ads)
  3. Promotes winners to dedicated ad sets with higher budgets
  4. Detects frequency fatigue and triggers fresh creative
  5. Returns summary for the morning report

All thresholds are defined in mind.md and loaded at runtime.
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional
import requests
import os
from dotenv import load_dotenv  # <--- Add this

load_dotenv()



FB_API = "https://graph.facebook.com/v19.0"

# ─── Thresholds from mind.md ────────────────────────────────
# These are the defaults — the manager can override from mind.md parsing

PAIN_KILL = {"min_engagement_rate": 1.0, "max_cost_per_engagement_usd": 0.50, "min_tiktok_completion": 25, "hours_before_eval": 48}
PAIN_SCALE = {"min_engagement_rate": 5.0, "min_tiktok_completion": 60}

PRODUCT_KILL = {"min_ctr": 0.8, "max_cpc_usd": 1.50, "min_conversations": 1, "max_spend_no_conv_ttd": 20, "hours_before_eval": 48}
PRODUCT_SCALE = {"min_ctr": 2.5, "min_cost_per_conv_usd": 0.50, "min_roas": 3.0, "days_before_scale": 7}

FREQUENCY_FATIGUE = 3.0  # Above this = audience seeing ad too many times
REMIX_CTR = 3.0  # Above this CTR = extract angle for new variations
MAX_BUDGET_MULTIPLIER = 2.0  # Scale winners by 2x max


def fb_get(endpoint: str, params: dict = None) -> dict:
    token = os.environ["FACEBOOK_ADS_TOKEN"]
    params = params or {}
    params["access_token"] = token
    resp = requests.get(f"{FB_API}/{endpoint}", params=params)
    resp.raise_for_status()
    return resp.json()


def fb_post(endpoint: str, data: dict) -> dict:
    token = os.environ["FACEBOOK_ADS_TOKEN"]
    data["access_token"] = token
    resp = requests.post(f"{FB_API}/{endpoint}", data=data)
    resp.raise_for_status()
    return resp.json()


# ─── Performance Pull ────────────────────────────────────────

def pull_ad_performance(days_back: int = 3) -> list:
    """Pull performance data for all ads across all RUGGTECH campaigns."""
    ad_account = os.environ["META_AD_ACCOUNT_ID"]
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    until = datetime.now().strftime("%Y-%m-%d")
    
    ads_data = fb_get(
        f"{ad_account}/ads",
        params={
            "fields": "id,name,status,adset_id,campaign_id,creative{id,name}",
            "filtering": json.dumps([{"field": "name", "operator": "CONTAIN", "value": "RUGGTECH_"}]),
            "limit": 200,
        },
    )
    
    results = []
    for ad in ads_data.get("data", []):
        if ad["status"] != "ACTIVE":
            continue
        
        # Get insights for this ad
        try:
            insights = fb_get(
                f"{ad['id']}/insights",
                params={
                    "fields": "impressions,clicks,ctr,cpc,cpm,spend,actions,cost_per_action_type,frequency",
                    "time_range": json.dumps({"since": since, "until": until}),
                },
            )
            
            insight = insights.get("data", [{}])[0] if insights.get("data") else {}
            
            # Parse content type from ad name
            name = ad.get("name", "")
            content_type = "pain" if name.startswith("pain_") else "product"
            
            # Parse lane and region from ad name
            parts = name.split("_")
            lane_id = parts[1] if len(parts) > 1 else "unknown"
            region_id = parts[2] if len(parts) > 2 else "unknown"
            
            # Extract key metrics
            impressions = int(insight.get("impressions", 0))
            clicks = int(insight.get("clicks", 0))
            ctr = float(insight.get("ctr", 0))
            cpc = float(insight.get("cpc", 0))
            spend = float(insight.get("spend", 0))
            frequency = float(insight.get("frequency", 0))
            
            # Extract conversions (WhatsApp conversations or purchases)
            conversations = 0
            purchases = 0
            for action in insight.get("actions", []):
                if action.get("action_type") in ["onsite_conversion.messaging_conversation_started_7d", "contact_total"]:
                    conversations = int(action.get("value", 0))
                elif action.get("action_type") in ["purchase", "offsite_conversion.fb_pixel_purchase"]:
                    purchases = int(action.get("value", 0))
            
            # Hours since ad started (approximate from impressions)
            hours_active = days_back * 24  # Simplified — could use ad created_time
            
            results.append({
                "ad_id": ad["id"],
                "ad_name": name,
                "adset_id": ad["adset_id"],
                "campaign_id": ad["campaign_id"],
                "content_type": content_type,
                "lane_id": lane_id,
                "region_id": region_id,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": ctr,
                "cpc": cpc,
                "spend": spend,
                "frequency": frequency,
                "conversations": conversations,
                "purchases": purchases,
                "hours_active": hours_active,
            })
            
            time.sleep(0.5)  # Rate limit
            
        except Exception as e:
            print(f"[Optimizer] Error getting insights for {ad['id']}: {e}")
    
    return results


# ─── Decision Engine ─────────────────────────────────────────

def evaluate_ads(ads: list) -> dict:
    """
    Apply mind.md thresholds to all ads.
    Returns lists of ads to pause, promote, and remix.
    """
    to_pause = []
    to_promote = []
    to_remix = []
    frequency_fatigue = []
    healthy = []
    
    for ad in ads:
        ct = ad["content_type"]
        hours = ad["hours_active"]
        
        # ── Frequency fatigue check (applies to both types) ──
        if ad["frequency"] > FREQUENCY_FATIGUE:
            frequency_fatigue.append({
                **ad,
                "reason": f"Frequency {ad['frequency']:.1f} > {FREQUENCY_FATIGUE} — audience fatigue",
            })
            continue
        
        # ── Pain post evaluation ──
        if ct == "pain":
            if hours >= PAIN_KILL["hours_before_eval"]:
                engagement_rate = (ad["clicks"] / max(ad["impressions"], 1)) * 100
                
                if engagement_rate < PAIN_KILL["min_engagement_rate"]:
                    to_pause.append({**ad, "reason": f"Engagement {engagement_rate:.1f}% < {PAIN_KILL['min_engagement_rate']}%"})
                elif engagement_rate >= PAIN_SCALE["min_engagement_rate"]:
                    to_promote.append({**ad, "reason": f"Engagement {engagement_rate:.1f}% >= {PAIN_SCALE['min_engagement_rate']}%"})
                else:
                    healthy.append(ad)
                    
                # Remix check
                if ad["ctr"] >= REMIX_CTR:
                    to_remix.append({**ad, "reason": f"CTR {ad['ctr']:.1f}% >= {REMIX_CTR}% — extract angle"})
            else:
                healthy.append(ad)
        
        # ── Product post evaluation ──
        elif ct == "product":
            if hours >= PRODUCT_KILL["hours_before_eval"]:
                if ad["ctr"] < PRODUCT_KILL["min_ctr"]:
                    to_pause.append({**ad, "reason": f"CTR {ad['ctr']:.1f}% < {PRODUCT_KILL['min_ctr']}%"})
                elif ad["cpc"] > PRODUCT_KILL["max_cpc_usd"]:
                    to_pause.append({**ad, "reason": f"CPC ${ad['cpc']:.2f} > ${PRODUCT_KILL['max_cpc_usd']}"})
                elif ad["ctr"] >= PRODUCT_SCALE["min_ctr"]:
                    to_promote.append({**ad, "reason": f"CTR {ad['ctr']:.1f}% >= {PRODUCT_SCALE['min_ctr']}%"})
                else:
                    healthy.append(ad)
                    
                if ad["ctr"] >= REMIX_CTR:
                    to_remix.append({**ad, "reason": f"CTR {ad['ctr']:.1f}% — winning angle, remix"})
            else:
                healthy.append(ad)
    
    return {
        "to_pause": to_pause,
        "to_promote": to_promote,
        "to_remix": to_remix,
        "frequency_fatigue": frequency_fatigue,
        "healthy": healthy,
    }


# ─── Actions ─────────────────────────────────────────────────

def pause_ad(ad_id: str) -> bool:
    """Pause an underperforming ad."""
    try:
        fb_post(ad_id, {"status": "PAUSED"})
        return True
    except Exception as e:
        print(f"[Optimizer] Failed to pause {ad_id}: {e}")
        return False


def promote_ad(ad: dict) -> Optional[str]:
    """
    Promote a winning ad by duplicating it to a dedicated ad set
    with increased budget (2x current).
    """
    ad_account = os.environ["META_AD_ACCOUNT_ID"]
    
    try:
        # Get current ad set budget
        adset_data = fb_get(ad["adset_id"], params={"fields": "daily_budget,targeting"})
        current_budget = int(adset_data.get("daily_budget", 500))
        new_budget = min(current_budget * MAX_BUDGET_MULTIPLIER, 5000)  # Cap at $50 USD
        
        # Create new "winners" ad set
        winner_name = f"RUGGTECH_WINNER_{ad['lane_id']}_{ad['region_id']}_{ad['content_type']}"
        
        result = fb_post(
            f"{ad_account}/adsets",
            {
                "name": winner_name,
                "campaign_id": ad["campaign_id"],
                "daily_budget": int(new_budget),
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "CONVERSIONS",
                "targeting": json.dumps(adset_data.get("targeting", {})),
                "status": "PAUSED",  # Still paused — Davon activates if budget > threshold
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            },
        )
        
        return result.get("id")
    
    except Exception as e:
        print(f"[Optimizer] Failed to promote {ad['ad_id']}: {e}")
        return None


# ─── Main Optimization Cycle ─────────────────────────────────

def run_optimization_cycle() -> dict:
    """
    Full daily optimization cycle:
    1. Pull all active ad performance
    2. Evaluate against thresholds
    3. Pause losers, promote winners
    4. Flag remix candidates
    5. Return summary for morning report
    """
    print("\n[Optimizer] Starting daily optimization cycle...")
    
    # Pull performance
    ads = pull_ad_performance(days_back=3)
    print(f"  Active ads evaluated: {len(ads)}")
    
    if not ads:
        return {"total_ads": 0, "paused": 0, "promoted": 0, "remix_candidates": 0}
    
    # Evaluate
    decisions = evaluate_ads(ads)
    
    # Execute pauses
    paused = 0
    for ad in decisions["to_pause"]:
        if pause_ad(ad["ad_id"]):
            paused += 1
            print(f"  PAUSED: {ad['ad_name']} — {ad['reason']}")
    
    for ad in decisions["frequency_fatigue"]:
        if pause_ad(ad["ad_id"]):
            paused += 1
            print(f"  PAUSED (fatigue): {ad['ad_name']} — {ad['reason']}")
    
    # Execute promotions
    promoted = 0
    for ad in decisions["to_promote"]:
        new_adset = promote_ad(ad)
        if new_adset:
            promoted += 1
            print(f"  PROMOTED: {ad['ad_name']} — {ad['reason']}")
    
    # Log remix candidates (don't auto-trigger — report to manager)
    remix_angles = []
    for ad in decisions["to_remix"]:
        remix_angles.append({
            "ad_name": ad["ad_name"],
            "content_type": ad["content_type"],
            "lane_id": ad["lane_id"],
            "ctr": ad["ctr"],
            "reason": ad["reason"],
        })
        print(f"  REMIX CANDIDATE: {ad['ad_name']} — {ad['reason']}")
    
    # Build summary
    summary = {
        "total_ads": len(ads),
        "paused": paused,
        "promoted": promoted,
        "frequency_fatigued": len(decisions["frequency_fatigue"]),
        "healthy": len(decisions["healthy"]),
        "remix_candidates": remix_angles,
        "pain_ads": len([a for a in ads if a["content_type"] == "pain"]),
        "product_ads": len([a for a in ads if a["content_type"] == "product"]),
        "total_spend": sum(a["spend"] for a in ads),
        "total_conversations": sum(a["conversations"] for a in ads),
        "total_purchases": sum(a["purchases"] for a in ads),
        "top_performer": max(ads, key=lambda a: a["ctr"]) if ads else None,
        "worst_performer": min((a for a in ads if a["impressions"] > 100), key=lambda a: a["ctr"], default=None),
        "timestamp": datetime.now().isoformat(),
    }
    
    # Save daily log
    os.makedirs("data/optimizer_logs", exist_ok=True)
    log_path = f"data/optimizer_logs/{datetime.now().strftime('%Y%m%d')}.json"
    with open(log_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n[Optimizer] Done: {paused} paused, {promoted} promoted, {len(remix_angles)} remix candidates")
    return summary


if __name__ == "__main__":
    result = run_optimization_cycle()
    print(json.dumps(result, indent=2, default=str))
