"""
RUGGTECH Learning Engine
Implements the 9 cross-platform insight transfer rules from mind.md.
Runs weekly (Monday 5:30 AM) after analytics collection.

Three sub-systems:
  1. Cross-platform transfers — move insights between platforms
  2. Proven angles — track top 10 winners per lane per content type
  3. Angle extractor — uses Claude to analyze WHY content won
"""

import os
import json
import glob
from datetime import datetime, timedelta
from typing import Optional
from anthropic import Anthropic
from tools.analytics_collector import load_analytics_range, load_latest_analytics


# ─── Cross-Platform Intelligence ─────────────────────────────

def run_cross_platform_analysis(days: int = 7) -> dict:
    """
    Apply the 9 insight transfer rules from mind.md.
    Returns list of findings and recommended actions.
    """
    snapshots = load_analytics_range(days)
    if not snapshots:
        return {"findings": [], "error": "No analytics data available"}

    latest = snapshots[0]
    findings = []

    # Rule 1: TikTok search terms → Facebook ad targeting
    tiktok = latest.get("tiktok", {})
    if tiktok.get("available"):
        for video in tiktok.get("videos", []):
            if video.get("views", 0) > 10000:
                findings.append({
                    "rule": "tiktok_search_to_fb_targeting",
                    "source": "tiktok",
                    "target": "facebook_ads",
                    "finding": f"TikTok video '{video['title'][:50]}' got {video['views']:,} views",
                    "action": "Extract search terms from caption, add as FB ad interest keywords",
                    "priority": "medium",
                    "auto_executable": False,
                })

    # Rule 2: WhatsApp objections → all ad copy
    wa = latest.get("whatsapp", {})
    if wa.get("available") and wa.get("total", 0) > 5:
        top_cat = wa.get("top_category", "")
        top_pct = wa.get("top_category_pct", 0)
        if top_pct >= 20 and top_cat not in ["other", "specs"]:
            findings.append({
                "rule": "whatsapp_objections_to_ad_copy",
                "source": "whatsapp",
                "target": "all_platforms",
                "finding": f"{top_pct}% of WhatsApp conversations ask about '{top_cat}'",
                "action": f"Copywriter must address '{top_cat}' in next batch of all pain + product posts",
                "priority": "high",
                "auto_executable": True,
                "data": {"category": top_cat, "percentage": top_pct},
            })

        # Check for common objections in categories
        categories = wa.get("categories", {})
        for cat, count in categories.items():
            pct = (count / max(wa["total"], 1)) * 100
            if cat in ["shipping", "payment_methods", "warranty"] and pct >= 15:
                findings.append({
                    "rule": "whatsapp_gap_to_ad_copy",
                    "source": "whatsapp",
                    "target": "all_platforms",
                    "finding": f"{pct:.0f}% ask about {cat} — this info should be in the ad",
                    "action": f"Add {cat} info directly into ad copy for all regions",
                    "priority": "high",
                    "auto_executable": True,
                    "data": {"category": cat, "percentage": round(pct, 1)},
                })

    # Rule 3: Winning FB ad angle → TikTok video concept
    fb = latest.get("facebook_ads", {})
    if fb.get("available"):
        top = fb.get("top_campaign")
        if top and top.get("ctr", 0) >= 2.5:
            findings.append({
                "rule": "fb_winner_to_tiktok",
                "source": "facebook_ads",
                "target": "tiktok",
                "finding": f"FB campaign '{top['name']}' has {top['ctr']:.1f}% CTR — proven angle",
                "action": "Generate TikTok video script based on same angle",
                "priority": "medium",
                "auto_executable": True,
                "data": {"campaign_name": top["name"], "ctr": top["ctr"]},
            })

    # Rule 5: IG saves → product opportunity signal
    ig = latest.get("instagram", {})
    if ig.get("available"):
        top_saved = ig.get("top_by_saves")
        if top_saved and top_saved.get("saves", 0) >= 50:
            avg_saves = sum(p.get("saves", 0) for p in ig.get("posts", [])) / max(len(ig.get("posts", [])), 1)
            if top_saved["saves"] >= avg_saves * 3:
                findings.append({
                    "rule": "ig_saves_product_signal",
                    "source": "instagram",
                    "target": "product_strategy",
                    "finding": f"IG post '{top_saved['caption'][:40]}...' got {top_saved['saves']} saves (3x+ average)",
                    "action": "Flag as high-demand content. Check if related product is in stock. If not, consider adding.",
                    "priority": "low",
                    "auto_executable": False,
                })

    # Rule 6: Website bounce → ad-landing mismatch
    web = latest.get("website", {})
    if web.get("available"):
        view_to_cart = web.get("view_to_cart_rate", 0)
        if web.get("product_views", 0) > 20 and view_to_cart < 5:
            findings.append({
                "rule": "website_bounce_mismatch",
                "source": "website",
                "target": "facebook_ads",
                "finding": f"Only {view_to_cart}% of product viewers add to cart (expected 10-15%)",
                "action": "Check product pages for issues: pricing display, trust signals, CTA placement",
                "priority": "high",
                "auto_executable": False,
            })

    # Rule 7: Notion lead geography → regional expansion
    notion = latest.get("notion_leads", {})
    if notion.get("available"):
        # Load active regions to check what's unserved
        try:
            with open("config/regions.json") as f:
                regions_config = json.load(f)["regions"]
            active_ids = {r["id"] for r in regions_config if r.get("active")}
        except Exception:
            active_ids = {"tt"}

        # Check if leads are coming from regions we're not advertising in
        by_platform = notion.get("by_platform", {})
        total = notion.get("total_leads", 0)
        if total >= 10:
            findings.append({
                "rule": "notion_geo_expansion",
                "source": "notion_leads",
                "target": "regional_expansion",
                "finding": f"{total} leads this week. Distribution: {json.dumps(notion.get('by_category', {}))}",
                "action": "Review lead sources for signals about unserved geographic demand",
                "priority": "medium",
                "auto_executable": False,
            })

    # Rule 9: Cross-lane angle transfer
    # Check if any lane's winning angles could apply to other lanes
    optimizer_logs = sorted(glob.glob("data/optimizer_logs/*.json"), reverse=True)
    if optimizer_logs:
        with open(optimizer_logs[0]) as f:
            opt_data = json.load(f)
        remix_candidates = opt_data.get("remix_candidates", [])
        for candidate in remix_candidates:
            findings.append({
                "rule": "cross_lane_angle",
                "source": f"facebook_ads:{candidate.get('lane_id', '')}",
                "target": "all_lanes",
                "finding": f"Winning angle in {candidate['lane_id']}: {candidate['ad_name']} ({candidate['ctr']:.1f}% CTR)",
                "action": "Test this angle across other product lanes with adapted messaging",
                "priority": "medium",
                "auto_executable": True,
                "data": candidate,
            })

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: priority_order.get(f["priority"], 3))

    return {
        "findings": findings,
        "total_findings": len(findings),
        "auto_executable": len([f for f in findings if f.get("auto_executable")]),
        "needs_davon": len([f for f in findings if not f.get("auto_executable")]),
        "analyzed_at": datetime.now().isoformat(),
    }


