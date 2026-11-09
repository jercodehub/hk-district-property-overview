#!/usr/bin/env python3
"""Build market-stats.json from RVD private-domestic tables.

Source package: hk-rvd-tsinfo_rvd-property-market-statistics
(差餉物業估價署 — 物業市場統計)

Stock / completions / vacancy (Traditional Chinese CSV):
https://www.rvd.gov.hk/datagovhk/Dom_Stock_Completions_and_Vacancy_by_District_Chi.csv

That table is one snapshot: year-end stock, completions, and year-end vacancy
for the 18 District Council districts, three region subtotals (港島 / 九龍 / 新界),
and 全港. Counts are private domestic units, not the building points on the map.
It has no prices and no district take-up.

RVD district labels sometimes omit 區. This script maps them onto the keys
used by index.html. "-" is the published nil marker and is stored as 0 with
a nil flag. A "+" remark on the completions-share column means below 0.05%.

The published 全港 row is kept as-is. The script checks that it equals the
sum of the 18 districts, and that the three region rows also sum to 全港.

Latest prices (two more CSVs from the same package):

- Private domestic average prices by class, monthly from 1999
  (港島 / 九龍 / 新界, not the 18 districts). From 1999, 九龍 includes 新九龍.
  https://www.rvd.gov.hk/datagovhk/1.2M.csv
- Private domestic price indices by class, territory-wide, monthly from 1993.
  1999 = 100.
  https://www.rvd.gov.hk/datagovhk/1.4M.csv

Only the latest month of each series is written. There is still no 18-district
price. "-" means no transaction; remark P is provisional; remark Z is fewer
than 20 transactions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from decimal import Decimal
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
PRICE_URL = "https://www.rvd.gov.hk/datagovhk/1.2M.csv"
INDEX_URL = "https://www.rvd.gov.hk/datagovhk/1.4M.csv"

# RVD average prices since 1999 use three regions. 九龍 includes 新九龍.
# This is the same 4 / 5 / 9 split as the stock table's region rows, not a
# finer district price.
DISTRICT_REGION = {
    "中西區": "港島",
    "灣仔區": "港島",
    "東區": "港島",
    "南區": "港島",
    "油尖旺區": "九龍",
    "深水埗區": "九龍",
    "九龍城區": "九龍",
    "黃大仙區": "九龍",
    "觀塘區": "九龍",
    "沙田區": "新界",
    "大埔區": "新界",
    "北區": "新界",
    "元朗區": "新界",
    "屯門區": "新界",
    "荃灣區": "新界",
    "葵青區": "新界",
    "西貢區": "新界",
    "離島區": "新界",
}
PRICE_REGION_EN = {
    "Hong Kong": "港島",
    "Kowloon": "九龍",
    "New Territories": "新界",
}
PRICE_CLASSES = ("A", "B", "C", "D", "E")
INDEX_SERIES = {
    "Class A": "A",
    "Class B": "B",
    "Class C": "C",
    "Class D": "D",
    "Class E": "E",
    "Classes A, B & C": "abc",
    "Classes D & E": "de",
    "All Classes": "all",
}
CLASS_META = [
    {"id": "A", "label": "A 類", "area": "實用面積少於 40 平方米"},
    {"id": "B", "label": "B 類", "area": "實用面積 40 至 69.9 平方米"},
    {"id": "C", "label": "C 類", "area": "實用面積 70 至 99.9 平方米"},
    {"id": "D", "label": "D 類", "area": "實用面積 100 至 159.9 平方米"},
    {"id": "E", "label": "E 類", "area": "實用面積 160 平方米或以上"},
]

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
            "omitted": "此表沒有分區樓價，也沒有分區吸納量。樓價見 prices：平均售價只到港島／九龍／新界，售價指數是全港。",
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


def load_month_table(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header_index = None
    for index, row in enumerate(rows):
        if clean(row[0] if row else "") == "Month":
            header_index = index
            break
    if header_index is None:
        raise SystemExit(f"No Month header in {path}")
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


def parse_month(token: str, label: str) -> tuple[int, int]:
    match = re.fullmatch(r"(0[1-9]|1[0-2])-(\d{4})", token.strip())
    if not match:
        raise SystemExit(f"Expected MM-YYYY in {label}, got {token!r}")
    month, year = int(match.group(1)), int(match.group(2))
    # The monthly price file starts in 1999; the index file starts in 1993.
    if not 1979 <= year <= 2100:
        raise SystemExit(f"Unexpected year in {label}: {token!r}")
    return year, month


def parse_measure(token: str, label: str) -> tuple[int | float | None, str | None]:
    """Return (number, nil_token). nil_token is set when the cell is not a price."""
    text = token.strip().replace(",", "").replace(" ", "")
    if text in ("-", "N.A.", "NA"):
        return None, text
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        raise SystemExit(f"Expected a number, '-' or 'N.A.' in {label}, got {token!r}")
    if "." not in text:
        return int(text), None
    number = float(text)
    if json.dumps(number) != text:
        raise SystemExit(f"Refusing to round {text!r} into JSON number {json.dumps(number)} ({label})")
    return number, None


def parse_price_remark(token: str, label: str) -> tuple[bool, bool]:
    """Return (provisional, few_transactions). Only P and Z are accepted."""
    text = token.strip()
    if text == "":
        return False, False
    letters = set(text)
    if letters - {"P", "Z"} or not letters:
        raise SystemExit(
            f"Unknown price remark in {label}: {token!r}. "
            "Only P (provisional) and Z (fewer than 20 transactions) are accepted."
        )
    return "P" in letters, "Z" in letters


def measure_cell(value_token: str, remark_token: str, label: str) -> dict:
    value, nil = parse_measure(value_token, label)
    provisional, few = parse_price_remark(remark_token, label)
    if nil is not None and (provisional or few):
        raise SystemExit(f"{label} is {nil!r} but also has a remark {remark_token!r}")
    if nil is not None and nil != "-":
        raise SystemExit(f"{label} is {nil!r}; this build only keeps '-' as no transaction")
    return {
        "value": value,
        "provisional": provisional,
        "fewTransactions": few,
        "noTransaction": nil == "-",
    }


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def format_delta(current: str, previous: str) -> str:
    diff = Decimal(current) - Decimal(previous)
    text = format(diff, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    if not text.startswith("-"):
        text = "+" + text
    return text


def latest_rows(body: list[list[str]], label: str) -> list[tuple[int, int, list[str]]]:
    parsed = []
    seen = set()
    for row in body:
        year, month = parse_month(row[0], label)
        key = (year, month)
        if key in seen:
            raise SystemExit(f"Duplicate month {month_key(year, month)} in {label}")
        seen.add(key)
        parsed.append((year, month, row))
    parsed.sort(key=lambda item: (item[0], item[1]))
    return parsed


def provisional_flags(cells: list[dict]) -> tuple[bool, bool]:
    flags = [cell["provisional"] for cell in cells if not cell["noTransaction"]]
    if not flags:
        return False, False
    return any(flags), all(flags)


def convert_average_prices(path: Path) -> dict:
    header, body = load_month_table(path)
    folded = " ".join(header)
    if "New Kowloon" in folded:
        raise SystemExit(
            f"{path} still splits New Kowloon. Use the from-1999 monthly file "
            "(1.2M.csv), where 九龍 includes 新九龍."
        )
    columns: dict[tuple[str, str], int] = {}
    remarks: dict[tuple[str, str], int] = {}
    for index, cell in enumerate(header):
        if index == 0:
            if cell != "Month":
                raise SystemExit(f"First column of {path} is {cell!r}, expected Month")
            continue
        match = re.fullmatch(
            r"Class ([A-E]) (Hong Kong|Kowloon|New Territories)( - Remarks)?",
            cell,
        )
        if not match:
            raise SystemExit(f"Unrecognised average-price column: {cell!r}")
        key = (match.group(1), PRICE_REGION_EN[match.group(2)])
        if match.group(3):
            if key in remarks:
                raise SystemExit(f"Duplicate remark column for {key}")
            remarks[key] = index
        else:
            if key in columns:
                raise SystemExit(f"Duplicate value column for {key}")
            columns[key] = index
    expected = {(klass, region) for klass in PRICE_CLASSES for region in REGIONS}
    if set(columns) != expected or set(remarks) != expected:
        raise SystemExit("Average-price table is missing a class/region column or its remark")

    rows = latest_rows(body, f"average prices {path.name}")
    year, month, row = rows[-1]
    areas: dict[str, dict] = {}
    cells = []
    for region in REGIONS:
        areas[region] = {}
        for klass in PRICE_CLASSES:
            key = (klass, region)
            cell = measure_cell(
                row[columns[key]],
                row[remarks[key]],
                f"{month_key(year, month)} {region} {klass}",
            )
            areas[region][klass] = cell
            cells.append(cell)
    any_provisional, all_provisional = provisional_flags(cells)
    return {
        "month": month_key(year, month),
        "year": year,
        "monthNumber": month,
        "provisional": any_provisional,
        "allProvisional": all_provisional,
        "unit": "港元／平方米（實用面積）",
        "areas": areas,
    }


def convert_price_index(path: Path) -> dict:
    header, body = load_month_table(path)
    columns: dict[str, int] = {}
    remarks: dict[str, int] = {}
    for index, cell in enumerate(header):
        if index == 0:
            if cell != "Month":
                raise SystemExit(f"First column of {path} is {cell!r}, expected Month")
            continue
        match = re.fullmatch(
            r"(Class [A-E]|Classes A, B & C|Classes D & E|All Classes)( - Remarks)?",
            cell,
        )
        if not match:
            raise SystemExit(f"Unrecognised price-index column: {cell!r}")
        key = INDEX_SERIES[match.group(1)]
        if match.group(2):
            remarks[key] = index
        else:
            columns[key] = index
    expected = set(INDEX_SERIES.values())
    if set(columns) != expected or set(remarks) != expected:
        raise SystemExit("Price-index table is missing a series or its remark column")

    rows = latest_rows(body, f"price index {path.name}")
    year, month, row = rows[-1]
    series = {}
    raw_tokens = {}
    cells = []
    for key in ("all", "abc", "de", *PRICE_CLASSES):
        cell = measure_cell(
            row[columns[key]],
            row[remarks[key]],
            f"{month_key(year, month)} index {key}",
        )
        if cell["noTransaction"] or cell["value"] is None:
            raise SystemExit(f"Territory price index {key} has no value for {month_key(year, month)}")
        series[key] = cell
        raw_tokens[key] = row[columns[key]].strip().replace(",", "").replace(" ", "")
        cells.append(cell)
    any_provisional, all_provisional = provisional_flags(cells)

    previous = None
    if len(rows) >= 2:
        prev_year, prev_month, prev_row = rows[-2]
        prev_cell = measure_cell(
            prev_row[columns["all"]],
            prev_row[remarks["all"]],
            f"{month_key(prev_year, prev_month)} index all",
        )
        if prev_cell["value"] is not None:
            prev_token = prev_row[columns["all"]].strip().replace(",", "").replace(" ", "")
            previous = {
                "month": month_key(prev_year, prev_month),
                "year": prev_year,
                "monthNumber": prev_month,
                "all": prev_cell["value"],
                "change": format_delta(raw_tokens["all"], prev_token),
            }

    return {
        "month": month_key(year, month),
        "year": year,
        "monthNumber": month,
        "base": "1999 = 100",
        "grain": "全港",
        "provisional": any_provisional,
        "allProvisional": all_provisional,
        "series": series,
        "previous": previous,
    }


def convert_prices(prices_path: Path, index_path: Path) -> dict:
    average = convert_average_prices(prices_path)
    index = convert_price_index(index_path)
    missing = [name for name in DISTRICTS if DISTRICT_REGION.get(name) not in REGIONS]
    if missing or set(DISTRICT_REGION) != set(DISTRICTS):
        raise SystemExit("District-to-region map does not cover the 18 districts")
    return {
        "source": {
            "provider": "差餉物業估價署",
            "providerEn": "Rating and Valuation Department",
            "packageId": PACKAGE_ID,
            "title": "私人住宅平均售價（按類別及區域）及全港售價指數",
            "datasetUrl": DATASET_URL,
            "averagePricesCsvUrl": PRICE_URL,
            "priceIndexCsvUrl": INDEX_URL,
            "dictionaryUrl": "https://www.rvd.gov.hk/datagovhk/Data_Dic.pdf",
            "averagePriceTitle": "私人住宅 — 各類單位平均售價（每月）",
            "priceIndexTitle": "私人住宅 — 各類單位售價指數（全港，每月）",
            "unit": "港元／平方米（實用面積）",
            "indexBase": "1999 = 100",
            "grain": "平均售價只到港島、九龍、新界，不是區議會 18 區。1999 年起九龍包括新九龍。售價指數是全港，按單位類別。",
            "primarySalesNote": "不包括住宅樓宇的首次買賣。",
            "mixNote": "平均售價會受所分析單位的質素影響，不能直接當成價格升跌。看升跌用售價指數。",
            "provisionalNote": "provisional 為 true 代表來源註 P，屬臨時數字。",
            "fewTransactionsNote": "fewTransactions 為 true 代表來源註 Z，少於 20 宗成交。",
            "nilNote": "沒有成交（來源「-」）記為 value null，並以 noTransaction 標示。",
        },
        "classes": CLASS_META,
        "regions": list(REGIONS),
        "districtRegion": {name: DISTRICT_REGION[name] for name in DISTRICTS},
        "averagePrices": average,
        "priceIndex": index,
    }


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
    parser.add_argument("--url", default=SOURCE_URL, help="Stock CSV URL used when --input is omitted.")
    parser.add_argument(
        "--prices-input",
        type=Path,
        help="Local monthly average-price CSV (1.2M). Downloaded when omitted.",
    )
    parser.add_argument("--prices-url", default=PRICE_URL, help="Average-price CSV URL.")
    parser.add_argument(
        "--index-input",
        type=Path,
        help="Local monthly territory price-index CSV (1.4M). Downloaded when omitted.",
    )
    parser.add_argument("--index-url", default=INDEX_URL, help="Price-index CSV URL.")
    parser.add_argument("--output", type=Path, default=Path("market-stats.json"))
    args = parser.parse_args()

    source = args.input
    if source is None:
        source = Path("/tmp/rvd-dom-stock-completions-vacancy.csv")
        print(f"Downloading {args.url}", file=sys.stderr)
        download(args.url, source)

    prices_source = args.prices_input
    if prices_source is None:
        prices_source = Path("/tmp/rvd-private-domestic-average-prices-monthly.csv")
        print(f"Downloading {args.prices_url}", file=sys.stderr)
        download(args.prices_url, prices_source)

    index_source = args.index_input
    if index_source is None:
        index_source = Path("/tmp/rvd-private-domestic-price-index-monthly.csv")
        print(f"Downloading {args.index_url}", file=sys.stderr)
        download(args.index_url, index_source)

    payload = convert(source)
    if args.url != SOURCE_URL:
        payload["source"]["csvUrl"] = args.url
    payload["prices"] = convert_prices(prices_source, index_source)
    if args.prices_url != PRICE_URL:
        payload["prices"]["source"]["averagePricesCsvUrl"] = args.prices_url
    if args.index_url != INDEX_URL:
        payload["prices"]["source"]["priceIndexCsvUrl"] = args.index_url
    write_json(args.output, payload)
    territory = payload["areas"][HK_KEY]
    prices = payload["prices"]
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
        "prices": {
            "averageMonth": prices["averagePrices"]["month"],
            "averageProvisional": prices["averagePrices"]["provisional"],
            "indexMonth": prices["priceIndex"]["month"],
            "indexAll": prices["priceIndex"]["series"]["all"]["value"],
            "indexChange": (prices["priceIndex"]["previous"] or {}).get("change"),
            "classA": {
                region: prices["averagePrices"]["areas"][region]["A"]["value"]
                for region in REGIONS
            },
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
