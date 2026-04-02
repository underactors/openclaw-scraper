"""
RUGGTECH Marketing Manager — OpenClaw Skill Runner

This replaces manager.py. Instead of hardcoded Python logic,
Claude IS the brain. It reads soul/heart/mind/voice as its identity,
sees the schedule + analytics as context, and calls tools via function calling.

The Python code here is just plumbing:
  - Load context files → build system prompt
  - Register tools → build function definitions
  - Call Claude → handle tool_use responses → loop
  - Send results back to Claude → repeat until Claude says it's done
"""

import os
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

# Import all tool functions
from tools.analytics_collector import (
    collect_all, load_latest_analytics, load_analytics_range
)
from tools.pain_researcher import research_pain_points
from tools.copywriter import (
    run_copywriter, generate_pain_copy, generate_product_copy,
    fetch_products_from_sanity, save_copy_batch
)
from tools.pricing_engine import calculate_price, load_regions, format_for_ad
from tools.renderer import render_batch
from tools.creative_review import (
    send_creative_gallery, send_message, send_photo,
    process_approval_callback, get_approved_creatives
)
from tools.fb_uploader import upload_approved_batch
from tools.social_poster import queue_days_posts, publish_queue
from tools.wa_responder import get_daily_stats as get_wa_stats
from tools.ad_optimizer import (
    run_optimization_cycle, pull_ad_performance, pause_ad, promote_ad
)
from tools.learning_engine import (
    run_weekly_learning, run_cross_platform_analysis,
    update_proven_angles, extract_winning_angle, get_proven_ratio
)


# ─── Context Loader ──────────────────────────────────────────

def load_system_prompt() -> str:
    """
    Load soul.md + heart.md + mind.md + voice.md as Claude's system prompt.
    This is WHO the manager is and HOW it thinks.
    """
    parts = []
    for filename in ["soul.md", "heart.md", "mind.md", "voice.md"]:
        path = Path(filename)
        if path.exists():
            content = path.read_text()
            parts.append(f"--- {filename.upper()} ---\n{content}")
        else:
            print(f"[Runner] Warning: {filename} not found")

    return "\n\n".join(parts)


def load_config_context() -> str:
    """
    Load regions.json, lanes.json, schedule.json as operational context.
    Passed as part of the user message so Claude can reference current config.
    """
    configs = {}
    for filename in ["config/regions.json", "config/lanes.json", "config/schedule.json"]:
        path = Path(filename)
        if path.exists():
            with open(path) as f:
                configs[filename] = json.load(f)

    return json.dumps(configs, indent=2)


