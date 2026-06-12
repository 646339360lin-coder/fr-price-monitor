from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from price_history_manager import merge_price_results

if TYPE_CHECKING:
    from playwright.async_api import Page


PRODUCT_LIST = Path("product_list.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36 TentokiPriceMonitor/1.0"
)
AMAZON_FR_HOST = "www.amazon.fr"
CLEARANCE_WORDS = ("clearance", "déstockage", "destockage", "liquidation", "soldes")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_product_list(path: Path = PRODUCT_LIST) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing product list: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    products = payload.get("products", payload if isinstance(payload, list) else [])
    return [p for p in products if p.get("enabled", True) and p.get("url")]


def normalize_product_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Invalid product URL: {url}")
    if "amazon.fr" not in parsed.netloc:
        raise ValueError(f"Only Amazon.fr URLs are allowed in this project: {url}")
    asin = extract_asin(url)
    if asin:
        return f"https://www.amazon.fr/dp/{asin}"
    return url


def extract_asin(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", url)
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Z0-9]{10})\b", url)
    return match.group(1) if match else None


def robots_allowed(url: str, user_agent: str = USER_AGENT) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception as exc:
        print(f"robots.txt unavailable for {parsed.netloc}: {exc}", file=sys.stderr)
        return False
    return parser.can_fetch(user_agent, url)


