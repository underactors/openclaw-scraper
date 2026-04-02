"""
RUGGTECH Pricing Engine
Calculates product prices per region from regions.json config.
Formula: (cost * (1 + base%) * (1 + region%) * (1 + vat%)) * exchange_rate
"""

import json
import math
from typing import Optional


def load_regions(config_path: str = "config/regions.json") -> list:
    with open(config_path) as f:
        return json.load(f)["regions"]


def calculate_price(supplier_cost_usd: float, region: dict) -> dict:
    base = region["base_markup_percent"]
    regional = region["region_markup_percent"]
    vat = region["vat_percent"]
    rate = region["exchange_rate"]

    pre_vat = supplier_cost_usd * (1 + base / 100) * (1 + regional / 100)
    with_vat = pre_vat * (1 + vat / 100)
    price_local = math.ceil(with_vat * rate)
    price_usd = round(with_vat, 2)

    return {
        "price_local": price_local,
        "price_usd": price_usd,
        "profit_usd": round(price_usd - supplier_cost_usd, 2),
        "effective_markup_pct": round((price_usd / supplier_cost_usd - 1) * 100, 1),
        "currency": region["currency"],
        "symbol": region["currency_symbol"],
        "display": f"{region['currency_symbol']}{price_local:,} {region['currency']}",
        "display_usd": f"{region['currency_symbol']}{price_local:,} {region['currency']} (${price_usd:,.2f} USD)",
        "shipping": region["shipping_note"],
        "payments": region["payment_methods"],
        "region_id": region["id"],
        "region_name": region["name"],
    }


def format_for_ad(supplier_cost_usd: float, region: dict) -> dict:
    """Returns ad-ready strings: price, shipping, payments, CTA."""
    p = calculate_price(supplier_cost_usd, region)
    payments = ", ".join(m.replace("_", " ").title() for m in region["payment_methods"])
    cta = {
        "WHATSAPP_MESSAGE": "Message us on WhatsApp: 868-366-1212",
        "SHOP_NOW": "Shop now at ruggtech.com",
    }.get(region["cta_type"], "Visit ruggtech.com")

    return {**p, "payment_line": payments, "cta_text": cta, "tone": region["tone"]}


def price_all_regions(cost: float, name: str, active_only: bool = True) -> list:
    regions = load_regions()
    if active_only:
        regions = [r for r in regions if r.get("active")]
    return [{**calculate_price(cost, r), "product": name} for r in regions]
