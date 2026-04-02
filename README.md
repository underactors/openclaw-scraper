#  Marketing Manager By underactors

AI-powered marketing system that runs 4 product lines across 6 international regions with autonomous ad creation, optimization, and reporting via Telegram.

## Architecture

```
soul.md          → WHO the manager is (identity, values, boundaries)
heart.md         → WHO it serves (Davon's context, goals, preferences)
mind.md          → HOW it thinks (thresholds, rules, learning logic)
voice.md         → HOW it communicates (Telegram formatting, tone)
config/
  regions.json   → Multi-region pricing (6 regions, your markup sliders)
  lanes.json     → Product line configs (4 lanes with pain/product ratios)
  schedule.json  → Cron timing for all daily/weekly tasks
tools/
  pricing_engine.py    → Calculates regional prices from supplier cost
  pain_researcher.py   → Pulls Notion leads + TikTok comments, clusters pain points via Claude
  copywriter.py        → Generates PAIN + PRODUCT ad copy variations
  renderer.py          → Renders copy into 1080x1080 PNG ad images
  creative_review.py   → Sends gallery to Telegram for Davon's approval
  fb_uploader.py       → Bulk uploads approved ads to Facebook Ads Manager
  social_poster.py     → Posts pain + product content to FB/IG/TikTok
  wa_responder.py      → Auto-replies to WhatsApp inquiries, logs for learning
  ad_optimizer.py      → Daily: pauses losers, promotes winners, flags remix candidates
```

## Two Content Types

Every piece of content is either:
- **Pain post** (source: lead gen scraper + TikTok comments) — speaks to the PROBLEM, builds awareness
- **Product post** (source: Sanity CMS) — showcases the SOLUTION, converts sales

They work as a funnel: pain posts build warm audiences → product posts retarget and convert them.

## Setup

### 1. Prerequisites (30 minutes)
- Add `ads_management` permission to your Meta app
- Create Telegram bot via @BotFather
- Get Claude API key from console.anthropic.com
- (Optional) Create Apify account for TikTok comment scraping
- (Optional) Switch RUGGTECH TikTok to Business Account

### 2. Install
```bash
cd ruggtech-marketing-manager
pip install -r requirements.txt --break-system-packages
playwright install chromium  # For ad image rendering
cp .env.example .env
# Fill in your API keys
```

### 3. Test each tool individually
```bash
# Test pricing engine
python -m tools.pricing_engine

# Test pain research (needs NOTION_API_KEY + ANTHROPIC_API_KEY)
python -m tools.pain_researcher rugged-phones

# Test copywriter (needs above + SANITY_API_TOKEN)
python -m tools.copywriter rugged-phones

# Test renderer (needs playwright)
python -m tools.renderer data/copy_rugged-phones_latest.json

# Test creative review (needs TELEGRAM_BOT_TOKEN)
python -m tools.creative_review output/creatives/batch_latest

# Test ad optimizer (needs FACEBOOK_ADS_TOKEN)
python -m tools.ad_optimizer

# Test WhatsApp stats
python -m tools.wa_responder
```

### 4. Pipeline test (full cycle)
```bash
# 1. Research pain points
python -m tools.pain_researcher rugged-phones

# 2. Generate copy (uses latest pain data + Sanity products)
python -m tools.copywriter rugged-phones

# 3. Render images
python -m tools.renderer data/copy_rugged-phones_YYYYMMDD_HHMM.json

# 4. Send to Telegram for review
python -m tools.creative_review output/creatives/batch_YYYYMMDD_HHMM

# 5. After approval: upload to Facebook
python -m tools.fb_uploader output/creatives/batch_YYYYMMDD_HHMM
```

## Product Lines (Lanes)

| Lane | Sanity Types | Pain:Product Ratio | Priority |
|------|-------------|-------------------|----------|
| Rugged Phones | product, phone | 60:40 (FB) / 75:25 (TikTok) | 1 |
| Suzuki Parts | car | 55:45 (FB) / 70:30 (TikTok) | 2 |
| Agritech | agritechPage | 70:30 (FB) / 80:20 (TikTok) | 3 |
| Off-Grid | offgrid | 60:40 (FB) / 75:25 (TikTok) | 4 |

## Regions

| Region | Currency | Markup | Sales Channel |
|--------|----------|--------|---------------|
| Trinidad & Tobago | TTD | 35% base | WhatsApp |
| Caribbean (CARICOM) | USD | 35% + 15% | WhatsApp |
| United States | USD | 35% + 25% | Website |
| United Kingdom | GBP | 35% + 30% + 20% VAT | Website |
| EU | EUR | 35% + 30% + 21% VAT | Website |
| Africa | USD | 35% + 20% | WhatsApp |

Only Trinidad is active by default. Enable others in regions.json when ready.

## Remaining Phases to Build

- **Phase 5**: Analytics collector (pulls metrics from all 6 platforms)
- **Phase 6**: Learning engine (cross-platform intelligence + proven angles tracking)
- **Phase 7**: Manager orchestrator (ties everything together, compiles reports)
- **Phase 8**: Railway deployment (cron, Telegram webhook, autonomous operation)

## Cost

| Item | Monthly USD |
|------|------------|
| Claude API (ad copy) | $3-5 |
| Railway hosting | $5 |
| Facebook Ads (TT only) | $45-60 |
| Apify (TikTok scraping) | $5 |
| **Total (TT launch)** | **$58-75** |

## Built by UNDERACTORS|
