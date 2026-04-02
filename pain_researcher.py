"""
RUGGTECH Pain Point Researcher
Pulls intent data from Notion CRM (lead gen output) + TikTok comments (Apify),
clusters them into structured pain points via Claude API.

This is the bridge between your existing lead gen skill and the ad copy generator.
It does NOT do fresh research — it interprets data you already collected.
"""

import os
import json
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Optional
from anthropic import Anthropic
import os
from dotenv import load_dotenv  # <--- Add this

load_dotenv()


NOTION_API = "https://api.notion.com/v1"
APIFY_API = "https://api.apify.com/v2"


def load_lane(lane_id: str, config_path: str = "config/lanes.json") -> dict:
    with open(config_path) as f:
        lanes = json.load(f)["lanes"]
    return next(l for l in lanes if l["id"] == lane_id)


# ─── Notion Lead Pull ───────────────────────────────────────

def pull_leads_from_notion(
    lane_id: str,
    min_score: int = 3,
    days_back: int = 14
) -> list:
    """
    Pull leads from Notion CRM filtered by product category and intent score.
    Returns list of dicts with intent_text, signals, score, platform, source_url.
    """
    headers = {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    db_id = os.environ["NOTION_LEADS_DB_ID"]
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    payload = {
        "filter": {
            "and": [
                {"property": "Category", "rich_text": {"contains": lane_id}},
                {"property": "Intent Score", "number": {"greater_than_or_equal_to": min_score}},
                {"timestamp": "created_time", "created_time": {"on_or_after": cutoff}},
            ]
        },
        "sorts": [{"property": "Intent Score", "direction": "descending"}],
        "page_size": 100,
    }

    resp = requests.post(f"{NOTION_API}/databases/{db_id}/query", headers=headers, json=payload)
    resp.raise_for_status()

    leads = []
    for page in resp.json().get("results", []):
        props = page["properties"]
        leads.append({
            "intent_text": _get_text(props, "Intent Text"),
            "intent_signals": _get_multi(props, "Intent Signals"),
            "intent_score": _get_number(props, "Intent Score"),
            "platform": _get_text(props, "Platform"),
            "source_url": _get_text(props, "Source URL"),
            "matched_product": _get_text(props, "Matched Product"),
            "source": "notion_leads",
        })

    return leads


def _get_text(props, key):
    p = props.get(key, {})
    if p.get("type") == "rich_text":
        return "".join(t["plain_text"] for t in p.get("rich_text", []))
    if p.get("type") == "title":
        return "".join(t["plain_text"] for t in p.get("title", []))
    if p.get("type") == "url":
        return p.get("url", "")
    if p.get("type") == "select":
        return (p.get("select") or {}).get("name", "")
    return ""


def _get_number(props, key):
    return props.get(key, {}).get("number", 0) or 0


def _get_multi(props, key):
    return [o["name"] for o in props.get(key, {}).get("multi_select", [])]


# ─── TikTok Comment Scraping ────────────────────────────────

def scrape_tiktok_comments(
    search_terms: list,
    max_videos_per_term: int = 5,
    min_likes: int = 50
) -> list:
    """
    Search TikTok for videos matching terms, scrape comments via Apify.
    Returns high-signal comments (min_likes+ likes) as pain point candidates.
    """
    api_key = os.environ.get("APIFY_API_KEY")
    if not api_key:
        print("[TikTok] No APIFY_API_KEY set, skipping TikTok scraping")
        return []

    all_comments = []

    for term in search_terms:
        try:
            # Use Apify TikTok scraper to search and get video URLs
            run_input = {
                "searchQueries": [term],
                "resultsPerPage": max_videos_per_term,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            }

            # Start the actor run
            resp = requests.post(
                f"{APIFY_API}/acts/clockworks~free-tiktok-scraper/runs",
                headers={"Authorization": f"Bearer {api_key}"},
                json=run_input,
                params={"waitForFinish": 120},
            )
            resp.raise_for_status()
            run_data = resp.json()["data"]
            dataset_id = run_data["defaultDatasetId"]

            # Fetch results
            items_resp = requests.get(
                f"{APIFY_API}/datasets/{dataset_id}/items",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"format": "json"},
            )
            items_resp.raise_for_status()
            videos = items_resp.json()

            for video in videos:
                video_url = video.get("webVideoUrl", "")
                if not video_url:
                    continue

                # Now scrape comments for this video
                comments = _scrape_video_comments(api_key, video_url, min_likes)
                all_comments.extend(comments)

        except Exception as e:
            print(f"[TikTok] Error scraping term '{term}': {e}")
            continue

    return all_comments


