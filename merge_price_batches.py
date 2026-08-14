from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def merge_batches(input_dir: Path, output: Path, market: str) -> None:
    files = sorted(input_dir.glob("**/price_results_latest.json"))
    if not files:
        raise RuntimeError(f"No batch result files found under {input_dir}")

    products_by_asin: dict[str, dict[str, Any]] = {}
    site = None
    currency = None
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("market") != market:
            raise RuntimeError(f"Market mismatch in {path}: {payload.get('market')}")
        site = site or payload.get("site")
        currency = currency or payload.get("currency")
        for product in payload.get("products", []):
            asin = str(product.get("asin") or "").strip().upper()
            if asin:
                products_by_asin[asin] = product

    result = {
        "generated_at": utc_now_iso(),
        "market": market,
        "site": site,
        "currency": currency,
        "products": [products_by_asin[asin] for asin in sorted(products_by_asin)],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Merged {len(files)} batches and {len(products_by_asin)} products into {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge marketplace batch scrape results")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--market", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    merge_batches(args.input_dir, args.output, args.market.upper())