def build_situation_briefing(trigger_type: str = "cron", callback_data: str = None, manual_instruction: str = None) -> str:
    """
    Build the user message that tells Claude the current situation.
    This is what Claude sees as "what's happening right now."
    """
    now = datetime.now()
    briefing_parts = [
        f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')} (Trinidad time)",
        f"Trigger: {trigger_type}",
    ]

    if callback_data:
        briefing_parts.append(f"Telegram callback received: {callback_data}")

    if manual_instruction:
        briefing_parts.append(f"Manual instruction from Davon: {manual_instruction}")

    # Load latest analytics summary if available
    analytics = load_latest_analytics()
    if analytics:
        platforms_ok = analytics.get("platforms_available", 0)
        briefing_parts.append(f"Latest analytics: {platforms_ok}/6 platforms reporting")

        fb = analytics.get("facebook_ads", {})
        if fb.get("available"):
            briefing_parts.append(
                f"  FB Ads: ${fb.get('total_spend_usd', 0):.2f} spend, "
                f"{fb.get('total_conversations', 0)} conversations, "
                f"{fb.get('avg_ctr', 0):.1f}% avg CTR"
            )

        wa = analytics.get("whatsapp", {})
        if wa.get("total", 0) > 0:
            briefing_parts.append(
                f"  WhatsApp: {wa['total']} conversations, "
                f"{wa.get('auto_handled', 0)} auto-handled, "
                f"top question: {wa.get('top_category', 'none')}"
            )

    # Load pending creative reviews
    import glob
    pending_batches = glob.glob("output/creatives/batch_*")
    if pending_batches:
        latest_batch = sorted(pending_batches, reverse=True)[0]
        manifest_path = Path(latest_batch) / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            pending = [m for m in manifest if m.get("approved") is None]
            approved = [m for m in manifest if m.get("approved")]
            if pending:
                briefing_parts.append(f"Pending creative review: {len(pending)} items awaiting Davon's approval")
            if approved:
                briefing_parts.append(f"Approved creatives ready to upload: {len(approved)}")

    # Check for errors from previous runs
    error_log = Path("data/last_errors.json")
    if error_log.exists():
        with open(error_log) as f:
            errors = json.load(f)
        if errors:
            briefing_parts.append(f"Previous errors: {len(errors)} — {', '.join(e['tool'] for e in errors[:3])}")

    briefing_parts.append("")
    briefing_parts.append("CONFIG CONTEXT (regions, lanes, schedule):")
    briefing_parts.append(load_config_context())

    briefing_parts.append("")
    briefing_parts.append(
        "Based on the current time, your schedule, and the data above, "
        "decide which tasks to run. Call the appropriate tools. "
        "After completing all tasks, compose any necessary Telegram messages "
        "using the voice.md formatting rules and send them. "
        "If no tasks are due, respond with a brief status note."
    )

    return "\n".join(briefing_parts)


# ─── Tool Registry ───────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "collect_analytics",
        "description": "Pull performance metrics from all 6 platforms (Facebook Ads, Instagram, TikTok, WhatsApp, Website, Notion) into a unified snapshot. Run this first every morning to get fresh data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {"type": "integer", "description": "Number of days of data to collect. Default 1 for daily, 7 for weekly.", "default": 1}
            }
        }
    },
    {
        "name": "research_pain_points",
        "description": "Pull leads from Notion CRM + scrape TikTok comments via Apify, then cluster them into structured pain points using AI. Returns pain categories with frequency data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lane_id": {"type": "string", "description": "Product lane: rugged-phones, suzuki-parts, agritech, or off-grid"},
                "include_tiktok": {"type": "boolean", "description": "Whether to include TikTok comment scraping. Default true.", "default": True}
            },
            "required": ["lane_id"]
        }
    },
    {
        "name": "run_copywriter",
        "description": "Generate both pain point AND product ad copy variations for a lane. Uses latest pain research data + Sanity CMS products. Outputs JSON + CSV.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lane_id": {"type": "string", "description": "Product lane ID"},
                "pain_data_path": {"type": "string", "description": "Optional path to specific pain data file. If omitted, uses most recent."}
            },
            "required": ["lane_id"]
        }
    },
    {
        "name": "render_batch",
        "description": "Render copy variations into 1080x1080 PNG ad images using HTML templates. Input is the JSON copy file path from the copywriter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "copy_data_path": {"type": "string", "description": "Path to the copy JSON file to render"}
            },
            "required": ["copy_data_path"]
        }
    },
    {
        "name": "send_creative_gallery",
        "description": "Send rendered ad creatives to Davon's Telegram for approval. Separates pain posts from product posts. Includes approve/reject buttons per item and batch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_dir": {"type": "string", "description": "Path to the creative batch directory containing manifest.json and PNG files"}
            },
            "required": ["batch_dir"]
        }
    },
    {
        "name": "upload_approved_batch",
        "description": "Upload all approved creatives from a batch to Facebook Ads Manager as PAUSED draft ads. Creates campaigns and ad sets per lane/region as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_dir": {"type": "string", "description": "Path to the creative batch directory"}
            },
            "required": ["batch_dir"]
        }
    },
    {
        "name": "run_optimization_cycle",
        "description": "Daily ad optimization: pull all active ad performance from Facebook, evaluate against mind.md thresholds (separate for pain vs product), pause losers, promote winners, flag remix candidates.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "queue_posts",
        "description": "Select and queue today's organic posts for a lane across all platforms (FB page, IG, TikTok), respecting the pain:product posting ratios in lanes.json.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lane_id": {"type": "string", "description": "Product lane ID"}
            },
            "required": ["lane_id"]
        }
    },
    {
        "name": "get_wa_stats",
        "description": "Get today's WhatsApp conversation statistics: total conversations, auto-handled vs escalated, question categories with percentages, top products asked about.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "run_weekly_learning",
        "description": "Full weekly intelligence cycle: cross-platform analysis (9 insight transfer rules), update proven angles, extract winning angles via AI, calculate proven/experimental ratios.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "run_cross_platform_analysis",
        "description": "Apply the 9 cross-platform insight transfer rules from mind.md. Returns findings like: TikTok search terms for FB targeting, WhatsApp objections for ad copy, IG saves as product signals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days of data to analyze. Default 7.", "default": 7}
            }
        }
    },
    {
        "name": "send_telegram",
        "description": "Send a text message to Davon's Telegram. Use voice.md formatting: numbers first, no fluff, TTD primary currency, max line limits per message type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message text to send. Use Telegram HTML formatting."}
            },
            "required": ["message"]
        }
    },
    {
        "name": "calculate_price",
        "description": "Calculate the selling price for a product in a specific region using the pricing formula from regions.json.",
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier_cost_usd": {"type": "number", "description": "Product cost in USD from supplier"},
                "region_id": {"type": "string", "description": "Region ID from regions.json (tt, caribbean, us, uk, eu, africa)"}
            },
            "required": ["supplier_cost_usd", "region_id"]
        }
    },
    {
        "name": "pause_ad",
        "description": "Pause a specific Facebook ad by ID. Use when an ad falls below mind.md kill thresholds.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string", "description": "Facebook ad ID to pause"}
            },
            "required": ["ad_id"]
        }
    },
    {
        "name": "get_proven_ratio",
        "description": "Get the current proven/experimental content ratio per lane. Per mind.md: 70/30 after 30 days with 5+ winners, 50/50 while building, 30/70 with no proven angles yet.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "load_latest_analytics",
        "description": "Load the most recent daily analytics snapshot from all platforms.",
        "input_schema": {"type": "object", "properties": {}}
    },
]