def _scrape_video_comments(api_key: str, video_url: str, min_likes: int) -> list:
    """Scrape comments from a single TikTok video via Apify."""
    try:
        run_input = {
            "postURLs": [video_url],
            "maxComments": 200,
            "maxReplies": 0,
        }

        resp = requests.post(
            f"{APIFY_API}/acts/clockworks~tiktok-comments-scraper/runs",
            headers={"Authorization": f"Bearer {api_key}"},
            json=run_input,
            params={"waitForFinish": 60},
        )
        resp.raise_for_status()
        dataset_id = resp.json()["data"]["defaultDatasetId"]

        items_resp = requests.get(
            f"{APIFY_API}/datasets/{dataset_id}/items",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"format": "json"},
        )
        items_resp.raise_for_status()

        comments = []
        for item in items_resp.json():
            likes = item.get("diggCount", 0) or item.get("likes", 0) or 0
            text = item.get("text", "").strip()
            if likes >= min_likes and len(text) > 15:
                comments.append({
                    "intent_text": text,
                    "intent_score": min(5, 3 + (likes // 500)),
                    "platform": "tiktok",
                    "source_url": video_url,
                    "likes": likes,
                    "source": "tiktok_comments",
                })

        return comments

    except Exception as e:
        print(f"[TikTok] Error scraping comments for {video_url}: {e}")
        return []


# ─── Deduplication ───────────────────────────────────────────

def deduplicate(items: list, threshold: float = 0.7) -> list:
    """Remove near-duplicate intent_text entries using simple hash + keyword overlap."""
    seen_hashes = set()
    unique = []

    for item in items:
        text = item["intent_text"].lower().strip()
        # Simple word-set hash for fuzzy dedup
        words = set(text.split())
        word_hash = hashlib.md5(" ".join(sorted(words)).encode()).hexdigest()[:12]

        if word_hash not in seen_hashes:
            seen_hashes.add(word_hash)
            unique.append(item)

    return unique


# ─── Claude Clustering ───────────────────────────────────────

def cluster_pain_points(
    items: list,
    lane_id: str,
    lane_name: str
) -> dict:
    """
    Send collected intent data to Claude for clustering into structured pain points.
    Returns dict with pain_categories, each containing extracted pain points.
    """
    if not items:
        return {"product_line": lane_id, "total_analyzed": 0, "pain_categories": []}

    client = Anthropic()

    # Build the intent text block for Claude
    numbered_items = []
    for i, item in enumerate(items[:50], 1):  # Cap at 50 to manage token usage
        source = item.get("platform", "unknown")
        likes = item.get("likes", "")
        likes_str = f" ({likes} likes)" if likes else ""
        numbered_items.append(f"{i}. [{source}{likes_str}] \"{item['intent_text']}\"")

    intent_block = "\n".join(numbered_items)

    prompt = f"""You are analyzing real customer complaints and buying signals collected from Reddit, Facebook, TikTok comments, and local classifieds in Trinidad and the Caribbean.

These are real people expressing real problems related to: {lane_name}

Below are {len(numbered_items)} intent signals. For each one, extract:
- pain_statement: the core problem in their own words (keep their language authentic)
- desired_outcome: what they wish they had
- emotional_trigger: one of [frustration, money_wasted, urgency, fear, aspiration, convenience]
- ad_hook_angle: one of [question, stat, before_after, direct_benefit, social_proof, meme_relatable]

Then cluster all pain points into the top 5 pain categories (e.g., "phone_durability", "water_damage", "battery_life", "price_vs_flagship", "local_availability").

For each category, include:
- category name (snake_case)
- frequency: how many of the signals fall into this category
- the extracted pain points belonging to this category

Return ONLY valid JSON, no markdown backticks, no preamble.

Schema:
{{
  "product_line": "{lane_id}",
  "total_analyzed": {len(numbered_items)},
  "pain_categories": [
    {{
      "category": "string",
      "frequency": number,
      "pain_points": [
        {{
          "pain_statement": "string",
          "desired_outcome": "string",
          "emotional_trigger": "string",
          "ad_hook_angle": "string",
          "source_language": "string (original customer text)",
          "source_platform": "string"
        }}
      ]
    }}
  ]
}}

Intent signals:
{intent_block}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Clean potential markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    return json.loads(text)


# ─── Main Entry Point ────────────────────────────────────────

def research_pain_points(lane_id: str, include_tiktok: bool = True) -> dict:
    """
    Full pipeline: pull leads from Notion + TikTok → deduplicate → cluster via Claude.
    Returns structured pain points ready for the copywriter.
    """
    lane = load_lane(lane_id)
    print(f"\n[PainResearcher] Starting research for lane: {lane['display_name']}")

    # 1. Pull from Notion
    leads = pull_leads_from_notion(lane_id)
    print(f"  Notion leads: {len(leads)}")

    # 2. Pull from TikTok
    tiktok_comments = []
    if include_tiktok and os.environ.get("APIFY_API_KEY"):
        tiktok_terms = lane.get("pain_sources", {}).get("tiktok_search_terms", [])
        if tiktok_terms:
            tiktok_comments = scrape_tiktok_comments(tiktok_terms)
            print(f"  TikTok comments: {len(tiktok_comments)}")

    # 3. Combine and deduplicate
    combined = leads + tiktok_comments
    unique = deduplicate(combined)
    print(f"  After dedup: {len(unique)}")

    if not unique:
        print("  No data to cluster. Returning empty result.")
        return {"product_line": lane_id, "total_analyzed": 0, "pain_categories": []}

    # 4. Cluster via Claude
    print(f"  Clustering {len(unique)} items via Claude...")
    result = cluster_pain_points(unique, lane_id, lane["display_name"])
    
    # 5. Sort categories by frequency
    result["pain_categories"].sort(key=lambda c: c["frequency"], reverse=True)
    
    # 6. Save to file
    output_path = f"data/pain_points_{lane_id}_{datetime.now().strftime('%Y%m%d')}.json"
    os.makedirs("data", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved to {output_path}")

    return result


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lane = sys.argv[1] if len(sys.argv) > 1 else "rugged-phones"
    result = research_pain_points(lane)
    print(f"\nResults for {lane}:")
    for cat in result.get("pain_categories", []):
        print(f"  {cat['category']} (frequency: {cat['frequency']})")
        for pp in cat["pain_points"][:2]:
            print(f"    - \"{pp['pain_statement']}\" [{pp['emotional_trigger']}]")
