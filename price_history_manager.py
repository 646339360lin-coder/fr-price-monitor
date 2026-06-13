from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LATEST_FILE = Path("price_results_latest.json")
HISTORY_FILE = Path("price_history.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        backup = path.with_suffix(path.suffix + f".broken-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        path.rename(backup)
        return deepcopy(default)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def product_key(record: dict[str, Any]) -> str:
    explicit = record.get("product_id") or record.get("asin")
    if explicit:
        return str(explicit).strip()
    return str(record.get("product_url") or record.get("url") or record.get("product_name") or "").strip()


def price_as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("\u00a0", " ").replace("EUR", "").replace("€", "").strip()
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def calculate_discount(current_price: Any, msrp_price: Any) -> float | None:
    current = price_as_float(current_price)
    msrp = price_as_float(msrp_price)
    if current is None or msrp is None or msrp <= 0 or current >= msrp:
        return None
    return round((msrp - current) / msrp * 100, 2)


def latest_history_by_product(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for entry in history.get("products", []):
        key = product_key(entry)
        if not key:
            continue
        latest[key] = entry
    return latest


def latest_valid_history_by_product(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for entry in history.get("products", []):
        key = product_key(entry)
        if not key or price_as_float(entry.get("current_price")) is None:
            continue
        latest[key] = entry
    return latest


def inherit_clearance_msrp(record: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not record.get("clearance_detected"):
        return record
    if record.get("msrp_price") is not None:
        return record
    if previous and previous.get("msrp_price") is not None:
        record["msrp_price"] = previous["msrp_price"]
        record["msrp_source"] = "history_inherited_for_clearance"
    return record


def merge_price_results(
    new_records: list[dict[str, Any]],
    latest_path: Path = LATEST_FILE,
    history_path: Path = HISTORY_FILE,
) -> dict[str, Any]:
    history = load_json(history_path, {"generated_at": None, "products": []})
    previous_by_key = latest_history_by_product(history)
    previous_valid_by_key = latest_valid_history_by_product(history)

    normalized_records: list[dict[str, Any]] = []
    scrape_time = utc_now_iso()
    for raw in new_records:
        record = deepcopy(raw)
        record.setdefault("scraped_at", scrape_time)
        record = carry_forward_valid_price(record, previous_valid_by_key.get(product_key(record)))
        record = inherit_clearance_msrp(record, previous_by_key.get(product_key(record)))
        record["discount_percent"] = calculate_discount(record.get("current_price"), record.get("msrp_price"))
        normalized_records.append(record)

    latest_payload = {
        "generated_at": scrape_time,
        "market": "FR",
        "site": "Amazon.fr",
        "currency": "EUR",
        "products": normalized_records,
    }

    history_products = history.get("products", [])
    history_products.extend(deepcopy(normalized_records))
    history_products = prune_history(history_products, days=180)

    history_payload = {
        "generated_at": scrape_time,
        "market": "FR",
        "site": "Amazon.fr",
        "currency": "EUR",
        "products": history_products,
    }

    save_json(latest_path, latest_payload)
    save_json(history_path, history_payload)
    return latest_payload


def carry_forward_valid_price(record: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if price_as_float(record.get("current_price")) is not None or not previous:
        return record
    original_status = record.get("status") or "price_missing"
    record["current_price"] = previous.get("current_price")
    if record.get("msrp_price") is None:
        record["msrp_price"] = previous.get("msrp_price")
    if not record.get("promotion_status"):
        record["promotion_status"] = previous.get("promotion_status")
    if not record.get("availability"):
        record["availability"] = previous.get("availability")
    record["price_source"] = "history_carried_forward"
    if record.get("msrp_price") is not None and not record.get("msrp_source"):
        record["msrp_source"] = "history_carried_forward"
    record["price_carried_forward"] = True
    record["last_success_scraped_at"] = previous.get("scraped_at")
    record["last_attempt_status"] = original_status
    record["status"] = "stale_price"
    return record


def prune_history(records: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[dict[str, Any]] = []
    for record in records:
        scraped_at = parse_iso_datetime(record.get("scraped_at"))
        if scraped_at is None or scraped_at >= cutoff:
            kept.append(record)
    return kept


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def weekly_change_summary(history_path: Path = HISTORY_FILE) -> dict[str, Any]:
    history = load_json(history_path, {"products": []})
    since = datetime.now(timezone.utc) - timedelta(days=7)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in history.get("products", []):
        key = product_key(record)
        scraped_at = parse_iso_datetime(record.get("scraped_at"))
        if not key or scraped_at is None or scraped_at < since:
            continue
        grouped.setdefault(key, []).append(record)

    summary = {"price_down": 0, "price_up": 0, "msrp_down": 0, "msrp_up": 0, "new_promo": 0}
    details: list[dict[str, Any]] = []
    for key, records in grouped.items():
        records.sort(key=lambda item: item.get("scraped_at") or "")
        first = records[0]
        last = records[-1]
        current_delta = delta(first.get("current_price"), last.get("current_price"))
        msrp_delta = delta(first.get("msrp_price"), last.get("msrp_price"))
        promo_started = not bool(first.get("promotion_status")) and bool(last.get("promotion_status"))
        if current_delta is not None and current_delta < 0:
            summary["price_down"] += 1
        if current_delta is not None and current_delta > 0:
            summary["price_up"] += 1
        if msrp_delta is not None and msrp_delta < 0:
            summary["msrp_down"] += 1
        if msrp_delta is not None and msrp_delta > 0:
            summary["msrp_up"] += 1
        if promo_started:
            summary["new_promo"] += 1
        if current_delta or msrp_delta or promo_started:
            details.append(
                {
                    "product_id": key,
                    "product_name": last.get("product_name"),
                    "brand": last.get("brand"),
                    "category": last.get("category"),
                    "current_price_delta": current_delta,
                    "msrp_price_delta": msrp_delta,
                    "new_promo": promo_started,
                    "product_url": last.get("product_url"),
                }
            )

    return {"summary": summary, "details": details}


def delta(first: Any, last: Any) -> float | None:
    a = price_as_float(first)
    b = price_as_float(last)
    if a is None or b is None:
        return None
    diff = round(b - a, 2)
    return diff if diff != 0 else None


if __name__ == "__main__":
    payload = weekly_change_summary()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
