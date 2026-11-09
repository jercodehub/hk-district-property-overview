#!/usr/bin/env python3
"""Build buildings.json from the Buildings Department open-data package.

Source dataset: hk-bd-opendata-building-information
(樓宇資料及樓齡紀錄 — address, usage, occupation-permit date, coordinates).

Default download:
https://static.csdi.gov.hk/csdi-webpage/download/0e55c533715b5da3ae0ca6e6024e90b4/csv

The page expects an object keyed by the 18 district names, each an array of
{addr, type, year, lat, lng}. District labels in the CSV sometimes omit 區;
this script appends it when that matches a page district. Records with no
district (for example Lok Ma Chau Loop, "Out Of District") or no occupation
permit date are left out.

Full Hong Kong is small enough for GitHub Pages after dropping unused columns
(about 50k compact records). Pass --max-per-district to write a smaller sample.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCE_URL = (
    "https://static.csdi.gov.hk/csdi-webpage/download/"
    "0e55c533715b5da3ae0ca6e6024e90b4/csv"
)

# Order matches the district buttons in index.html.
DISTRICTS = [
    "中西區",
    "灣仔區",
    "東區",
    "南區",
    "油尖旺區",
    "深水埗區",
    "九龍城區",
    "黃大仙區",
    "觀塘區",
    "沙田區",
    "大埔區",
    "北區",
    "元朗區",
    "屯門區",
    "荃灣區",
    "葵青區",
    "西貢區",
    "離島區",
]

# Rough Hong Kong bounds, wide enough for outlying islands.
LAT_MIN, LAT_MAX = 22.08, 22.62
LNG_MIN, LNG_MAX = 113.75, 114.55


def canon_district(name: str) -> str | None:
    name = (name or "").strip()
    if name in DISTRICTS:
        return name
    if name and not name.endswith("區"):
        candidate = name + "區"
        if candidate in DISTRICTS:
            return candidate
    return None


def clean(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split())


def parse_year(value: str | None) -> int | None:
    text = (value or "").strip()
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    year_text, month_text, day_text = text[:4], text[5:7], text[8:10]
    if not (year_text.isdigit() and month_text.isdigit() and day_text.isdigit()):
        return None
    year, month, day = int(year_text), int(month_text), int(day_text)
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year


def building_type(row: dict) -> str:
    usage = clean(row.get("NSEARCH5_C")) or clean(row.get("NSEARCH5_E"))
    kind = clean(row.get("NSEARCH4_C")) or clean(row.get("NSEARCH4_E"))
    if usage and kind:
        return f"{usage}（{kind}）"
    return usage or kind


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "hk-district-property-overview/build"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def iter_rows(path: Path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise SystemExit(f"No CSV inside {path}")
            with archive.open(names[0]) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                yield from csv.DictReader(text)
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def spread_sample(items: list[dict], limit: int) -> list[dict]:
    """Keep a geographic spread instead of the first N rows."""
    if len(items) <= limit:
        return items
    ordered = sorted(items, key=lambda b: (b["lat"], b["lng"], b["addr"], b["year"]))
    if limit <= 1:
        return [ordered[len(ordered) // 2]]
    step = (len(ordered) - 1) / (limit - 1)
    picked = [ordered[round(i * step)] for i in range(limit)]
    # Stride can repeat a building; fall back to unique insertion order.
    seen = set()
    unique = []
    for item in picked:
        key = (item["addr"], item["type"], item["year"], item["lat"], item["lng"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    if len(unique) < limit:
        for item in ordered:
            key = (item["addr"], item["type"], item["year"], item["lat"], item["lng"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) == limit:
                break
    unique.sort(key=lambda b: (b["addr"], b["year"], b["lat"], b["lng"]))
    return unique


def convert(rows, max_per_district: int | None) -> tuple[dict, dict]:
    grouped = {name: [] for name in DISTRICTS}
    seen = {name: set() for name in DISTRICTS}
    stats = {
        "read": 0,
        "kept": 0,
        "skipped_no_district": 0,
        "skipped_no_year": 0,
        "skipped_bad_coord": 0,
        "deduped": 0,
    }
    for row in rows:
        stats["read"] += 1
        district = canon_district(row.get("SEARCH1_C") or "")
        if district is None:
            stats["skipped_no_district"] += 1
            continue
        year = parse_year(row.get("NSEARCH3_C") or row.get("NSEARCH3_E"))
        if year is None:
            stats["skipped_no_year"] += 1
            continue
        try:
            lat = round(float((row.get("LATITUDE") or "").strip()), 6)
            lng = round(float((row.get("LONGITUDE") or "").strip()), 6)
        except ValueError:
            stats["skipped_bad_coord"] += 1
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
            stats["skipped_bad_coord"] += 1
            continue
        item = {
            "addr": clean(row.get("ADDRESS_C")) or clean(row.get("ADDRESS_E")) or "地址不詳",
            "type": building_type(row),
            "year": year,
            "lat": lat,
            "lng": lng,
        }
        key = (item["addr"], item["type"], item["year"], item["lat"], item["lng"])
        if key in seen[district]:
            stats["deduped"] += 1
            continue
        seen[district].add(key)
        grouped[district].append(item)

    for name in DISTRICTS:
        grouped[name].sort(key=lambda b: (b["addr"], b["year"], b["lat"], b["lng"]))
        if max_per_district is not None:
            grouped[name] = spread_sample(grouped[name], max_per_district)
        stats["kept"] += len(grouped[name])
    return grouped, stats


def write_json(path: Path, grouped: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("{\n")
        for i, name in enumerate(DISTRICTS):
            handle.write(json.dumps(name, ensure_ascii=False) + ":[\n")
            items = grouped[name]
            for j, item in enumerate(items):
                comma = "," if j < len(items) - 1 else ""
                handle.write(
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")) + comma + "\n"
                )
            tail = "," if i < len(DISTRICTS) - 1 else ""
            handle.write("]" + tail + "\n")
        handle.write("}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Local CSV or zip. Downloads the open-data package when omitted.")
    parser.add_argument("--url", default=SOURCE_URL, help="Package URL used when --input is omitted.")
    parser.add_argument("--output", type=Path, default=Path("buildings.json"))
    parser.add_argument(
        "--max-per-district",
        type=int,
        default=None,
        help="Cap each district at this many buildings (geographic sample). Default: keep all.",
    )
    args = parser.parse_args()
    if args.max_per_district is not None and args.max_per_district < 1:
        raise SystemExit("--max-per-district must be at least 1")

    source = args.input
    if source is None:
        source = Path("/tmp/bd-building-information.zip")
        print(f"Downloading {args.url}", file=sys.stderr)
        download(args.url, source)

    grouped, stats = convert(iter_rows(source), args.max_per_district)
    write_json(args.output, grouped)
    counts = {name: len(grouped[name]) for name in DISTRICTS}
    print(json.dumps({
        "output": str(args.output),
        "bytes": args.output.stat().st_size,
        "stats": stats,
        "counts": counts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
