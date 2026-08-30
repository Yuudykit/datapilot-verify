from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample"
GOLDEN = ROOT / "data" / "golden"
SEED = 20260830

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

STORES = [
    ("SH-001", "华东", "上海", "正常"),
    ("SH-003", "华东", "上海", "正常"),
    ("HZ-008", "华东", "杭州", "正常"),
    ("NJ-002", "华东", "南京", "正常"),
    ("NJ-009", "华东", "南京", "新店"),
    ("BJ-001", "华北", "北京", "正常"),
    ("TJ-004", "华北", "天津", "正常"),
    ("GZ-002", "华南", "广州", "正常"),
    ("SZ-006", "华南", "深圳", "正常"),
    ("CD-003", "西南", "成都", "正常"),
    ("CQ-005", "西南", "重庆", "正常"),
]
CATEGORIES = ["家电", "数码", "家居", "食品"]
CHANNELS = ["门店", "小程序", "平台"]


def stable_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    GOLDEN.mkdir(parents=True, exist_ok=True)

    stores_path = OUT / "stores.csv"
    with stores_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["store_id", "region", "city", "status", "opened_at"])
        for store_id, region, city, status in STORES:
            opened = "2026-07-10" if status == "新店" else "2023-01-01"
            writer.writerow([store_id, region, city, status, opened])

    rows: list[dict[str, object]] = []
    order_number = 1
    start = date(2026, 6, 1)
    for offset in range(61):
        paid_at = start + timedelta(days=offset)
        month = paid_at.month
        for store_id, region, _city, status in STORES:
            if status == "新店" and paid_at < date(2026, 7, 10):
                continue
            daily_orders = rng.randint(3, 7)
            for _ in range(daily_orders):
                category = rng.choices(CATEGORIES, weights=[30, 28, 24, 18], k=1)[0]
                channel = rng.choices(CHANNELS, weights=[45, 35, 20], k=1)[0]
                amount = rng.randint(120, 1200)

                # July decline is concentrated in three East-China appliance stores.
                if (
                    month == 7
                    and category == "家电"
                    and store_id in {"SH-003", "HZ-008", "NJ-002"}
                ):
                    amount = int(amount * 0.28)
                elif month == 7 and region == "华东":
                    amount = int(amount * 0.70)
                elif month == 7:
                    amount = int(amount * 0.96)

                refund_rate = 0.07
                if month == 7 and channel == "平台":
                    refund_rate = 0.18
                refunded = rng.random() < refund_rate
                refund_amount = amount if refunded else 0
                rows.append(
                    {
                        "order_id": f"O{order_number:06d}",
                        "paid_at": paid_at.isoformat(),
                        "store_id": store_id,
                        "category": category,
                        "channel": channel,
                        "paid_amount": amount,
                        "refund_amount": refund_amount,
                        "quantity": rng.randint(1, 4),
                    }
                )
                order_number += 1

    orders_path = OUT / "orders.csv"
    with orders_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    store_region = {store_id: region for store_id, region, *_ in STORES}
    totals: dict[int, int] = defaultdict(int)
    by_region: dict[tuple[int, str], int] = defaultdict(int)
    for row in rows:
        month = int(str(row["paid_at"])[5:7])
        net = int(row["paid_amount"]) - int(row["refund_amount"])
        totals[month] += net
        by_region[(month, store_region[str(row["store_id"])])] += net

    decline = totals[7] - totals[6]
    region_changes = {
        region: by_region[(7, region)] - by_region[(6, region)]
        for region in sorted(set(store_region.values()))
    }
    expected = {
        "seed": SEED,
        "row_count": len(rows),
        "file_hashes": {
            "orders.csv": stable_hash(orders_path),
            "stores.csv": stable_hash(stores_path),
        },
        "net_sales": {"2026-06": totals[6], "2026-07": totals[7]},
        "mom_rate": decline / totals[6],
        "change_amount": decline,
        "region_changes": region_changes,
        "largest_decline_region": min(region_changes, key=region_changes.get),
    }
    (GOLDEN / "expected_metrics.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(expected, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    generate()