# ─── Tool Executor ───────────────────────────────────────────

def execute_tool(name: str, input_data: dict) -> Any:
    """Execute a tool by name and return the result."""
    executors = {
        "collect_analytics": lambda: collect_all(input_data.get("days_back", 1)),
        "research_pain_points": lambda: research_pain_points(
            input_data["lane_id"], input_data.get("include_tiktok", True)
        ),
        "run_copywriter": lambda: run_copywriter(
            input_data["lane_id"], input_data.get("pain_data_path")
        ),
        "render_batch": lambda: render_batch(input_data["copy_data_path"]),
        "send_creative_gallery": lambda: send_creative_gallery(input_data["batch_dir"]),
        "upload_approved_batch": lambda: upload_approved_batch(input_data["batch_dir"]),
        "run_optimization_cycle": lambda: run_optimization_cycle(),
        "queue_posts": lambda: queue_days_posts(input_data["lane_id"]),
        "get_wa_stats": lambda: get_wa_stats(),
        "run_weekly_learning": lambda: run_weekly_learning(),
        "run_cross_platform_analysis": lambda: run_cross_platform_analysis(
            input_data.get("days", 7)
        ),
        "send_telegram": lambda: send_message(input_data["message"]),
        "calculate_price": lambda: calculate_price(
            input_data["supplier_cost_usd"],
            next(r for r in load_regions() if r["id"] == input_data["region_id"])
        ),
        "pause_ad": lambda: pause_ad(input_data["ad_id"]),
        "get_proven_ratio": lambda: get_proven_ratio(),
        "load_latest_analytics": lambda: load_latest_analytics(),
    }

    executor = executors.get(name)
    if not executor:
        return {"error": f"Unknown tool: {name}"}

    return executor()


