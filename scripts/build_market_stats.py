#!/usr/bin/env python3
"""Build market-stats.json from the RVD private-domestic district table.

Source package: hk-rvd-tsinfo_rvd-property-market-statistics
(差餉物業估價署 — 物業市場統計)

Default CSV (Traditional Chinese):
https://www.rvd.gov.hk/datagovhk/Dom_Stock_Completions_and_Vacancy_by_District_Chi.csv

The table is one snapshot: year-end stock, completions, and year-end vacancy
for the 18 District Council districts, three region subtotals (港島 / 九龍 / 新界),
and 全港. It does not include prices or take-up. Counts are private domestic
units, not the building points on the map.

RVD district labels sometimes omit 區. This script maps them onto the keys
used by index.html. "-" is the published nil marker and is stored as 0 with
a nil flag. A "+" remark on the completions-share column means below 0.05%.

The published 全港 row is kept as-is. The script checks that it equals the
sum of the 18 districts, and that the three region rows also sum to 全港.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://www.rvd.gov.hk/datagovhk/"
    "Dom_Stock_Completions_and_Vacancy_by_District_Chi.csv"
)
DATASET_URL = (
    "https://data.gov.hk/tc-data/dataset/"
    "hk-rvd-tsinfo_rvd-property-market-statistics"
)
PACKAGE_ID = "hk-rvd-tsinfo_rvd-property-market-statistics"

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

# Region subtotals published in the same CSV. Not selectable in the app.
REGIONS = ["港島", "九龍", "新界"]
HK_KEY = "全港"

# English labels in the twin CSV, mapped to the Traditional Chinese source names
# before the 區 suffix is applied.
EN_TO_TC = {
    "Central and Western": "中西區",
    "Wan Chai": "灣仔",
    "Eastern": "東區",
    "Southern": "南區",
    "HONG KONG": "港島",
    "Yau Tsim Mong": "油尖旺",
    "Sham Shui Po": "深水埗",
    "Kowloon City": "九龍城",
    "Wong Tai Sin": "黃大仙",
    "Kwun Tong": "觀塘",
    "KOWLOON": "九龍",
    "Kwai Tsing": "葵青",
    "Tsuen Wan": "荃灣",
    "Tuen Mun": "屯門",
    "Yuen Long": "元朗",
    "North": "北區",
    "Tai Po": "大埔",
    "Sha Tin": "沙田",
    "Sai Kung": "西貢",
    "Islands": "離島",
    "NEW TERRITORIES": "新界",
    "OVERALL": "全港",
}

YEAR_RE = re.compile(r"(20\d{2})")
COUNT_FIELDS = ("stockPrior", "stock", "completions", "vacant")


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "hk-district-property-overview/market-stats"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def clean(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split())


def app_key(raw_name: str) -> tuple[str, str]:
    """Return (key, kind) where kind is district, region, or territory."""
    name = EN_TO_TC.get(raw_name, raw_name)
    if name == HK_KEY:
        return HK_KEY, "territory"
    if name in REGIONS:
        return name, "region"
    if name in DISTRICTS:
        return name, "district"
    if name and not name.endswith("區"):
        candidate = name + "區"
        if candidate in DISTRICTS:
            return candidate, "district"
    raise SystemExit(f"Unrecognised district label: {raw_name!r}")


def header_role(header: str) -> str:
    folded = header.replace(" ", "").replace("\u3000", "")
    lower = header.lower()
    if folded in ("地區", "District"):
        return "district"
    if "註釋" in folded or "remark" in lower:
        return "share_remark"
    if "空置數目" in folded or "no.vacant" in lower.replace(" ", ""):
        return "vacant"
    if "空置百分率" in folded or "% vacant" in lower:
        return "vacancy_pct"
    if "百分率" in folded or "% of" in lower:
        return "share_pct"
    if "落成量" in folded or lower.startswith("completions in"):
        return "completions"
    if "總存量" in folded or lower.startswith("stock at"):
        return "stock"
    raise SystemExit(f"Unrecognised column: {header!r}")


def year_in(header: str) -> int | None:
    match = YEAR_RE.search(header)
    return int(match.group(1)) if match else None


def parse_count(token: str, label: str) -> tuple[int, bool]:
    text = token.strip().replace(",", "")
    if text == "-":
        return 0, True
    if not re.fullmatch(r"\d+", text):
        raise SystemExit(f"Expected a unit count or '-' in {label}, got {token!r}")
    return int(text), False


def parse_percent(token: str, remark: str, label: str) -> tuple[int | float | None, bool]:
    text = token.strip().replace(",", "")
    note = remark.strip()
    if note not in ("", "+"):
        raise SystemExit(f"Unknown remark in {label}: {remark!r}")
    if note == "+":
        if text not in ("-", ""):
            raise SystemExit(
                f"'+' means below 0.05% and should not accompany a number ({label}: {token!r})"
            )
        return None, True
    if text == "-":
        return None, False
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        raise SystemExit(f"Expected a percentage or '-' in {label}, got {token!r}")
    if "." not in text:
        return int(text), False
    # Keep the published decimal (these are one decimal place, e.g. 2.4).
    number = float(text)
    rendered = json.dumps(number)
    if rendered != text:
        raise SystemExit(
            f"Refusing to round {text!r} into JSON number {rendered} ({label})"
        )
    return number, False


def load_table(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header_index = None
    for index, row in enumerate(rows):
        first = clean(row[0] if row else "")
        if first in ("地區", "District"):
            header_index = index
            break
    if header_index is None:
        raise SystemExit(f"No 地區/District header in {path}")
    header = [clean(cell) for cell in rows[header_index]]
    body = []
    for row in rows[header_index + 1 :]:
        if not row or not clean(row[0]):
            continue
        padded = row + [""] * (len(header) - len(row))
        body.append([clean(cell) for cell in padded[: len(header)]])
    if not body:
        raise SystemExit(f"No data rows in {path}")
    return header, body


def convert(path: Path) -> dict:
    header, body = load_table(path)
    roles = [(header_role(cell), year_in(cell), cell) for cell in header]
    role_names = [role for role, _, _ in roles]
    expected = [
        "district",
        "stock",
        "completions",
        "share_pct",
        "share_remark",
        "stock",
        "vacant",
        "vacancy_pct",
    ]
    if role_names != expected:
        raise SystemExit(
            "Unexpected columns. Got "
            + ", ".join(role_names)
            + ". The parser only accepts the stock / completions / vacancy-by-district table."
        )

    stock_years = [year for role, year, _ in roles if role == "stock"]
    completions_year = next(year for role, year, _ in roles if role == "completions")
    share_year = next(year for role, year, _ in roles if role == "share_pct")
    vacant_year = next(year for role, year, _ in roles if role == "vacant")
    if any(year is None for year in (*stock_years, completions_year, share_year, vacant_year)):
        raise SystemExit(f"Could not read years from headers: {header}")
    prior_stock_year, stock_year = stock_years
    if not prior_stock_year < stock_year:
        raise SystemExit(f"Stock columns are not in year order: {stock_years}")
    if share_year != prior_stock_year:
        raise SystemExit(
            f"Completions share is based on {share_year}, not the prior stock year {prior_stock_year}"
        )

    areas: dict[str, dict] = {}
    regions: dict[str, dict] = {}
    territory: dict | None = None
    seen: set[str] = set()

    for row in body:
        raw_name = row[0]
        key, kind = app_key(raw_name)
        if key in seen:
            raise SystemExit(f"Duplicate row for {key}")
        seen.add(key)

        stock_prior, stock_prior_nil = parse_count(row[1], f"{key} prior stock")
        completions, completions_nil = parse_count(row[2], f"{key} completions")
        share, share_below = parse_percent(row[3], row[4], f"{key} completions share")
        stock, stock_nil = parse_count(row[5], f"{key} stock")
        vacant, vacant_nil = parse_count(row[6], f"{key} vacant")
        vacancy_pct, vacancy_below = parse_percent(row[7], "", f"{key} vacancy rate")
        if stock_prior_nil or stock_nil or vacant_nil or vacancy_below or vacancy_pct is None:
            raise SystemExit(
                f"{key} is missing stock or vacancy. Only completions may be published as '-'."
            )

        record = {
            "stockPrior": stock_prior,
            "stock": stock,
            "completions": completions,
            "completionsNil": completions_nil,
            "completionsSharePct": share,
            "completionsShareBelow": share_below,
            "vacant": vacant,
            "vacancyPct": vacancy_pct,
        }
        if completions_nil and (share is not None or share_below):
            raise SystemExit(f"{key} has no completions but a non-nil share")
        if kind == "district":
            areas[key] = record
        elif kind == "region":
            regions[key] = record
        else:
            territory = record

    missing = [name for name in DISTRICTS if name not in areas]
    if missing:
        raise SystemExit("Missing districts: " + "、".join(missing))
    missing_regions = [name for name in REGIONS if name not in regions]
    if missing_regions or territory is None:
        raise SystemExit("Missing 港島 / 九龍 / 新界 or 全港 row")

    areas[HK_KEY] = territory
    check_sums(areas, regions, territory)

    ordered = {name: areas[name] for name in DISTRICTS}
    ordered[HK_KEY] = areas[HK_KEY]
    ordered_regions = {name: regions[name] for name in REGIONS}

    return {
        "source": {
            "provider": "差餉物業估價署",
            "providerEn": "Rating and Valuation Department",
            "packageId": PACKAGE_ID,
            "title": "私人住宅 — 各區總存量、落成量及空置量",
            "datasetUrl": DATASET_URL,
            "csvUrl": SOURCE_URL,
            "dictionaryUrl": "https://www.rvd.gov.hk/datagovhk/Data_Dic.pdf",
            "unit": "私人住宅單位",
            "boundaryNote": "分區跟隨 2023 年區議會分界。",
            "nilNote": "來源以「-」表示沒有錄得，這裡記為 0，並以 completionsNil 標示。",
            "belowNote": "completionsShareBelow 為 true 時，落成量佔上年存量少於 0.05%（來源註釋「+」）。",
            "stockNote": "最新年底總存量來自最新差餉估價紀錄，不是上年存量加落成量。",
            "omitted": "此表沒有分區樓價，也沒有分區吸納量。",
        },
        "periods": {
            "priorStockYear": prior_stock_year,
            "stockYear": stock_year,
            "completionsYear": completions_year,
            "vacancyYear": vacant_year,
        },
        "areas": ordered,
        "regions": ordered_regions,
    }


def check_sums(areas: dict, regions: dict, territory: dict) -> None:
    for field in COUNT_FIELDS:
        district_sum = sum(areas[name][field] for name in DISTRICTS)
        region_sum = sum(regions[name][field] for name in REGIONS)
        if district_sum != territory[field] or region_sum != territory[field]:
            raise SystemExit(
                f"{field} does not add up: 18 districts {district_sum}, "
                f"regions {region_sum}, 全港 {territory[field]}"
            )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        help="Local Traditional Chinese or English CSV. Downloads the TC file when omitted.",
    )
    parser.add_argument("--url", default=SOURCE_URL, help="CSV URL used when --input is omitted.")
    parser.add_argument("--output", type=Path, default=Path("market-stats.json"))
    args = parser.parse_args()

    source = args.input
    if source is None:
        source = Path("/tmp/rvd-dom-stock-completions-vacancy.csv")
        print(f"Downloading {args.url}", file=sys.stderr)
        download(args.url, source)

    payload = convert(source)
    if args.url != SOURCE_URL:
        payload["source"]["csvUrl"] = args.url
    write_json(args.output, payload)
    territory = payload["areas"][HK_KEY]
    print(json.dumps({
        "output": str(args.output),
        "bytes": args.output.stat().st_size,
        "periods": payload["periods"],
        "districts": len(DISTRICTS),
        "hongKong": {
            "stock": territory["stock"],
            "completions": territory["completions"],
            "vacant": territory["vacant"],
            "vacancyPct": territory["vacancyPct"],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
