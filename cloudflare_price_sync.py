from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from multi_market_price_refresh import load_marketplace


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = os.environ.get("PRICE_MONITOR_URL", "https://price.tentoki.online").rstrip("/")
    token = required_env("PRICE_MONITOR_INGEST_TOKEN")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "TentokiPriceMonitorGitHubActions/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Cloudflare API HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cloudflare API request failed: {type(exc).__name__}") from exc


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def download_seed(market: str, output: Path, account: str) -> None:
    payload = api_request("GET", f"/api/ingest/seed?market={market}&account={account}")
    if not isinstance(payload.get("products"), list):
        raise RuntimeError("Cloudflare seed response is missing products")
    write_json_atomic(output, payload)
    print(f"Downloaded {len(payload['products'])} {market} seed records to {output}")


def market_catalog(catalog: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    result = dict(catalog)
    for key in ("products", "non_active_products"):
        rows = []
        for source in catalog.get(key, []):
            item = dict(source)
            asin = str(item.get("asin") or "").strip().upper()
            if asin:
                item["url"] = f"{market['base_url']}/dp/{asin}"
            rows.append(item)
        result[key] = rows
    result["market"] = market["code"]
    result["site"] = market["site"]
    return result


def upload(market_code: str, latest_path: Path, catalog_path: Path, account: str) -> None:
    market = load_marketplace(market_code)
    with latest_path.open("r", encoding="utf-8") as handle:
        latest = json.load(handle)
    with catalog_path.open("r", encoding="utf-8") as handle:
        catalog = market_catalog(json.load(handle), market)
    if latest.get("market") != market_code:
        raise RuntimeError(f"Latest result market mismatch: expected {market_code}")
    response = api_request(
        "POST",
        "/api/ingest",
        {"account": account, "market": market_code, "latest": latest, "catalog": catalog},
    )
    if not response.get("ok"):
        raise RuntimeError(f"Cloudflare ingest rejected payload: {response}")
    print(
        f"Uploaded {market_code}: latest={response.get('latest_count')} "
        f"ok={response.get('success_count')} stale={response.get('stale_count')}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize marketplace price data with Cloudflare")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed = subparsers.add_parser("download-seed")
    seed.add_argument("--market", required=True, choices=("UK", "DE", "IT", "ES", "NL"))
    seed.add_argument("--output", required=True, type=Path)
    seed.add_argument("--account", default="primary")
    push = subparsers.add_parser("upload")
    push.add_argument("--market", required=True, choices=("UK", "DE", "IT", "ES", "NL"))
    push.add_argument("--latest", required=True, type=Path)
    push.add_argument("--catalog", default=Path("product_list.json"), type=Path)
    push.add_argument("--account", default="primary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "download-seed":
            download_seed(args.market, args.output, args.account)
        else:
            upload(args.market, args.latest, args.catalog, args.account)
        return 0
    except RuntimeError as exc:
        print(str(exc), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