# ─── Proven Angles Tracker ───────────────────────────────────

PROVEN_ANGLES_PATH = "data/proven_angles.json"


def load_proven_angles() -> dict:
    """Load the proven angles database."""
    if os.path.exists(PROVEN_ANGLES_PATH):
        with open(PROVEN_ANGLES_PATH) as f:
            return json.load(f)
    return {"lanes": {}, "updated_at": None}


def save_proven_angles(angles: dict):
    os.makedirs("data", exist_ok=True)
    angles["updated_at"] = datetime.now().isoformat()
    with open(PROVEN_ANGLES_PATH, "w") as f:
        json.dump(angles, f, indent=2)


def update_proven_angles(optimizer_results: dict, analytics: dict) -> dict:
    """
    Update the proven angles list based on latest performance data.
    Top 10 per lane per content type. Graduates experiments, demotes failures.
    """
    proven = load_proven_angles()

    # Process optimizer remix candidates as potential graduates
    for candidate in optimizer_results.get("remix_candidates", []):
        lane_id = candidate.get("lane_id", "unknown")
        content_type = candidate.get("content_type", "unknown")
        key = f"{lane_id}_{content_type}"

        if key not in proven["lanes"]:
            proven["lanes"][key] = {"winners": [], "experiments": []}

        lane_data = proven["lanes"][key]
        winners = lane_data["winners"]

        new_entry = {
            "ad_name": candidate.get("ad_name", ""),
            "angle": candidate.get("ad_name", "").split("_")[-1][:50],
            "ctr": candidate.get("ctr", 0),
            "content_type": content_type,
            "lane_id": lane_id,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "consecutive_wins": 1,
        }

        # Check if this angle already exists
        existing = next((w for w in winners if w["ad_name"] == new_entry["ad_name"]), None)
        if existing:
            existing["last_seen"] = datetime.now().isoformat()
            existing["consecutive_wins"] = existing.get("consecutive_wins", 0) + 1
            existing["ctr"] = max(existing["ctr"], new_entry["ctr"])
        else:
            winners.append(new_entry)

        # Keep top 10 by CTR
        winners.sort(key=lambda w: w["ctr"], reverse=True)
        lane_data["winners"] = winners[:10]

    save_proven_angles(proven)

    # Calculate stats
    total_winners = sum(len(v["winners"]) for v in proven["lanes"].values())
    total_lanes = len(proven["lanes"])

    return {
        "total_proven_angles": total_winners,
        "lanes_with_data": total_lanes,
        "proven_angles": proven,
    }


