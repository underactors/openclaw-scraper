"""
RUGGTECH Ad Renderer
Takes copy variations (JSON from copywriter) and renders them into 1080x1080 PNG images.
Uses HTML templates + Playwright for screenshot capture.

Templates are in templates/ad_templates/ — one HTML file per format.
"""

import os
import json
import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
import os
from dotenv import load_dotenv  # <--- Add this

load_dotenv()



TEMPLATE_DIR = Path("templates/ad_templates")
OUTPUT_DIR = Path("output/creatives")


# ─── Template Definitions ────────────────────────────────────

PAIN_TEMPLATES = {
    "question_hook": """
    <div style="width:1080px;height:1080px;background:#1a1a1a;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:80px;font-family:Arial,sans-serif;">
        <div style="color:#FF6B35;font-size:52px;font-weight:bold;text-align:center;line-height:1.3;margin-bottom:40px;">{headline}</div>
        <div style="color:#cccccc;font-size:28px;text-align:center;line-height:1.6;max-width:900px;">{body}</div>
        <div style="margin-top:auto;display:flex;align-items:center;gap:20px;">
            <div style="color:#888;font-size:22px;">RUGGTECH</div>
        </div>
    </div>""",

    "before_after": """
    <div style="width:1080px;height:1080px;display:flex;font-family:Arial,sans-serif;">
        <div style="flex:1;background:#2d1111;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:50px;">
            <div style="color:#ff4444;font-size:38px;font-weight:bold;margin-bottom:20px;">BEFORE</div>
            <div style="color:#cc8888;font-size:26px;text-align:center;line-height:1.5;">{before_text}</div>
        </div>
        <div style="width:4px;background:#FF6B35;"></div>
        <div style="flex:1;background:#112d11;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:50px;">
            <div style="color:#44ff44;font-size:38px;font-weight:bold;margin-bottom:20px;">AFTER</div>
            <div style="color:#88cc88;font-size:26px;text-align:center;line-height:1.5;">{after_text}</div>
        </div>
    </div>""",

    "stat_card": """
    <div style="width:1080px;height:1080px;background:#0d0d0d;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:80px;font-family:Arial,sans-serif;">
        <div style="color:#FF6B35;font-size:120px;font-weight:bold;">{stat_number}</div>
        <div style="color:#ffffff;font-size:36px;text-align:center;margin-top:20px;line-height:1.4;">{stat_context}</div>
        <div style="color:#888;font-size:24px;text-align:center;margin-top:40px;max-width:800px;line-height:1.5;">{body}</div>
        <div style="margin-top:auto;color:#555;font-size:20px;">RUGGTECH</div>
    </div>""",

    "meme_relatable": """
    <div style="width:1080px;height:1080px;background:#1a1a1a;display:flex;flex-direction:column;font-family:Arial,sans-serif;">
        <div style="background:#FF6B35;padding:30px 50px;">
            <div style="color:#fff;font-size:32px;font-weight:bold;">{headline}</div>
        </div>
        <div style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:60px;">
            <div style="color:#ffffff;font-size:42px;font-weight:bold;line-height:1.3;margin-bottom:30px;">{body}</div>
            <div style="color:#888;font-size:24px;">{cta_text}</div>
        </div>
        <div style="padding:20px 50px;color:#555;font-size:18px;">RUGGTECH</div>
    </div>""",
}

PRODUCT_TEMPLATES = {
    "hero_specs": """
    <div style="width:1080px;height:1080px;background:linear-gradient(135deg,#1a1a2e,#16213e);display:flex;flex-direction:column;justify-content:center;align-items:center;padding:80px;font-family:Arial,sans-serif;">
        <div style="color:#FF6B35;font-size:22px;font-weight:bold;letter-spacing:2px;margin-bottom:20px;">RUGGTECH</div>
        <div style="color:#ffffff;font-size:44px;font-weight:bold;text-align:center;line-height:1.3;margin-bottom:30px;">{product_name}</div>
        <div style="color:#cccccc;font-size:26px;text-align:center;line-height:1.6;max-width:800px;margin-bottom:40px;">{specs_text}</div>
        <div style="background:#FF6B35;color:#fff;font-size:36px;font-weight:bold;padding:15px 50px;border-radius:8px;">{price_display}</div>
        <div style="color:#888;font-size:22px;margin-top:20px;">{shipping}</div>
        <div style="color:#FF6B35;font-size:24px;margin-top:30px;">{cta_text}</div>
    </div>""",

    "price_compare": """
    <div style="width:1080px;height:1080px;background:#0a0a0a;display:flex;flex-direction:column;font-family:Arial,sans-serif;">
        <div style="padding:40px 60px;color:#FF6B35;font-size:28px;font-weight:bold;">Why pay more?</div>
        <div style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:0 60px;gap:30px;">
            <div style="display:flex;justify-content:space-between;align-items:center;padding:25px 30px;background:#1a1a1a;border-radius:12px;">
                <div style="color:#888;font-size:28px;">Samsung Galaxy</div>
                <div style="color:#ff4444;font-size:32px;font-weight:bold;text-decoration:line-through;">{competitor_price}</div>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;padding:25px 30px;background:#1a2a1a;border:2px solid #FF6B35;border-radius:12px;">
                <div style="color:#fff;font-size:28px;font-weight:bold;">{product_name}</div>
                <div style="color:#44ff44;font-size:32px;font-weight:bold;">{price_display}</div>
            </div>
        </div>
        <div style="padding:30px 60px;color:#888;font-size:22px;display:flex;justify-content:space-between;">
            <span>{headline}</span>
            <span style="color:#FF6B35;">RUGGTECH</span>
        </div>
    </div>""",
}


