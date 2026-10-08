#!/usr/bin/env python3
"""Download public market data without filling gaps or inventing timestamps.

Python standard library only. A nonzero exit means at least one selected source
failed, including sources whose daily endpoint remains unresolved.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MISSING = {"", ".", "NA", "N/A", "null"}


def fetch(url):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("Only HTTPS sources are accepted")
    request = urllib.request.Request(url, headers={"User-Agent": "InternationalFeaturesResearch/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if urllib.parse.urlparse(response.url).scheme != "https":
            raise ValueError("Refusing a downgrade from HTTPS")
        return response.read(), response.url


def preserve(raw_dir, name, body, url):
    digest = hashlib.sha256(body).hexdigest()
    path = raw_dir / f"{name}-{digest[:16]}"
    if path.exists() and path.read_bytes() != body:
        raise ValueError("Content-addressed file collision")
    if not path.exists():
        path.write_bytes(body)
    return {"path": str(path.relative_to(ROOT)), "url": url, "sha256": digest, "bytes": len(body)}


def numeric(value):
    if value is None or str(value).strip() in MISSING:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite numeric observation")
    return number


def parse_date(value):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unsupported observation date: {value!r}")


def parse_csv(body, date_column, value_column, ohlc_columns=None):
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    required = {date_column, value_column, *(ohlc_columns or {}).values()}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError(f"Missing CSV fields: {sorted(required - set(reader.fieldnames or []))}")
    rows = []
    for raw in reader:
        if not raw.get(date_column):
            raise ValueError("Missing observation date")
        row = {"date": parse_date(raw[date_column]).isoformat(), "value": numeric(raw[value_column])}
        for name, column in (ohlc_columns or {}).items():
            row[name] = numeric(raw[column])
        rows.append(row)
    return rows


def validate(rows, start, end, allow_nonpositive=False, intraday=False):
    if not rows:
        raise ValueError("Empty data response")
    keys = [row["timestamp_utc"] if intraday else row["date"] for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate observations")
    if keys != sorted(keys):
        raise ValueError("Observations are not chronologically ordered")
    selected = [row for row in rows if start <= date.fromisoformat(row["date"]) <= end]
    if not selected:
        raise ValueError("No observations within the requested period")
    valid = [row for row in selected if row["value"] is not None]
    if not valid:
        raise ValueError("All requested observations are missing")
    for row in valid:
        if not math.isfinite(row["value"]):
            raise ValueError("Non-finite numeric observation")
        if not allow_nonpositive and row["value"] <= 0:
            raise ValueError("Nonpositive price/index observation requires source investigation")
        if all(row.get(field) is not None for field in ("open", "high", "low", "close")):
            if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]) or row["low"] > row["high"]:
                raise ValueError("Invalid OHLC range")
    return selected, {
        "source_start": rows[0]["date"],
        "source_end": rows[-1]["date"],
        "requested_rows": len(selected),
        "nonmissing_rows": len(valid),
        "missing_rows": len(selected) - len(valid),
        "observed_start": valid[0]["date"],
        "observed_end": valid[-1]["date"],
        "calendar_days_since_last_observation": (end - date.fromisoformat(valid[-1]["date"])).days,
        "timing_alignment_verified": False,
        "filled_observations": 0,
    }


def datahub(source, raw_dir, artifacts):
    base = f"https://raw.githubusercontent.com/{source['repository']}/{source['revision']}"
    package_body, package_url = fetch(base + "/datapackage.json")
    artifacts.append(preserve(raw_dir, source["id"] + "-datapackage.json", package_body, package_url))
    package = json.loads(package_body)
    resource = next(item for item in package["resources"] if item["name"] == source["resource"])
    if resource.get("format") != "csv":
        raise ValueError("Expected a CSV resource")
    resource_path = resource["path"]
    if not isinstance(resource_path, str) or resource_path.startswith("/") or ".." in resource_path.split("/") or ":" in resource_path:
        raise ValueError("Unexpected resource path")
    body, url = fetch(base + "/" + resource_path)
    artifacts.append(preserve(raw_dir, source["id"] + ".csv", body, url))
    expected = resource.get("hash")
    if expected:
        expected = expected.removeprefix("md5:")
        if len(expected) != 32 or hashlib.md5(body).hexdigest() != expected:
            raise ValueError("Publisher resource checksum mismatch; data not normalized")
    rows = parse_csv(body, source["date_column"], source["value_column"], source.get("ohlc_columns"))
    return rows, {"declared_licenses": package.get("licenses", []), "declared_sources": package.get("sources", []), "publisher_checksum_verified": bool(expected)}


def fred(source, start, end, raw_dir, artifacts):
    query = urllib.parse.urlencode({"id": source["series"], "cosd": start.isoformat(), "coed": end.isoformat()})
    body, url = fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?" + query)
    artifacts.append(preserve(raw_dir, source["id"] + ".csv", body, url))
    fields = csv.DictReader(io.StringIO(body.decode("utf-8-sig"))).fieldnames or []
    column = next((name for name in ("observation_date", "DATE") if name in fields), None)
    if column is None:
        raise ValueError("FRED CSV is missing its observation-date column")
    return parse_csv(body, column, source["series"]), {}


def yahoo(source, start, end, raw_dir, artifacts):
    intraday = source["kind"] == "yahoo_intraday"
    if intraday:
        params = {"range": "1mo", "interval": "30m", "includePrePost": "false"}
    else:
        params = {
            "period1": int(datetime.combine(start, time.min, timezone.utc).timestamp()),
            "period2": int(datetime.combine(end + timedelta(days=1), time.min, timezone.utc).timestamp()),
            "interval": "1d", "includePrePost": "false",
        }
    symbol = urllib.parse.quote(source["symbol"], safe="")
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol + "?" + urllib.parse.urlencode(params)
    body, url = fetch(url)
    artifacts.append(preserve(raw_dir, source["id"] + ".json", body, url))
    payload = json.loads(body)
    if payload["chart"].get("error"):
        raise ValueError("Yahoo returned a chart error: " + str(payload["chart"]["error"]))
    result = payload["chart"]["result"][0]
    metadata = result["meta"]
    zone_name = metadata.get("exchangeTimezoneName")
    if not zone_name:
        raise ValueError("Yahoo exchange timezone is missing")
    if source.get("timezone") and zone_name != source["timezone"]:
        raise ValueError("Unexpected exchange timezone")
    quotes = result["indicators"]["quote"][0]
    rows = []
    for index, stamp in enumerate(result.get("timestamp") or []):
        utc = datetime.fromtimestamp(stamp, timezone.utc)
        row = {"date": utc.astimezone(ZoneInfo(zone_name)).date().isoformat()}
        if intraday:
            row["date"] = utc.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
            row["timestamp_utc"] = utc.isoformat()
            row["bar_start_ist"] = utc.astimezone(ZoneInfo("Asia/Kolkata")).isoformat()
        for field in ("open", "high", "low", "close", "volume"):
            values = quotes.get(field)
            row[field] = numeric(values[index]) if values is not None else None
        row["value"] = row["close"]
        rows.append(row)
    if not intraday:
        # The last daily bar may be incomplete. Exclude the exchange's current
        # local date, even when the caller requests data through today.
        local_today = datetime.now(timezone.utc).astimezone(ZoneInfo(zone_name)).date().isoformat()
        rows = [row for row in rows if row["date"] < local_today]
    return rows, {
        "provider_timezone": zone_name,
        "provider_instrument": {key: metadata.get(key) for key in ("symbol", "exchangeName", "fullExchangeName", "instrumentType", "shortName", "longName", "dataGranularity")},
        "bar_timestamps_are_availability_timestamps": False,
    }


def csv_source(source, raw_dir, artifacts):
    body, url = fetch(source["url"])
    artifacts.append(preserve(raw_dir, source["id"] + ".csv", body, url))
    return parse_csv(body, source["date_column"], source["value_column"], source.get("ohlc_columns")), {}


def acquire(source, start, end, raw_dir, artifacts):
    if source["kind"] == "datahub":
        return datahub(source, raw_dir, artifacts)
    if source["kind"] == "fred":
        return fred(source, start, end, raw_dir, artifacts)
    if source["kind"] == "csv":
        return csv_source(source, raw_dir, artifacts)
    if source["kind"].startswith("yahoo_"):
        return yahoo(source, start, end, raw_dir, artifacts)
    raise ValueError("Daily source endpoint remains unresolved; no proxy series substituted")


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1))
    parser.add_argument("--only", nargs="+", help="Select source identifiers")
    parser.add_argument("--probe-brent-intraday", action="store_true")
    parser.add_argument("--allow-snapshot-fallback", action="store_true", help="Explicitly permit older pinned DataHub snapshots if a live Brent/VIX feed fails")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("Start must not be after end")
    config = json.loads((ROOT / "config/data_sources.json").read_text())
    sources = config["sources"]
    if args.only:
        unknown = set(args.only) - {source["id"] for source in sources}
        if unknown:
            parser.error("Unknown source identifiers: " + ", ".join(sorted(unknown)))
        sources = [source for source in sources if source["id"] in args.only]
    if args.probe_brent_intraday:
        sources = sources + [config["intraday_probe"]]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    raw_dir = ROOT / "data/raw" / run_id
    processed_dir = ROOT / "data/processed" / run_id
    report_dir = ROOT / "data/runs" / run_id
    for directory in (raw_dir, processed_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=False)
    report = {"run_id": run_id, "requested_start": args.start.isoformat(), "requested_end": args.end.isoformat(), "results": []}
    failed = False
    for source in sources:
        result = {"source": source, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "artifacts": []}
        try:
            try:
                rows, details = acquire(source, args.start, args.end, raw_dir, result["artifacts"])
                result["used_snapshot_fallback"] = False
            except Exception as primary_error:
                fallback = source.get("snapshot_fallback")
                if not args.allow_snapshot_fallback or not fallback:
                    raise
                snapshot_source = dict(source, **fallback)
                rows, details = acquire(snapshot_source, args.start, args.end, raw_dir, result["artifacts"])
                result.update(used_snapshot_fallback=True, primary_error=str(primary_error), fallback_source=snapshot_source)
                print(f"{source['id']}: using an older pinned snapshot; live feed failed", flush=True)
            selected, quality = validate(rows, args.start, args.end, allow_nonpositive="yield" in source["id"], intraday=source["kind"] == "yahoo_intraday")
            path = processed_dir / (source["id"] + ".csv")
            write_csv(path, selected)
            result.update(status="downloaded_validated_structure", processed_path=str(path.relative_to(ROOT)), quality=quality, **details)
            print(f"{source['id']}: {quality['nonmissing_rows']} observations, {quality['observed_start']} to {quality['observed_end']}", flush=True)
        except Exception as error:
            failed = True
            result.update(status="failed", error_type=type(error).__name__, error=str(error))
            print(f"{source['id']}: FAILED — {error}", flush=True)
        report["results"].append(result)
        # Persist partial progress after each source; successful downloads are
        # preserved even if another provider fails or the run is interrupted.
        (report_dir / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Run manifest: " + str((report_dir / "manifest.json").relative_to(ROOT)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
