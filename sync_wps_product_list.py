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


OUTPUT_PATH = Path("product_list.json")
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


def build_payload(result: dict[str, Any], products: list[dict[str, Any]], non_active: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "market": "FR",
        "site": "Amazon.fr",
        "source": "WPS AirScript: TVL备货表格-20240914 / 产品清单",
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


def main() -> int:
    try:
        result = call_airscript(required_env("WPS_SCRIPT_WEBHOOK"), required_env("WPS_AIRSCRIPT_TOKEN"))
        products, non_active = validate_result(result)
        write_json_atomic(OUTPUT_PATH, build_payload(result, products, non_active))
        print(f"WPS sync complete: active={len(products)}, non_active={len(non_active)}, output={OUTPUT_PATH}")
        return 0
    except RuntimeError as exc:
        print(f"WPS sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