# ─── Rendering Engine ────────────────────────────────────────

async def render_copy_to_images(copy_data_path: str) -> str:
    """
    Takes a copy JSON file, renders each variation to a 1080x1080 PNG.
    Returns path to output directory with all images.
    """
    with open(copy_data_path) as f:
        copy_items = json.load(f)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    batch_dir = OUTPUT_DIR / f"batch_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    
    # Separate by content type
    pain_items = [c for c in copy_items if c.get("content_type") == "pain"]
    product_items = [c for c in copy_items if c.get("content_type") == "product"]
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Renderer] Playwright not installed. Run: pip install playwright && playwright install chromium")
        # Fallback: save HTML files for manual review
        return _save_html_fallback(copy_items, batch_dir)
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1080, "height": 1080})
        
        manifest = []
        
        # Render pain posts
        for i, item in enumerate(pain_items):
            template = _select_pain_template(item)
            html = _fill_template(template, item)
            filename = f"pain_{item['lane_id']}_{item['region_id']}_{i:03d}.png"
            filepath = batch_dir / filename
            
            await page.set_content(f"<html><body style='margin:0;padding:0;'>{html}</body></html>")
            await page.screenshot(path=str(filepath), clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            
            manifest.append({
                "filename": filename,
                "content_type": "pain",
                "lane_id": item["lane_id"],
                "region_id": item["region_id"],
                "platform": item.get("platform", "facebook"),
                "headline": item.get("headline", ""),
                "pain_category": item.get("pain_category", ""),
                "hook_angle": item.get("hook_angle", ""),
            })
        
        # Render product posts
        for i, item in enumerate(product_items):
            template = _select_product_template(item)
            html = _fill_template(template, item)
            filename = f"product_{item['lane_id']}_{item['region_id']}_{i:03d}.png"
            filepath = batch_dir / filename
            
            await page.set_content(f"<html><body style='margin:0;padding:0;'>{html}</body></html>")
            await page.screenshot(path=str(filepath), clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            
            manifest.append({
                "filename": filename,
                "content_type": "product",
                "lane_id": item["lane_id"],
                "region_id": item["region_id"],
                "platform": item.get("platform", "facebook"),
                "product_name": item.get("product_name", ""),
                "price_display": item.get("price_display", ""),
                "headline": item.get("headline", ""),
            })
        
        await browser.close()
    
    # Save manifest
    manifest_path = batch_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    print(f"[Renderer] Generated {len(pain_items)} pain + {len(product_items)} product images in {batch_dir}")
    return str(batch_dir)


def _select_pain_template(item: dict) -> str:
    angle = item.get("hook_angle", "question")
    return PAIN_TEMPLATES.get(angle, PAIN_TEMPLATES["question_hook"])


def _select_product_template(item: dict) -> str:
    benefit = item.get("featured_benefit", "").lower()
    if "price" in benefit or "cheap" in benefit or "afford" in benefit:
        return PRODUCT_TEMPLATES["price_compare"]
    return PRODUCT_TEMPLATES["hero_specs"]


def _fill_template(template: str, item: dict) -> str:
    """Replace template placeholders with copy data."""
    replacements = {
        "{headline}": item.get("headline", ""),
        "{body}": item.get("body", ""),
        "{product_name}": item.get("product_name", ""),
        "{price_display}": item.get("price_display", ""),
        "{cta_text}": item.get("cta_text", ""),
        "{shipping}": item.get("shipping", ""),
        "{specs_text}": item.get("body", ""),
        "{stat_number}": item.get("stat_number", "3x"),
        "{stat_context}": item.get("headline", ""),
        "{before_text}": item.get("before_text", item.get("source_pain", "")),
        "{after_text}": item.get("after_text", item.get("headline", "")),
        "{competitor_price}": item.get("competitor_price", "$4,500 TTD"),
        "{payment_line}": item.get("payment_line", ""),
    }
    result = template
    for key, val in replacements.items():
        result = result.replace(key, str(val))
    return result


def _save_html_fallback(copy_items: list, batch_dir: Path) -> str:
    """When Playwright isn't available, save HTML files for manual review."""
    gallery_html = ['<html><head><style>body{background:#111;font-family:Arial;}.grid{display:flex;flex-wrap:wrap;gap:20px;padding:20px;}.card{border:1px solid #333;border-radius:8px;overflow:hidden;width:540px;}</style></head><body><div class="grid">']
    
    for i, item in enumerate(copy_items):
        ctype = item.get("content_type", "unknown")
        template = _select_pain_template(item) if ctype == "pain" else _select_product_template(item)
        html = _fill_template(template, item)
        scaled = html.replace("1080px", "540px").replace("font-size:52px", "font-size:26px").replace("font-size:44px", "font-size:22px").replace("font-size:36px", "font-size:18px").replace("font-size:28px", "font-size:14px").replace("font-size:26px", "font-size:13px")
        label = f"{ctype} | {item.get('lane_id','')} | {item.get('region_id','')} | {item.get('platform','')}"
        gallery_html.append(f'<div class="card"><div style="padding:8px;color:#888;font-size:12px;">{label}</div>{scaled}</div>')
    
    gallery_html.append('</div></body></html>')
    gallery_path = batch_dir / "gallery.html"
    with open(gallery_path, "w") as f:
        f.write("\n".join(gallery_html))
    
    print(f"[Renderer] Playwright not available. HTML gallery saved to {gallery_path}")
    return str(batch_dir)


# ─── Main ────────────────────────────────────────────────────

def render_batch(copy_data_path: str) -> str:
    """Sync wrapper for the async render pipeline."""
    return asyncio.run(render_copy_to_images(copy_data_path))


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/copy_rugged-phones_latest.json"
    render_batch(path)
