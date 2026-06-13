from __future__ import annotations

import argparse
import asyncio
import json
import random
import urllib.request
from pathlib import Path
from typing import Any

from daily_price_refresh import DEFAULT_POSTCODE, normalize_price, scrape_product
from price_history_manager import save_json, utc_now_iso


DEFAULT_LATEST_URL = "https://raw.githubusercontent.com/646339360lin-coder/fr-price-monitor/main/price_results_latest.json"


def load_json_source(source: str) -> dict[str, Any]:
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    with Path(source).open("r", encoding="utf-8") as f:
        return json.load(f)


def load_product_list(path: str) -> dict[str, dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    products = payload.get("products", payload if isinstance(payload, list) else [])
    return {p.get("asin") or p.get("id"): p for p in products if p.get("enabled", True) and p.get("url")}


def product_key(record: dict[str, Any]) -> str:
    return str(record.get("asin") or record.get("product_id") or record.get("product_url") or "")


def select_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    records = [r for r in records if product_key(r)]
    if args.asin:
        wanted = {asin.strip().upper() for asin in args.asin.split(",") if asin.strip()}
        return [r for r in records if product_key(r).upper() in wanted]
    if args.sample_size and args.sample_size < len(records):
        rng = random.Random(args.seed)
        return rng.sample(records, args.sample_size)
    return records


def compare_record(github_record: dict[str, Any], frontend_record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    github_price = normalize_price(github_record.get("current_price"))
    frontend_price = normalize_price(frontend_record.get("current_price"))
    github_msrp = normalize_price(github_record.get("msrp_price"))
    frontend_msrp = normalize_price(frontend_record.get("msrp_price"))
    price_delta = round(frontend_price - github_price, 2) if frontend_price is not None and github_price is not None else None
    msrp_delta = round(frontend_msrp - github_msrp, 2) if frontend_msrp is not None and github_msrp is not None else None
    location = frontend_record.get("observer_location") or ""

    issues: list[str] = []
    github_status = github_record.get("status")
    if github_status not in ("ok", "ok_manual"):
        issues.append(f"github_status:{github_status}")
    if frontend_record.get("status") != "ok":
        issues.append(f"frontend_status:{frontend_record.get('status')}")
    if args.postcode and args.postcode not in location:
        issues.append("frontend_location_not_postcode")
    if github_record.get("currency") not in (None, "EUR") or frontend_record.get("currency") != "EUR":
        issues.append("currency_not_eur")
    if github_price is None:
        issues.append("github_price_missing")
    if frontend_price is None:
        issues.append("frontend_price_missing")
    if price_delta is not None and abs(price_delta) > args.price_tolerance:
        issues.append("price_mismatch")
    if msrp_delta is not None and abs(msrp_delta) > args.msrp_tolerance:
        issues.append("msrp_mismatch")

    return {
        "asin": product_key(github_record),
        "brand": github_record.get("brand") or frontend_record.get("brand"),
        "model": github_record.get("model") or frontend_record.get("model"),
        "product_url": github_record.get("product_url") or frontend_record.get("product_url"),
        "github": {
            "current_price": github_price,
            "msrp_price": github_msrp,
            "currency": github_record.get("currency"),
            "status": github_record.get("status"),
            "source": github_record.get("source"),
            "observer_location": github_record.get("observer_location"),
            "scraped_at": github_record.get("scraped_at"),
        },
        "frontend": {
            "current_price": frontend_price,
            "msrp_price": frontend_msrp,
            "currency": frontend_record.get("currency"),
            "status": frontend_record.get("status"),
            "source": frontend_record.get("source"),
            "observer_location": frontend_record.get("observer_location"),
            "scraped_at": frontend_record.get("scraped_at"),
        },
        "price_delta_frontend_minus_github": price_delta,
        "msrp_delta_frontend_minus_github": msrp_delta,
        "result": "pass" if not issues else "fail",
        "issues": issues,
    }


async def run(args: argparse.Namespace) -> int:
    latest = load_json_source(args.latest_source)
    github_records = select_records(latest.get("products", []), args)
    products_by_asin = load_product_list(args.product_list)
    if not github_records:
        raise SystemExit("No records selected for verification.")

    from playwright.async_api import async_playwright

    comparisons: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        for index, github_record in enumerate(github_records, start=1):
            asin = product_key(github_record)
            product = products_by_asin.get(asin) or {
                "id": asin,
                "asin": asin,
                "url": github_record.get("product_url"),
                "brand": github_record.get("brand"),
                "category": github_record.get("category"),
                "model": github_record.get("model"),
                "name": github_record.get("product_name"),
                "enabled": True,
            }
            print(f"[{index}/{len(github_records)}] verify {asin} {product.get('brand')} {product.get('model')}")
            frontend_record = await scrape_product(page, product)
            comparisons.append(compare_record(github_record, frontend_record, args))
            await asyncio.sleep(random.uniform(args.min_delay, args.max_delay))
        await page.close()
        await browser.close()

    failed = [item for item in comparisons if item["result"] != "pass"]
    report = {
        "generated_at": utc_now_iso(),
        "latest_source": args.latest_source,
        "frontend_cdp_endpoint": args.cdp_endpoint,
        "postcode": args.postcode,
        "price_tolerance": args.price_tolerance,
        "msrp_tolerance": args.msrp_tolerance,
        "summary": {
            "checked": len(comparisons),
            "passed": len(comparisons) - len(failed),
            "failed": len(failed),
        },
        "comparisons": comparisons,
    }
    save_json(Path(args.output), report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")
    return 1 if failed and args.fail_on_mismatch else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare GitHub Amazon.fr prices against a local frontend browser session.")
    parser.add_argument("--latest-source", default=DEFAULT_LATEST_URL, help="Local JSON path or raw GitHub URL.")
    parser.add_argument("--product-list", default="product_list.json")
    parser.add_argument("--cdp-endpoint", required=True, help="Existing Chromium DevTools endpoint, e.g. http://127.0.0.1:51679")
    parser.add_argument("--asin", help="Comma-separated ASIN list to verify.")
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--postcode", default=DEFAULT_POSTCODE)
    parser.add_argument("--price-tolerance", type=float, default=0.2)
    parser.add_argument("--msrp-tolerance", type=float, default=0.2)
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=2.0)
    parser.add_argument("--output", default="price_verification_report.json")
    parser.add_argument("--fail-on-mismatch", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
