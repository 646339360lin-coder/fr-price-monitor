from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from daily_price_refresh import (
    USER_AGENT,
    build_error_record as build_fr_error_record,
    dismiss_cookie_banner,
    extract_dom_prices,
    extract_embedded_prices,
    extract_engagement_metrics,
    extract_main_image,
    extract_promotion_status,
    extract_structured_product,
    extract_asin,
    first_number,
    first_source_for_price,
    load_product_list,
    product_key_for_product,
    product_key_for_result,
    retryable_status,
    robots_allowed,
    safe_text,
    should_replace_with_retry,
    utc_now_iso,
    wait_for_engagement_metrics,
)
from price_history_manager import merge_price_results

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


MARKETPLACE_FILE = Path("marketplaces.json")


def load_marketplace(code: str, path: Path = MARKETPLACE_FILE) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    market = payload.get(code.upper())
    if not isinstance(market, dict):
        raise ValueError(f"Unknown marketplace: {code}")
    required = {
        "site",
        "host",
        "base_url",
        "locale",
        "language_query",
        "accept_language",
        "timezone",
        "currency",
        "postcode",
        "country_code",
        "city",
    }
    missing = sorted(required - market.keys())
    if missing:
        raise ValueError(f"Marketplace {code} is missing: {', '.join(missing)}")
    return {"code": code.upper(), **market}


