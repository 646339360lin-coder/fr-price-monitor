from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ALLOWED_HOSTS = {"www.kdocs.cn", "kdocs.cn"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def call_airscript(webhook: str, token: str) -> dict[str, Any]:
    parsed = urlparse(webhook)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise RuntimeError("WPS_SCRIPT_WEBHOOK must be an HTTPS kdocs.cn URL")

    body = json.dumps(
        {"Context": {"argv": {"requested_at": utc_now_iso()}, "sheet_name": "产品清单"}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "AirScript-Token": token,
            "User-Agent": "TentokiWpsProductSync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"WPS request failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"WPS request failed: {type(exc).__name__}") from exc

    if payload.get("status") != "finished" or payload.get("error"):
        raise RuntimeError(f"WPS script did not finish successfully: {payload.get('error') or payload.get('status')}")

    result = payload.get("data", {}).get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            raise RuntimeError("WPS script returned a non-JSON result") from exc
    if not isinstance(result, dict):
        raise RuntimeError("WPS script returned an invalid result object")
    return result


def validate_result(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products = result.get("products")
    non_active = result.get("non_active_products")
    if not isinstance(products, list) or not isinstance(non_active, list):
        raise RuntimeError("WPS result must contain products and non_active_products arrays")
    if not products:
        raise RuntimeError("WPS result contains no active products; refusing to replace product_list.json")

    invalid_active = [item for item in products if not isinstance(item, dict) or not item.get("asin") or not item.get("url")]
    if invalid_active:
        raise RuntimeError(f"WPS result contains {len(invalid_active)} invalid active products")
    return products, non_active


def build_payload(
    result: dict[str, Any],
    products: list[dict[str, Any]],
    non_active: list[dict[str, Any]],
    market: str,
    site: str,
    source: str,
) -> dict[str, Any]:
    return {
        "account_key": result.get("account_key", "primary"),
        "market": market,
        "site": site,
        "source": source,
        "synced_at": utc_now_iso(),
        "schema_version": result.get("schema_version", 1),
        "filter": {"product_status": ["新品", "正常在售"]},
        "stats": result.get("stats", {}),
        "products": products,
        "non_active_products": non_active,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def parse_args() -> Any:
    import argparse

    parser = argparse.ArgumentParser(description="Synchronize a WPS AirScript product catalog")
    parser.add_argument("--output", type=Path, default=Path("product_list.json"))
    parser.add_argument("--market", default="FR")
    parser.add_argument("--site", default="Amazon.fr")
    parser.add_argument(
        "--source",
        default="WPS AirScript: TVL备货表格-20240914 / 产品清单",
    )
    parser.add_argument(
        "--additional-active-status",
        action="append",
        default=[],
        help="Move matching WPS non-active rows into the active catalog",
    )
    parser.add_argument(
        "--include-all-valid-asins",
        action="store_true",
        help="Include every WPS row with a valid ASIN and product URL",
    )
    parser.add_argument(
        "--isku-prefix",
        default="",
        help="Only keep rows whose iSKU begins with this account prefix",
    )
    return parser.parse_args()


def include_additional_active_statuses(
    products: list[dict[str, Any]],
    non_active: list[dict[str, Any]],
    statuses: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = {status.strip() for status in statuses if status.strip()}
    if not allowed:
        return products, non_active
    seen = {str(item.get("asin") or "").upper() for item in products}
    remaining = []
    for item in non_active:
        asin = str(item.get("asin") or "").strip().upper()
        if item.get("product_status") in allowed and asin and item.get("url") and asin not in seen:
            item = dict(item)
            item["enabled"] = True
            item["id"] = asin
            products.append(item)
            seen.add(asin)
        else:
            remaining.append(item)
    return products, remaining


def include_all_valid_asins(
    products: list[dict[str, Any]],
    non_active: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen = {str(item.get("asin") or "").upper() for item in products}
    remaining = []
    for item in non_active:
        asin = str(item.get("asin") or "").strip().upper()
        if asin and item.get("url") and asin not in seen:
            item = dict(item)
            item["enabled"] = True
            item["id"] = asin
            products.append(item)
            seen.add(asin)
        else:
            remaining.append(item)
    return products, remaining


def filter_by_isku_prefix(
    products: list[dict[str, Any]],
    non_active: list[dict[str, Any]],
    prefix: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = prefix.strip().upper()
    if not normalized:
        return products, non_active

    def belongs_to_account(item: dict[str, Any]) -> bool:
        return str(item.get("isku") or "").strip().upper().startswith(normalized)

    filtered_products = [item for item in products if belongs_to_account(item)]
    filtered_non_active = [item for item in non_active if belongs_to_account(item)]
    if not filtered_products:
        raise RuntimeError(f"WPS result contains no products with iSKU prefix {normalized}")
    return filtered_products, filtered_non_active


def main() -> int:
    args = parse_args()
    try:
        result = call_airscript(required_env("WPS_SCRIPT_WEBHOOK"), required_env("WPS_AIRSCRIPT_TOKEN"))
        products, non_active = validate_result(result)
        products, non_active = include_additional_active_statuses(
            products,
            non_active,
            args.additional_active_status,
        )
        if args.include_all_valid_asins:
            products, non_active = include_all_valid_asins(products, non_active)
        products, non_active = filter_by_isku_prefix(
            products,
            non_active,
            args.isku_prefix,
        )
        payload = build_payload(
            result,
            products,
            non_active,
            args.market.upper(),
            args.site,
            args.source,
        )
        payload["filter"]["product_status"].extend(args.additional_active_status)
        if args.include_all_valid_asins:
            payload["filter"] = {"product_status": "all", "valid_asin_required": True}
        if args.isku_prefix:
            payload["filter"]["isku_prefix"] = args.isku_prefix.strip().upper()
        payload["stats"] = dict(payload.get("stats") or {})
        payload["stats"]["exported_products"] = len(products)
        payload["stats"]["exported_non_active_products"] = len(non_active)
        write_json_atomic(args.output, payload)
        print(f"WPS sync complete: active={len(products)}, non_active={len(non_active)}, output={args.output}")
        return 0
    except RuntimeError as exc:
        print(f"WPS sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