# ─── Main Agent Loop ─────────────────────────────────────────

def run_agent(
    trigger_type: str = "cron",
    callback_data: str = None,
    manual_instruction: str = None,
    max_turns: int = 15
) -> dict:
    """
    The core agent loop. Claude reasons, calls tools, gets results, reasons again.
    Continues until Claude stops calling tools or max_turns is reached.
    """
    client = Anthropic()
    system_prompt = load_system_prompt()
    user_message = build_situation_briefing(trigger_type, callback_data, manual_instruction)

    messages = [{"role": "user", "content": user_message}]
    tools_called = []
    errors = []

    print(f"\n{'='*60}")
    print(f"[Agent] Starting cycle: {trigger_type} at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    for turn in range(max_turns):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
        except Exception as e:
            print(f"[Agent] Claude API error: {e}")
            errors.append({"tool": "claude_api", "error": str(e)})
            break

        # Process response content blocks
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check if Claude is done (no more tool calls)
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]
        text_blocks = [b for b in assistant_content if b.type == "text"]

        # Print any text Claude produced
        for block in text_blocks:
            if block.text.strip():
                print(f"[Agent] Claude: {block.text[:200]}...")

        if not tool_uses:
            print(f"[Agent] Claude finished reasoning. No more tool calls.")
            break

        # Execute each tool call
        tool_results = []
        for tool_use in tool_uses:
            tool_name = tool_use.name
            tool_input = tool_use.input
            print(f"[Agent] Calling tool: {tool_name}({json.dumps(tool_input)[:100]})")

            try:
                result = execute_tool(tool_name, tool_input)
                result_str = json.dumps(result, indent=2, default=str)

                # Truncate very large results to stay within context
                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_str,
                })
                tools_called.append({"tool": tool_name, "status": "success"})
                print(f"[Agent] Tool {tool_name} completed successfully")

            except Exception as e:
                error_msg = f"Tool {tool_name} failed: {str(e)}"
                print(f"[Agent] {error_msg}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps({"error": error_msg}),
                    "is_error": True,
                })
                tools_called.append({"tool": tool_name, "status": "failed", "error": str(e)})
                errors.append({"tool": tool_name, "error": str(e)})

        messages.append({"role": "user", "content": tool_results})

        # Brief pause between turns for rate limiting
        time.sleep(1)

    # Check stop reason
    if response.stop_reason == "end_turn":
        print(f"[Agent] Cycle complete: {len(tools_called)} tools called, {len(errors)} errors")
    elif response.stop_reason == "max_tokens":
        print(f"[Agent] Hit max tokens — Claude may have more to say")
    else:
        print(f"[Agent] Stopped: {response.stop_reason}")

    # Save errors for next cycle's briefing
    os.makedirs("data", exist_ok=True)
    with open("data/last_errors.json", "w") as f:
        json.dump(errors, f, indent=2)

    return {
        "trigger": trigger_type,
        "tools_called": len(tools_called),
        "errors": len(errors),
        "turns": turn + 1,
        "tools": tools_called,
        "timestamp": datetime.now().isoformat(),
    }


# ─── Entry Points ────────────────────────────────────────────

def main():
    """Cron entry point — run a normal scheduled cycle."""
    return run_agent(trigger_type="cron")


def handle_webhook(update: dict):
    """Telegram webhook — process approval callbacks."""
    callback = update.get("callback_query", {})
    if callback:
        data = callback.get("data", "")
        return run_agent(trigger_type="webhook", callback_data=data)


def handle_manual(instruction: str):
    """Manual trigger — Davon sends a custom instruction."""
    return run_agent(trigger_type="manual", manual_instruction=instruction)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        instruction = " ".join(sys.argv[1:])
        result = handle_manual(instruction)
    else:
        result = main()

    print(f"\nResult: {json.dumps(result, indent=2)}")
