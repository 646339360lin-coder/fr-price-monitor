from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import random
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

from daily_price_refresh import USER_AGENT
from multi_market_price_refresh import (
    add_market_cookies,
    load_marketplace,
    normalize_product_url,
    scrape_product,
    set_delivery_postcode,
)


def api_request(path: str, token: str, method: str = "GET", payload: Any = None) -> Any:
    base_url = os.environ.get("PRICE_MONITOR_URL", "https://price-ingest.tentoki.online")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "tentoki-price-monitor/1.0",
        },
    )
    try:
        with urlopen(request, timeout=90) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Competitor API {method} {path} failed: HTTP {exc.code} {detail}") from exc


MAX_SCREENSHOT_BYTES = 1_000_000


def compress_screenshot(raw: bytes, max_bytes: int = MAX_SCREENSHOT_BYTES) -> bytes:
    if len(raw) <= max_bytes:
        return raw

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(io.BytesIO(raw)) as opened:
        image = opened.convert("RGB")

    def encode(candidate: Image.Image, quality: int) -> bytes:
        output = io.BytesIO()
        candidate.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
        return output.getvalue()

    compressed = raw
    for quality in (60, 50, 40, 30, 22):
        compressed = encode(image, quality)
        if len(compressed) <= max_bytes:
            return compressed

    # Preserve the complete page while reducing both dimensions proportionally.
    while len(compressed) > max_bytes and image.width > 320:
        ratio = max(0.65, min(0.88, (max_bytes / len(compressed)) ** 0.5 * 0.94))
        size = (max(320, int(image.width * ratio)), max(1, int(image.height * ratio)))
        image = image.resize(size, Image.Resampling.LANCZOS)
        for quality in (45, 35, 25, 18):
            compressed = encode(image, quality)
            if len(compressed) <= max_bytes:
                return compressed

    if len(compressed) > max_bytes:
        raise RuntimeError(f"Unable to compress full-page screenshot below {max_bytes} bytes")
    return compressed


async def capture_page(page: Any) -> bytes:
    try:
        raw = await page.screenshot(type="jpeg", quality=70, full_page=True)
    except Exception:
        raw = await page.screenshot(type="jpeg", quality=70, full_page=True, animations="disabled")
    screenshot = compress_screenshot(raw)
    print(f"  screenshot compressed: {len(raw) / 1024:.0f} KB -> {len(screenshot) / 1024:.0f} KB")
    return screenshot


def page_matches_asin(page_url: str, asin: str) -> bool:
    normalized_url = page_url.upper()
    return f"/DP/{asin}" in normalized_url or f"/GP/PRODUCT/{asin}" in normalized_url


async def run(args: argparse.Namespace) -> int:
    token = os.environ.get("PRICE_MONITOR_INGEST_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PRICE_MONITOR_INGEST_TOKEN is required")

    market = load_marketplace(args.market, Path(args.marketplace_file))
    query = urlencode({"market": market["code"]})
    registry = api_request(f"/api/ingest/competitors?{query}", token)
    products = registry.get("products") or []
    if args.limit:
        products = products[: args.limit]
    if not products:
        print(f"{market['code']} has no active competitors; nothing to capture")
        api_request(f"/api/ingest/competitors/cleanup?{query}", token, method="POST", payload={})
        return 0

    from playwright.async_api import async_playwright

    context_options = {
        "user_agent": USER_AGENT,
        "locale": market["locale"],
        "timezone_id": market["timezone"],
        "viewport": {"width": 1365, "height": 900},
        "extra_http_headers": {"Accept-Language": market["accept_language"]},
    }
    uploaded = 0
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(**context_options)
        await add_market_cookies(context, market)
        page = await context.new_page()
        location = await set_delivery_postcode(
            page,
            market["postcode"],
            market,
            normalize_product_url(products[0], market),
        )
        print(f"{market['site']} competitor delivery location: {location or 'not captured'}")

        for index, product in enumerate(products, start=1):
            asin = str(product["asin"]).upper()
            source = {
                "id": asin,
                "asin": asin,
                "brand": "Competitor",
                "category": product["benchmark_type"],
                "type": product["benchmark_type"],
            }
            print(f"[{index}/{len(products)}] {market['code']} competitor {asin}")
            record = await scrape_product(page, source, market, market["postcode"])
            if not page_matches_asin(page.url, asin):
                print(
                    f"  screenshot skipped because browser ended on {page.url}",
                    file=sys.stderr,
                )
                continue
            screenshot = await capture_page(page)
            api_request(
                "/api/ingest/competitor-result",
                token,
                method="POST",
                payload={
                    "market": market["code"],
                    "record": record,
                    "screenshot_content_type": "image/jpeg",
                    "screenshot_base64": base64.b64encode(screenshot).decode("ascii"),
                },
            )
            uploaded += 1
            if index < len(products):
                await asyncio.sleep(random.uniform(args.min_delay, args.max_delay))

        await context.close()
        await browser.close()

    cleanup = api_request(
        f"/api/ingest/competitors/cleanup?{query}", token, method="POST", payload={}
    )
    print(
        f"{market['code']} uploaded {uploaded} competitor snapshots; "
        f"expired={cleanup.get('deleted', 0)}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture daily Amazon competitor pages")
    parser.add_argument("--market", required=True, choices=("UK", "DE", "IT", "ES"))
    parser.add_argument("--marketplace-file", default="marketplaces.json")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