async def scrape_product(page: "Page", product: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    url = normalize_product_url(product["url"])
    if dry_run:
        return build_error_record(product, url, "dry_run")

    if not robots_allowed(url):
        return build_error_record(product, url, "blocked_by_robots_txt")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(1200)
    except Exception as exc:
        if exc.__class__.__name__ == "TimeoutError":
            return build_error_record(product, url, "timeout")
        return build_error_record(product, url, f"navigation_error: {exc}")

    html = await page.content()
    title = await safe_text(page, "#productTitle")
    structured = await extract_structured_product(page)
    embedded = extract_embedded_prices(html)
    dom_prices = await extract_dom_prices(page)
    page_text = ((title or "") + " " + html[:50_000]).lower()
    clearance = any(word in page_text for word in CLEARANCE_WORDS)

    current_price = first_number(
        structured.get("price"),
        embedded.get("current_price"),
        dom_prices.get("current_price"),
    )
    msrp_price = first_number(
        structured.get("msrp_price"),
        embedded.get("msrp_price"),
        None if clearance else dom_prices.get("msrp_price"),
    )

    promo = await extract_promotion_status(page)
    availability = await safe_text(page, "#availability, #outOfStock")
    record = {
        "product_id": product.get("id") or extract_asin(url) or url,
        "asin": extract_asin(url),
        "product_name": structured.get("name") or title or product.get("name"),
        "brand": structured.get("brand") or product.get("brand"),
        "category": product.get("category"),
        "model": product.get("model"),
        "current_price": current_price,
        "msrp_price": msrp_price,
        "currency": structured.get("currency") or "EUR",
        "promotion_status": promo,
        "availability": availability,
        "product_url": url,
        "scraped_at": utc_now_iso(),
        "source": "amazon.fr",
        "price_source": structured.get("price_source") or embedded.get("price_source") or dom_prices.get("price_source"),
        "msrp_source": structured.get("msrp_source") or embedded.get("msrp_source") or dom_prices.get("msrp_source"),
        "clearance_detected": clearance,
        "status": "ok" if current_price is not None else "price_missing",
    }
    return record


async def extract_structured_product(page: "Page") -> dict[str, Any]:
    data = await page.evaluate(
        """() => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
          .map((node) => node.textContent)
          .filter(Boolean)"""
    )
    for raw in data:
        for item in parse_json_fragments(raw):
            product = find_product_jsonld(item)
            if not product:
                continue
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                offers = {}
            brand = product.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            price_spec = offers.get("priceSpecification") or {}
            if isinstance(price_spec, list):
                price_spec = price_spec[0] if price_spec else {}
            if not isinstance(price_spec, dict):
                price_spec = {}
            return {
                "name": product.get("name"),
                "brand": brand,
                "price": normalize_price(offers.get("price") or offers.get("lowPrice")),
                "currency": offers.get("priceCurrency"),
                "msrp_price": normalize_price(offers.get("highPrice") or price_spec.get("price")),
                "price_source": "json_ld",
                "msrp_source": "json_ld",
            }
    return {}


def parse_json_fragments(raw: str) -> list[Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return []


def find_product_jsonld(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    item_type = item.get("@type")
    if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
        return item
    graph = item.get("@graph")
    if isinstance(graph, list):
        for node in graph:
            found = find_product_jsonld(node)
            if found:
                return found
    return None


def extract_embedded_prices(html: str) -> dict[str, Any]:
    patterns = [
        r'"priceToPay"\s*:\s*\{.*?"amount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"displayPrice"\s*:\s*"([^"]+)"',
        r'"basisPrice"\s*:\s*\{.*?"amount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"listPrice"\s*:\s*\{.*?"amount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
    ]
    prices = [normalize_price(match.group(1)) for pattern in patterns for match in re.finditer(pattern, html, re.S)]
    prices = [p for p in prices if p is not None]
    result: dict[str, Any] = {}
    if prices:
        result["current_price"] = prices[0]
        result["price_source"] = "embedded_json"
    if len(prices) > 1:
        result["msrp_price"] = max(prices)
        result["msrp_source"] = "embedded_json"
    return result


async def extract_dom_prices(page: "Page") -> dict[str, Any]:
    current = await safe_text(
        page,
        ".a-price.aok-align-center .a-offscreen, #corePrice_feature_div .a-price .a-offscreen, "
        "#apex_desktop .a-price .a-offscreen, .priceToPay .a-offscreen",
    )
    msrp = await safe_text(
        page,
        ".basisPrice .a-offscreen, .a-text-price .a-offscreen, "
        "#corePriceDisplay_desktop_feature_div span.a-text-price .a-offscreen",
    )
    return {
        "current_price": normalize_price(current),
        "msrp_price": normalize_price(msrp),
        "price_source": "dom_fallback" if current else None,
        "msrp_source": "dom_fallback" if msrp else None,
    }


async def extract_promotion_status(page: "Page") -> str | None:
    selectors = [
        "#couponText",
        ".couponBadge",
        "#dealBadge_feature_div",
        ".savingsPercentage",
        "#promoPriceBlockMessage_feature_div",
    ]
    chunks = []
    for selector in selectors:
        text = await safe_text(page, selector)
        if text:
            chunks.append(text)
    return " | ".join(dict.fromkeys(chunks)) or None


async def safe_text(page: "Page", selector: str) -> str | None:
    try:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            return None
        text = await locator.inner_text(timeout=2500)
    except Exception:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).replace("\u00a0", " ").replace("EUR", "").replace("€", "")
    match = re.search(r"([0-9]+(?:[.,][0-9]{1,2})?)", text.replace(" ", ""))
    if not match:
        return None
    return round(float(match.group(1).replace(",", ".")), 2)


def first_number(*values: Any) -> float | None:
    for value in values:
        number = normalize_price(value)
        if number is not None:
            return number
    return None


def build_error_record(product: dict[str, Any], url: str, status: str) -> dict[str, Any]:
    return {
        "product_id": product.get("id") or extract_asin(url) or url,
        "asin": extract_asin(url),
        "product_name": product.get("name"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "model": product.get("model"),
        "current_price": None,
        "msrp_price": None,
        "currency": "EUR",
        "promotion_status": None,
        "availability": None,
        "product_url": url,
        "scraped_at": utc_now_iso(),
        "source": "amazon.fr",
        "status": status,
    }


async def run(args: argparse.Namespace) -> int:
    products = load_product_list(Path(args.product_list))
    if args.limit:
        products = products[: args.limit]
    if not products:
        print("No enabled products with URLs found in product_list.json")
        return 1

    results: list[dict[str, Any]] = []
    if args.dry_run:
        for index, product in enumerate(products, start=1):
            url = normalize_product_url(product["url"])
            print(f"[{index}/{len(products)}] dry-run {product.get('brand')} {product.get('model')} {url}")
            results.append(build_error_record(product, url, "dry_run"))
        latest = merge_price_results(results)
        print(f"Dry-run wrote {len(latest['products'])} latest records.")
        return 0

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headful)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1365, "height": 900},
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6"},
        )
        page = await context.new_page()
        for index, product in enumerate(products, start=1):
            url = normalize_product_url(product["url"])
            print(f"[{index}/{len(products)}] {product.get('brand')} {product.get('model')} {url}")
            try:
                record = await scrape_product(page, product, dry_run=args.dry_run)
            except Exception as exc:
                record = build_error_record(product, url, f"unexpected_error: {exc}")
                print(f"  unexpected error: {exc}", file=sys.stderr)
            results.append(record)
            if index < len(products):
                await asyncio.sleep(random.uniform(args.min_delay, args.max_delay))
        await browser.close()

    latest = merge_price_results(results)
    ok_count = sum(1 for item in latest["products"] if item.get("status") == "ok")
    print(f"Wrote {len(latest['products'])} latest records, {ok_count} ok.")
    return 0 if ok_count or args.allow_empty else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Amazon.fr competitor price refresh")
    parser.add_argument("--product-list", default=str(PRODUCT_LIST))
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--allow-empty", action="store_true", help="Exit 0 even when all prices are missing")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