def normalize_product_url(product: dict[str, Any], market: dict[str, Any]) -> str:
    asin = str(product.get("asin") or extract_asin(str(product.get("url") or "")) or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        raise ValueError(f"Missing or invalid ASIN: {product.get('asin') or product.get('url')}")
    return f"{market['base_url']}/dp/{asin}"


def with_market_language(url: str, market: dict[str, Any]) -> str:
    parsed = urlparse(url)
    language = f"language={market['language_query']}"
    query = f"{parsed.query}&{language}" if parsed.query else language
    return urlunparse(parsed._replace(query=query))


def normalized_postcode(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def location_matches_postcode(
    location: str | None, postcode: str, market: dict[str, Any] | None = None
) -> bool:
    expected = normalized_postcode(postcode)
    actual = normalized_postcode(location)
    if expected and expected in actual:
        return True
    return bool(market and market.get("country_code") == "GB" and expected[:5] in actual)


def currency_from_text(value: Any) -> str | None:
    text = str(value or "")
    if "£" in text or re.search(r"\bGBP\b", text, re.I):
        return "GBP"
    if "€" in text or re.search(r"\bEUR\b", text, re.I):
        return "EUR"
    if "$" in text or re.search(r"\bUSD\b", text, re.I):
        return "USD"
    return None


async def add_market_cookies(context: "BrowserContext", market: dict[str, Any]) -> None:
    cookies = [
        {"name": "i18n-prefs", "value": market["currency"], "url": market["base_url"]},
    ]
    if market.get("locale_cookie_name") and market.get("locale_cookie"):
        cookies.append(
            {
                "name": market["locale_cookie_name"],
                "value": market["locale_cookie"],
                "url": market["base_url"],
            }
        )
    await context.add_cookies(cookies)


async def dismiss_delivery_overlay(page: "Page") -> None:
    for selector in (
        "input[data-action-type='DISMISS']",
        ".glow-toaster-button-dismiss input",
    ):
        try:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.click(timeout=2500)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def continue_shopping_if_prompted(page: "Page") -> bool:
    prompts = (
        "Continue shopping",
        "Weiter einkaufen",
        "Weiter shoppen",
        "Continua gli acquisti",
        "Continuar comprando",
        "Doorgaan met winkelen",
    )
    body_text = (await safe_text(page, "body") or "").lower()
    if len(body_text) > 2_000 or await page.locator("#productTitle").count():
        return False
    if not any(prompt.lower() in body_text for prompt in prompts):
        return False
    for prompt in prompts:
        for role in ("button", "link"):
            try:
                locator = page.get_by_role(role, name=prompt, exact=False).first
                if await locator.count():
                    await locator.click(timeout=4000)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
    return False


async def navigate_product_page(page: "Page", url: str) -> None:
    for _ in range(3):
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(1200)
        if not await continue_shopping_if_prompted(page):
            return
    raise RuntimeError("continue shopping interstitial persisted")


async def open_location_modal(page: "Page") -> bool:
    await dismiss_delivery_overlay(page)
    for selector in (
        "#nav-global-location-popover-link",
        "#nav-global-location-data-modal-action",
    ):
        try:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


async def set_delivery_postcode(
    page: "Page",
    postcode: str,
    market: dict[str, Any],
    start_url: str | None = None,
) -> str:
    target_url = with_market_language(start_url or f"{market['base_url']}/", market)
    await page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_timeout(1800)
    await continue_shopping_if_prompted(page)
    await dismiss_cookie_banner(page)
    await dismiss_delivery_overlay(page)
    current = await safe_text(page, "#glow-ingress-line2, #nav-global-location-popover-link")
    if location_matches_postcode(current, postcode, market):
        return current or ""

    if await set_delivery_postcode_via_ajax(page, postcode, market):
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(1200)
        await continue_shopping_if_prompted(page)
        current = await safe_text(page, "#glow-ingress-line2, #nav-global-location-popover-link")
        if location_matches_postcode(current, postcode, market):
            return current or ""

    try:
        opened = await open_location_modal(page)
        if not opened:
            fallback_url = with_market_language(f"{market['base_url']}/", market)
            await page.goto(fallback_url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(1800)
            await continue_shopping_if_prompted(page)
            await dismiss_cookie_banner(page)
            opened = await open_location_modal(page)
        if not opened:
            page_title = (await page.title()).strip()
            body_text = (await safe_text(page, "body") or "").replace("\n", " ")[:180]
            raise RuntimeError(
                f"location modal trigger not found; title={page_title!r}; body={body_text!r}"
            )
        await page.wait_for_timeout(900)
        postcode_input = page.locator("#GLUXZipUpdateInput, #GLUXZipUpdateInput_0").first
        await postcode_input.fill(postcode, timeout=8000)
        submitted = False
        for selector in (
            "#GLUXZipUpdate",
            "#GLUXZipUpdate .a-button-input",
            "input[aria-labelledby='GLUXZipUpdate-announce']",
        ):
            try:
                locator = page.locator(selector).first
                if await locator.count():
                    await locator.click(timeout=4000)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            await postcode_input.press("Enter")
        await page.wait_for_timeout(2200)
        for selector in (
            "#GLUXConfirmClose",
            ".a-popover-footer #GLUXConfirmClose",
            "button[name='glowDoneButton']",
        ):
            try:
                if await page.locator(selector).count():
                    await page.locator(selector).first.click(timeout=2500)
                    break
            except Exception:
                continue
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(1000)
        await continue_shopping_if_prompted(page)
    except Exception as exc:
        print(f"Unable to set {market['site']} postcode {postcode}: {exc}", file=sys.stderr)
    return await safe_text(page, "#glow-ingress-line2, #nav-global-location-popover-link") or ""


async def set_delivery_postcode_via_ajax(
    page: "Page", postcode: str, market: dict[str, Any]
) -> bool:
    try:
        result = await page.evaluate(
            """async (location) => {
              const params = new URLSearchParams({
                locationType: "LOCATION_INPUT",
                zipCode: location.postcode,
                countryCode: location.countryCode,
                city: location.city,
                storeContext: "generic",
                deviceType: "web",
                pageType: "Gateway",
                actionSource: "glow"
              });
              const controller = new AbortController();
              const timeout = setTimeout(() => controller.abort(), 8000);
              try {
                const response = await fetch("/gp/delivery/ajax/address-change.html", {
                  method: "POST",
                  credentials: "include",
                  signal: controller.signal,
                  headers: {
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "x-requested-with": "XMLHttpRequest"
                  },
                  body: params.toString()
                });
                if (!response.ok) return { ok: false, status: response.status };
                const payload = await response.json().catch(() => ({}));
                return {
                  ok: Boolean(payload.successful || payload.isAddressUpdated),
                  status: response.status,
                  payload
                };
              } catch (error) {
                return { ok: false, error: error?.name || "request_failed" };
              } finally {
                clearTimeout(timeout);
              }
            }""",
            {
                "postcode": postcode,
                "countryCode": market["country_code"],
                "city": market["city"],
            },
        )
        address = ((result or {}).get("payload") or {}).get("address") or {}
        print(
            f"{market['site']} ajax location: ok={(result or {}).get('ok')} "
            f"country={address.get('countryCode')} zip={address.get('zipCode')}"
        )
        response_country = str(address.get("countryCode") or "").upper()
        response_postcode = normalized_postcode(address.get("zipCode"))
        expected_postcode = normalized_postcode(postcode)
        return bool(
            result
            and result.get("ok")
            and response_country == market["country_code"]
            and response_postcode == expected_postcode
        )
    except Exception as exc:
        print(f"Unable to set {market['site']} postcode via ajax: {exc}", file=sys.stderr)
        return False


def build_error_record(
    product: dict[str, Any], url: str, status: str, market: dict[str, Any], postcode: str
) -> dict[str, Any]:
    record = build_fr_error_record(product, url, status)
    record.update(
        {
            "currency": market["currency"],
            "source": market["host"].removeprefix("www."),
            "observer_postcode": postcode,
            "market": market["code"],
        }
    )
    return record


def availability_is_unavailable(availability: str | None, market: dict[str, Any]) -> bool:
    text = str(availability or "").lower()
    return bool(text and any(word.lower() in text for word in market.get("unavailable_words", [])))


async def scrape_product(
    page: "Page",
    product: dict[str, Any],
    market: dict[str, Any],
    postcode: str,
    context_location_confirmed: bool = False,
) -> dict[str, Any]:
    url = normalize_product_url(product, market)
    if not robots_allowed(url):
        return build_error_record(product, url, "blocked_by_robots_txt", market, postcode)

    location_confirmed_via_api = False
    try:
        target_url = with_market_language(url, market)
        await navigate_product_page(page, target_url)
        observer_location = await safe_text(page, "#glow-ingress-line2, #nav-global-location-popover-link")
        if (
            not context_location_confirmed
            and not location_matches_postcode(observer_location, postcode, market)
        ):
            location_set = await set_delivery_postcode_via_ajax(page, postcode, market)
            location_confirmed_via_api = location_set
            if not location_set:
                modal_location = await set_delivery_postcode(page, postcode, market, url)
                location_set = location_matches_postcode(modal_location, postcode, market)
            if location_set:
                await navigate_product_page(page, target_url)
    except Exception as exc:
        status = "timeout" if exc.__class__.__name__ == "TimeoutError" else f"navigation_error: {exc}"
        return build_error_record(product, url, status, market, postcode)

    page_title = await page.title()
    if any(word in page_title.lower() for word in market.get("not_found_words", [])):
        record = build_error_record(product, url, "page_not_found", market, postcode)
        record["page_title"] = page_title
        record["observer_location"] = await safe_text(
            page, "#glow-ingress-line2, #nav-global-location-popover-link"
        )
        return record

    price_wait_ms = int(market.get("price_wait_ms") or 0)
    if price_wait_ms:
        try:
            await page.locator(
                "#corePrice_feature_div .a-price .a-offscreen, "
                "#apex_desktop .a-price .a-offscreen, "
                ".priceToPay .a-offscreen, #availability, #outOfStock"
            ).first.wait_for(state="attached", timeout=price_wait_ms)
        except Exception:
            pass

    html = await page.content()
    title = await safe_text(page, "#productTitle")
    structured = await extract_structured_product(page)
    embedded = extract_embedded_prices(html)
    dom_prices = await extract_dom_prices(page)
    page_text = ((title or "") + " " + html[:50_000]).lower()
    clearance = any(word in page_text for word in market.get("clearance_words", []))

    current_price = first_number(
        structured.get("price"), dom_prices.get("current_price"), embedded.get("current_price")
    )
    current_source = first_source_for_price(
        current_price,
        (structured.get("price"), structured.get("price_source")),
        (dom_prices.get("current_price"), dom_prices.get("price_source")),
        (embedded.get("current_price"), embedded.get("price_source")),
    )
    msrp_price = first_number(
        structured.get("msrp_price"),
        None if clearance else dom_prices.get("msrp_price"),
        embedded.get("msrp_price"),
    )
    msrp_source = first_source_for_price(
        msrp_price,
        (structured.get("msrp_price"), structured.get("msrp_source")),
        (None if clearance else dom_prices.get("msrp_price"), dom_prices.get("msrp_source")),
        (embedded.get("msrp_price"), embedded.get("msrp_source")),
    )

    if current_source == "json_ld":
        detected_currency = structured.get("currency")
    elif current_source == "dom_fallback":
        detected_currency = currency_from_text(dom_prices.get("current_raw"))
    else:
        detected_currency = None
    currency_mismatch = bool(
        detected_currency and str(detected_currency).upper() != market["currency"]
    )

    availability = await safe_text(page, "#availability, #outOfStock")
    unavailable = current_price is None and availability_is_unavailable(availability, market)
    if unavailable:
        await wait_for_engagement_metrics(page, int(market.get("engagement_wait_ms") or 0))
        structured = await extract_structured_product(page)
    engagement = await extract_engagement_metrics(page, structured)
    promotion = await extract_promotion_status(page)
    image_url = await extract_main_image(page)
    observer_location = await safe_text(page, "#glow-ingress-line2, #nav-global-location-popover-link")
    location_valid = (
        context_location_confirmed
        or location_confirmed_via_api
        or location_matches_postcode(observer_location, postcode, market)
    )
    if currency_mismatch or not location_valid:
        current_price = None
        msrp_price = None
        current_source = None
        msrp_source = None

    if currency_mismatch:
        status = f"currency_mismatch:{detected_currency}"
    elif not location_valid:
        status = "location_not_postcode"
    elif unavailable:
        status = "unavailable"
    elif current_price is None:
        status = "price_missing"
    else:
        status = "ok"

    return {
        "product_id": product.get("id") or extract_asin(url) or url,
        "asin": extract_asin(url),
        "product_name": structured.get("name") or title or product.get("name"),
        "brand": structured.get("brand") or product.get("brand"),
        "category": product.get("category"),
        "type": product.get("type") or product.get("category"),
        "style": product.get("style"),
        "model": product.get("model"),
        "spec": product.get("spec"),
        "phone_brand": product.get("phone_brand"),
        "sku": product.get("sku"),
        "isku": product.get("isku"),
        "fnsku": product.get("fnsku"),
        "source_row": product.get("source_row"),
        "product_status": product.get("product_status"),
        "current_price": current_price,
        "msrp_price": msrp_price,
        "currency": market["currency"],
        "detected_currency": detected_currency,
        "promotion_status": promotion,
        "rating": engagement.get("rating"),
        "review_count": engagement.get("review_count"),
        "monthly_sales_label": engagement.get("monthly_sales_label"),
        "rating_source": engagement.get("rating_source"),
        "review_count_source": engagement.get("review_count_source"),
        "monthly_sales_source": engagement.get("monthly_sales_source"),
        "availability": availability,
        "image_url": image_url,
        "product_url": url,
        "scraped_at": utc_now_iso(),
        "source": market["host"].removeprefix("www."),
        "market": market["code"],
        "observer_postcode": postcode,
        "observer_location": observer_location,
        "price_source": current_source,
        "msrp_source": msrp_source,
        "clearance_detected": clearance,
        "status": status,
    }


async def run(args: argparse.Namespace) -> int:
    market = load_marketplace(args.market, Path(args.marketplace_file))
    postcode = args.postcode or market["postcode"]
    products = load_product_list(Path(args.product_list))
    if args.asin:
        requested_asin = args.asin.strip().upper()
        products = [
            product
            for product in products
            if str(product.get("asin") or extract_asin(str(product.get("url") or "")) or "").upper()
            == requested_asin
        ]
    if args.offset:
        products = products[args.offset :]
    if args.limit:
        products = products[: args.limit]
    if not products:
        print(f"No enabled products found for {market['site']}")
        return 1

    latest_path = Path(args.latest_output or f".runtime/{market['code'].lower()}/price_results_latest.json")
    history_path = Path(args.history_output or f".runtime/{market['code'].lower()}/price_history.json")
    results: list[dict[str, Any]] = []
    location_failure_streak = 0
    aborted_for_location = False

    if args.dry_run:
        for index, product in enumerate(products, start=1):
            url = normalize_product_url(product, market)
            print(f"[{index}/{len(products)}] dry-run {market['code']} {url}")
            results.append(build_error_record(product, url, "dry_run", market, postcode))
    else:
        from playwright.async_api import async_playwright

        context_options = {
            "user_agent": USER_AGENT,
            "locale": market["locale"],
            "timezone_id": market["timezone"],
            "viewport": {"width": 1365, "height": 900},
            "extra_http_headers": {"Accept-Language": market["accept_language"]},
        }
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headful)
            context = await browser.new_context(**context_options)
            await add_market_cookies(context, market)
            page = await context.new_page()
            context_location_confirmed = args.skip_location
            if not args.skip_location:
                location = await set_delivery_postcode(page, postcode, market)
                context_location_confirmed = location_matches_postcode(
                    location, postcode, market
                )
                print(f"{market['site']} delivery location: {location or 'not captured'}")
            for index, product in enumerate(products, start=1):
                cooldown_every = int(market.get("cooldown_every") or 0)
                if cooldown_every and index > 1 and (index - 1) % cooldown_every == 0:
                    cooldown_seconds = float(market.get("cooldown_seconds") or 90)
                    print(
                        f"{market['code']} cooling down for {cooldown_seconds:g}s "
                        f"after {index - 1} products"
                    )
                    await asyncio.sleep(cooldown_seconds)
                url = normalize_product_url(product, market)
                print(f"[{index}/{len(products)}] {market['code']} {product.get('brand')} {url}")
                try:
                    record = await scrape_product(
                        page,
                        product,
                        market,
                        postcode,
                        context_location_confirmed=context_location_confirmed,
                    )
                except Exception as exc:
                    record = build_error_record(
                        product, url, f"unexpected_error: {exc}", market, postcode
                    )
                    print(f"  unexpected error: {exc}", file=sys.stderr)
                results.append(record)
                if record.get("status") == "location_not_postcode":
                    location_failure_streak += 1
                else:
                    location_failure_streak = 0
                if location_failure_streak >= 10:
                    aborted_for_location = True
                    print(
                        f"{market['code']} aborting after {location_failure_streak} consecutive "
                        "postcode verification failures",
                        file=sys.stderr,
                    )
                    for skipped_product in products[index:]:
                        skipped_url = normalize_product_url(skipped_product, market)
                        results.append(
                            build_error_record(
                                skipped_product,
                                skipped_url,
                                "aborted_after_location_failures",
                                market,
                                postcode,
                            )
                        )
                    break
                if index < len(products):
                    await asyncio.sleep(random.uniform(args.min_delay, args.max_delay))
            await context.close()
            await browser.close()

            if args.retry_failures and not aborted_for_location:
                results_by_key = {product_key_for_result(record): record for record in results}
                products_by_key = {product_key_for_product(product): product for product in products}
                for retry_round in range(1, args.retry_failures + 1):
                    retry_products = [
                        products_by_key[key]
                        for key, record in results_by_key.items()
                        if retryable_status(record.get("status")) and key in products_by_key
                    ]
                    if not retry_products:
                        break
                    print(f"{market['code']} retry round {retry_round}: {len(retry_products)} products")
                    retry_browser = await playwright.chromium.launch(headless=not args.headful)
                    retry_context = await retry_browser.new_context(**context_options)
                    await add_market_cookies(retry_context, market)
                    retry_page = await retry_context.new_page()
                    retry_location_confirmed = args.skip_location
                    if not args.skip_location:
                        location = await set_delivery_postcode(
                            retry_page,
                            postcode,
                            market,
                        )
                        retry_location_confirmed = location_matches_postcode(
                            location, postcode, market
                        )
                        print(f"{market['site']} retry location: {location or 'not captured'}")
                    for index, product in enumerate(retry_products, start=1):
                        cooldown_every = int(market.get("cooldown_every") or 0)
                        if cooldown_every and index > 1 and (index - 1) % cooldown_every == 0:
                            await asyncio.sleep(float(market.get("cooldown_seconds") or 90))
                        url = normalize_product_url(product, market)
                        try:
                            retry_record = await scrape_product(
                                retry_page,
                                product,
                                market,
                                postcode,
                                context_location_confirmed=retry_location_confirmed,
                            )
                        except Exception as exc:
                            retry_record = build_error_record(
                                product, url, f"unexpected_error: {exc}", market, postcode
                            )
                        key = product_key_for_result(retry_record)
                        previous = results_by_key.get(key)
                        if previous and should_replace_with_retry(previous, retry_record):
                            results_by_key[key] = retry_record
                        if index < len(retry_products):
                            await asyncio.sleep(random.uniform(args.min_delay, args.max_delay))
                    await retry_context.close()
                    await retry_browser.close()
                results = [results_by_key[product_key_for_product(product)] for product in products]

    latest = merge_price_results(
        results,
        latest_path=latest_path,
        history_path=history_path,
        market=market["code"],
        site=market["site"],
        currency=market["currency"],
    )
    ok_count = sum(1 for item in latest["products"] if item.get("status") == "ok")
    print(
        f"{market['code']} wrote {len(latest['products'])} records to {latest_path}; "
        f"ok={ok_count}"
    )
    if aborted_for_location and not args.allow_empty:
        return 2
    return 0 if ok_count or args.allow_empty or args.dry_run else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Amazon European marketplace price refresh")
    parser.add_argument("--market", required=True, choices=("UK", "DE", "IT", "ES", "NL"))
    parser.add_argument("--marketplace-file", default=str(MARKETPLACE_FILE))
    parser.add_argument("--product-list", default="product_list.json")
    parser.add_argument("--latest-output")
    parser.add_argument("--history-output")
    parser.add_argument("--postcode")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--asin", help="Scrape one specific ASIN for validation")
    parser.add_argument("--skip-location", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--retry-failures", type=int, default=2)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
