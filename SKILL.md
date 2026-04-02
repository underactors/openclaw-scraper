# RUGGTECH Marketing Manager — OpenClaw Skill

## Trigger

- **Cron:** Railway runs skill_runner.py every 15 minutes. The runner passes the current time to Claude. Claude checks schedule.json and decides which tasks are due.
- **Webhook:** Telegram button callbacks (approve/reject) trigger the runner with the callback data. Claude processes the approval and decides next steps.
- **Manual:** POST to /run endpoint with a natural language instruction. Claude interprets it and acts.

## Context (loaded as system prompt)

These files are concatenated and passed as Claude's system prompt on every cycle:

1. soul.md — Identity, values, boundaries, content philosophy
2. heart.md — Deep context on Davon, family, goals, current reality
3. mind.md — Operational rules, thresholds, learning logic, cross-platform intelligence
4. voice.md — Telegram message formatting, tone, templates

Config data passed as user context each cycle:
- regions.json — Regional pricing, targeting, CTA per market
- lanes.json — Product line configs, pain sources, posting ratios
- schedule.json — Daily/weekly task timing

## Tools (registered as Claude function calls)

Claude can call any tool. Each returns structured data Claude reasons about before deciding next action.

### Data collection
- collect_analytics() — Pull metrics from all 6 platforms
- research_pain_points(lane_id, include_tiktok) — Notion leads + TikTok comments → clustered pain points
- get_daily_wa_stats() — WhatsApp conversation stats and question categories
- load_latest_analytics() — Most recent analytics snapshot
- load_analytics_range(days) — Multiple days for trend analysis

### Content creation
- generate_pain_copy(lane_id) — Pain point ad variations from scraper data
- generate_product_copy(lane_id) — Product ad variations from Sanity CMS
- render_batch(copy_path) — Copy → 1080x1080 PNG images
- calculate_price(cost, region_id) — Regional price calculation

### Distribution
- send_creative_gallery(batch_dir) — Gallery to Davon's Telegram for approval
- upload_approved_batch(batch_dir) — Approved ads → Facebook Ads Manager
- queue_posts(lane_id) — Queue organic posts per platform ratios
- publish_queue(lane_id, platform) — Publish to FB page / IG / TikTok

### Optimization
- pull_ad_performance(days_back) — Active ad metrics from Facebook
- pause_ad(ad_id) — Pause underperformer
- promote_ad(ad_data) — Promote winner to dedicated ad set
- run_optimization_cycle() — Full daily: pull, evaluate, pause, promote

### Intelligence
- run_cross_platform_analysis(days) — 9 cross-platform insight transfer rules
- update_proven_angles(optimizer_data, analytics) — Top 10 winners per lane
- extract_winning_angle(ad_name, copy, metrics) — Analyze WHY content won
- get_proven_ratio() — Current proven/experimental split
- run_weekly_learning() — Full weekly learning cycle

### Communication
- send_telegram(message) — Message to Davon
- send_telegram_with_buttons(message, buttons) — Message with inline keyboard

## Agent loop

1. Runner loads system prompt (soul + heart + mind + voice) and config context
2. Runner tells Claude: current time, schedule, latest analytics, pending tasks
3. Claude reasons about what to do, calls appropriate tools
4. Tool results return. Claude reasons using mind.md rules.
5. Claude decides: handle autonomously, escalate, or report
6. Claude composes messages using voice.md tone, sends via Telegram
7. Creative review: loop pauses until webhook callback
8. On callback: Claude processes approval, triggers upload if approved

## Self-learning behavior

Claude's reasoning enables behaviors hardcoded logic cannot:
- Pattern recognition across platforms without explicit cross-reference code
- Contextual threshold application considering audience size, seasonality, campaign age
- Natural language reports with genuine insight, not template fills
- Adaptive recommendations beyond what mind.md explicitly covers
- Self-reflection: noting diminishing returns and suggesting new directions