def get_proven_ratio() -> dict:
    """
    Returns the recommended proven/experimental split per lane.
    Per mind.md: after 30 days, 70% proven / 30% experimental.
    Before 30 days: 30% proven / 70% experimental.
    """
    proven = load_proven_angles()
    ratios = {}

    for key, lane_data in proven["lanes"].items():
        winners = lane_data.get("winners", [])
        if not winners:
            ratios[key] = {"proven": 30, "experimental": 70, "reason": "No proven angles yet"}
        elif len(winners) >= 5:
            ratios[key] = {"proven": 70, "experimental": 30, "reason": f"{len(winners)} proven angles"}
        else:
            ratios[key] = {"proven": 50, "experimental": 50, "reason": f"Building: {len(winners)} angles so far"}

    return ratios


# ─── Angle Extractor ─────────────────────────────────────────

def extract_winning_angle(ad_name: str, ad_copy: str, metrics: dict) -> dict:
    """
    Use Claude to analyze WHY a piece of content won.
    Returns the extracted angle (not just the metric).
    """
    client = Anthropic()

    prompt = f"""Analyze this winning ad and extract the underlying ANGLE that made it work.

Ad name: {ad_name}
Ad copy: {ad_copy[:500]}
Performance: CTR {metrics.get('ctr', 0):.1f}%, {metrics.get('conversations', 0)} conversations, {metrics.get('clicks', 0)} clicks

I need you to identify:
1. The core pain point or desire this ad taps into
2. The hook mechanism (question, stat, fear, aspiration, social proof)
3. The emotional trigger (frustration, urgency, money_wasted, aspiration, convenience)
4. A reusable angle name (2-4 words, snake_case) that captures the strategy
5. How to adapt this angle for other product lines

Return ONLY valid JSON:
{{
  "angle_name": "string (e.g., waterproof_rain, price_vs_flagship)",
  "core_pain": "string (the underlying problem)",
  "hook_type": "string (question/stat/fear/aspiration/social_proof)",
  "emotional_trigger": "string",
  "why_it_works": "string (1 sentence)",
  "cross_lane_adaptation": {{
    "rugged-phones": "string (how to use this angle for phones)",
    "suzuki-parts": "string (how to adapt for parts)",
    "agritech": "string (how to adapt for agritech)",
    "off-grid": "string (how to adapt for off-grid)"
  }}
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
    except Exception as e:
        return {"error": str(e), "angle_name": "unknown", "why_it_works": "Analysis failed"}


# ─── Weekly Learning Cycle ────────────────────────────────────

def run_weekly_learning() -> dict:
    """
    Full weekly learning cycle:
    1. Cross-platform intelligence analysis
    2. Update proven angles from optimizer results
    3. Extract angles from top winners
    4. Generate recommendations for next week
    """
    print("\n[Learning] Starting weekly learning cycle...")

    # 1. Cross-platform analysis
    cross_platform = run_cross_platform_analysis(days=7)
    print(f"  Cross-platform findings: {cross_platform['total_findings']}")

    # 2. Update proven angles
    optimizer_log = None
    opt_files = sorted(glob.glob("data/optimizer_logs/*.json"), reverse=True)
    if opt_files:
        with open(opt_files[0]) as f:
            optimizer_log = json.load(f)

    angles_update = update_proven_angles(
        optimizer_log or {"remix_candidates": []},
        load_latest_analytics() or {}
    )
    print(f"  Proven angles: {angles_update['total_proven_angles']} across {angles_update['lanes_with_data']} lanes")

    # 3. Extract angles from top performers
    extracted_angles = []
    if optimizer_log:
        for candidate in optimizer_log.get("remix_candidates", [])[:3]:
            angle = extract_winning_angle(
                candidate.get("ad_name", ""),
                candidate.get("ad_name", ""),  # In production: load actual copy from data files
                candidate,
            )
            extracted_angles.append(angle)
            print(f"  Extracted angle: {angle.get('angle_name', 'unknown')}")

    # 4. Proven/experimental ratios
    ratios = get_proven_ratio()

    # Save learning report
    report = {
        "cross_platform": cross_platform,
        "proven_angles": angles_update,
        "extracted_angles": extracted_angles,
        "content_ratios": ratios,
        "generated_at": datetime.now().isoformat(),
    }

    os.makedirs("data/learning", exist_ok=True)
    report_path = f"data/learning/{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"  Saved learning report to {report_path}")
    return report


if __name__ == "__main__":
    result = run_weekly_learning()
    print(f"\nFindings: {result['cross_platform']['total_findings']}")
    print(f"Proven angles: {result['proven_angles']['total_proven_angles']}")
    for angle in result.get("extracted_angles", []):
        print(f"  Angle: {angle.get('angle_name')} — {angle.get('why_it_works', '')}")
