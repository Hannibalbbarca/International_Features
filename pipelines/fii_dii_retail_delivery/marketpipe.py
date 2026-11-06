"""Local Indian cash-market delivery archive. Python 3.10+, standard library only.

All delivery-money calculations and remaining-participant values are labelled
estimates. Missing data is never filled with a numeric zero.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import csv
from datetime import date, datetime, time as daytime, timedelta, timezone
import gzip
import hashlib
import html
import io
import json
import math
from pathlib import Path
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

VERSION = "1.0.0"
METHOD = "gross_client_vwap_estimate_v1"
IST = timezone(timedelta(hours=5, minutes=30))
HOME = Path(__file__).resolve().parent
MONTHS = ("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC").split()
LONG_MONTHS = ("January February March April May June July August September October November December").split()
EXCHANGES = ("NSE", "BSE", "MSEI")
CRORE = 10_000_000


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def local_today():
    return datetime.now(IST).date()


def iso(value):
    return date.fromisoformat(value)


def years_ago(day, years):
    try:
        return day.replace(year=day.year-years)
    except ValueError:
        return day.replace(year=day.year-years, day=28)


def n(value):
    if value is None or str(value).strip() in ("", "-", "--", "NA", "N/A"):
        return None
    result = float(str(value).strip().replace(",", ""))
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric field")
    return result


def integer(value):
    value = n(value)
    if value is None:
        return None
    if not value.is_integer() or value < 0:
        raise ValueError("Quantity must be a nonnegative integer")
    return int(value)


def date_matches(value, target):
    value = str(value).strip().split("T")[0]
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d%m%Y", "%d/%m/%Y", "%m/%d/%Y",
                "%d/%b/%Y", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            if datetime.strptime(value, fmt).date() == target:
                return True
        except ValueError:
            pass
    return False


def unpack(raw):
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [name for name in archive.namelist()
                     if name.lower().endswith((".csv", ".txt", ".dat")) and not name.endswith("/")]
            if len(names) != 1:
                raise ValueError(f"Expected one data file, found {names[:5]}")
            return archive.read(names[0])
    return raw


def csv_rows(raw, delimiter=","):
    payload = unpack(raw)
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        text = payload.decode("cp1252", errors="strict")
    if re.search(r"<(?:!doctype|html|body)\b", text[:1000], re.I):
        raise ValueError("HTML response, not exchange data")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("Empty file")
    return [{str(k).strip(): (v or "").strip() for k, v in row.items() if k and k.strip()}
            for row in reader if any(v and str(v).strip() for v in row.values())]


def prices(raw, target, exchange):
    result = []
    for row in csv_rows(raw):
        if "TradDt" in row:  # UDiFF
            if not date_matches(row["TradDt"], target):
                raise ValueError(f"Internal trade date {row['TradDt']} != {target}")
            item = {"key": row["FinInstrmId"] if exchange == "BSE" else (row["TckrSymb"], row["SctySrs"]),
                    "symbol": row["TckrSymb"], "series": row["SctySrs"], "isin": row.get("ISIN", ""),
                    "q": integer(row["TtlTradgVol"]), "v": n(row["TtlTrfVal"]),
                    "close": n(row["ClsPric"])}
        elif exchange == "NSE" and "TOTTRDQTY" in row:  # pre-July 2024
            if not date_matches(row["TIMESTAMP"], target):
                raise ValueError("Legacy NSE internal date mismatch")
            item = {"key": (row["SYMBOL"], row["SERIES"]), "symbol": row["SYMBOL"],
                    "series": row["SERIES"], "isin": row.get("ISIN", ""),
                    "q": integer(row["TOTTRDQTY"]), "v": n(row["TOTTRDVAL"]), "close": n(row["CLOSE"])}
        elif exchange == "BSE" and "SC_CODE" in row:
            # Legacy BSE price files have no internal date field. They must be
            # corroborated against the dated delivery file before they are used.
            item = {"key": row["SC_CODE"], "symbol": row.get("SC_NAME", ""),
                    "series": row.get("SC_GROUP", ""), "isin": row.get("ISIN_CODE", ""),
                    "q": integer(row["NO_OF_SHRS"]), "v": n(row["NET_TURNOV"]),
                    "close": n(row["CLOSE"]), "filename_date_only": True}
        elif exchange == "MSEI" and "Volume (Quantity)" in row:
            if not date_matches(row["Date"], target):
                raise ValueError("MSEI internal trade date mismatch")
            if row.get("Currency Code", "INR") != "INR":
                raise ValueError("MSEI value is not INR")
            item = {"key": (row["Symbol"], row["Series"]), "symbol": row["Symbol"],
                    "series": row["Series"], "isin": "", "q": integer(row["Volume (Quantity)"]),
                    "v": n(row["Traded Value"]), "close": n(row["Close"])}
        else:
            raise ValueError(f"Unrecognised {exchange} price schema: {list(row)[:6]}")
        if item["q"] is None or item["v"] is None or item["v"] < 0:
            raise ValueError("Missing/negative price-file quantity or turnover")
        if item["q"] == 0 and item["v"] != 0:
            raise ValueError("Nonzero turnover with zero traded quantity")
        if item["close"] is not None and item["close"] <= 0:
            item["close"] = None
        result.append(item)
    if not result:
        raise ValueError("Empty report cannot establish a dated zero-trading session")
    if len({x["key"] for x in result}) != len(result):
        raise ValueError("Duplicate price record keys")
    return result


def mto(raw, target):
    text = raw.decode("utf-8-sig")
    if not re.search(r"Trade Date\s*<"+target.strftime("%d-%b-%Y")+r">", text, re.I):
        raise ValueError("NSE delivery internal date mismatch")
    result, control = {}, None
    for row in csv.reader(io.StringIO(text)):
        if row and row[0] == "10":
            if not date_matches(row[2], target):
                raise ValueError("MTO header date mismatch")
            control = (integer(row[3]), integer(row[4]))
        if row and row[0] == "20":
            key = (row[2].strip(), row[3].strip())
            if key in result:
                raise ValueError("Duplicate MTO key")
            q, dq = integer(row[4]), integer(row[5])
            if q is None or dq is None or dq > q:
                raise ValueError("Invalid MTO delivery quantity")
            result[key] = {"q": q, "dq": dq}
    if not result or control != (sum(x["dq"] for x in result.values()), len(result)):
        raise ValueError("MTO record count / deliverable-quantity control total failed")
    return result


def bse_delivery(raw, target):
    result = {}
    for row in csv_rows(raw, "|"):
        if not date_matches(row["DATE"], target):
            raise ValueError("BSE delivery internal date mismatch")
        key = row["SCRIP CODE"]
        if key in result:
            raise ValueError("Duplicate BSE delivery code")
        q, dq = integer(row["DAY'S VOLUME"]), integer(row["DELIVERY QTY"])
        if q is None or dq is None or dq > q:
            raise ValueError("Invalid BSE delivery quantities")
        v, dv = n(row["DAY'S TURNOVER"]), n(row["DELIVERY VAL"])
        if v is None or dv is None or min(v, dv) < 0:
            raise ValueError("Invalid BSE monetary fields")
        result[key] = {"q": q, "dq": dq, "v": v, "official_dv": dv}
    if not result:
        raise ValueError("No dated BSE delivery records")
    return result


def parse(kind, raw, target):
    if kind == "nse_delivery":
        return mto(raw, target)
    if kind == "bse_delivery":
        return bse_delivery(raw, target)
    if kind == "msei_activity":
        text = unpack(raw).decode("utf-8-sig")
        rows = [r for r in csv.reader(io.StringIO(text)) if r and r[0].strip()]
        if not rows or not date_matches(rows[0][0], target):
            raise ValueError("MSEI activity report internal date mismatch")
        values = {r[0].strip(): r[1].strip() for r in rows if len(r) > 1}
        turnover, quantity = n(values.get("Traded Value (Rs.)")), integer(values.get("Traded Quantity"))
        if turnover is None or quantity is None or turnover < 0 or (turnover == 0) != (quantity == 0):
            raise ValueError("Missing or inconsistent MSEI activity totals")
        return {"v": turnover, "verified_zero": turnover == quantity == 0}
    return prices(raw, target, kind.split("_")[0].upper())


def source_url(kind, day):
    ddmmyyyy = day.strftime("%d%m%Y")
    if kind == "nse_prices":
        if day >= date(2024, 7, 8):
            return f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
        mon = MONTHS[day.month-1]
        return f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{day.year}/{mon}/cm{day.day:02}{mon}{day.year}bhav.csv.zip"
    if kind == "nse_delivery":
        return f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{ddmmyyyy}.DAT"
    if kind == "bse_delivery":
        return f"https://www.bseindia.com/BSEDATA/gross/{day.year}/SCBSEALL{day:%d%m}.zip"
    if kind == "bse_prices":
        if day >= date(2024, 7, 8):
            return f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV"
        return f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{day:%d%m%y}_CSV.ZIP"
    if kind in ("msei_prices", "msei_activity"):
        report = "Statistics" if kind == "msei_prices" else "Activity"
        return f"https://www.msei.in/SX-Content/daily/Equity/{day.year}/{LONG_MONTHS[day.month-1]}/{day.day}/Market-{report}-Report_{ddmmyyyy}.csv"
    raise ValueError(kind)


class HostGate:
    def __init__(self, delay):
        self.delay, self.lock, self.next = delay, threading.Lock(), {}

    def wait(self, url):
        host = urllib.request.urlparse(url).hostname if hasattr(urllib.request, "urlparse") else url.split("/")[2]
        with self.lock:
            now = time.monotonic()
            deadline = max(now, self.next.get(host, now))
            self.next[host] = deadline+self.delay
        time.sleep(max(0, deadline-now))


def network(url, gate, timeout=25, retries=2):
    last = None
    for attempt in range(retries+1):
        gate.wait(url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read(40_000_001)
                if len(raw) > 40_000_000:
                    raise ValueError("Unexpected file over 40 MB")
                return raw, response.status
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 401, 403, 404, 410):
                raise
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            retry_after = exc.headers.get("Retry-After", "")
            pause = min(30, int(retry_after)) if retry_after.isdigit() else min(20, 2**attempt+random.random())
        except (OSError, ValueError) as exc:
            last, pause = exc, min(20, 2**attempt+random.random())
        if attempt < retries:
            time.sleep(pause)
    raise last


SCHEMA = """
CREATE TABLE IF NOT EXISTS cache(day TEXT,kind TEXT,url TEXT,path TEXT,sha256 TEXT,fetched_utc TEXT,
 PRIMARY KEY(day,kind));
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,day TEXT,kind TEXT,url TEXT,
 attempted_utc TEXT,status TEXT,http_status INTEGER,error TEXT,sha256 TEXT);
CREATE INDEX IF NOT EXISTS attempt_lookup ON attempts(day,kind,id);
CREATE TABLE IF NOT EXISTS exchange_daily(day TEXT,exchange TEXT,method TEXT,payload TEXT,
 updated_utc TEXT, PRIMARY KEY(day,exchange));
CREATE TABLE IF NOT EXISTS institutions(day TEXT PRIMARY KEY,fii_buy REAL,fii_sell REAL,
 dii_buy REAL,dii_sell REAL,source TEXT,scope TEXT,published_utc TEXT);
CREATE TABLE IF NOT EXISTS institution_revisions(id INTEGER PRIMARY KEY,day TEXT,
 previous_payload TEXT,replaced_utc TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,started_utc TEXT,finished_utc TEXT,
 mode TEXT,start_day TEXT,end_day TEXT,processed INTEGER DEFAULT 0,status TEXT);
"""


class Pipeline:
    def __init__(self, data_dir, delay=.75, timeout=25, retries=2, offline=False):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root/"market.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript(SCHEMA)
        self.gate, self.timeout, self.retries = HostGate(delay), timeout, retries
        self.offline = offline

    def close(self):
        self.db.close()

    def save(self, kind, day, raw, url):
        parsed = parse(kind, raw, day)  # Validate before promoting a cache entry.
        digest = hashlib.sha256(raw).hexdigest()
        folder = self.root/"raw"/kind/str(day.year)
        folder.mkdir(parents=True, exist_ok=True)
        filename = folder/f"{day}_{digest[:16]}.bin.gz"
        if not filename.exists():
            temp = filename.with_suffix(".tmp")
            temp.write_bytes(gzip.compress(raw, compresslevel=5))
            temp.replace(filename)
        self.db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?,?)",
                        (str(day), kind, url, str(filename.relative_to(self.root)), digest, utcnow()))
        self.db.commit()
        return parsed

    def cached(self, kind, day):
        row = self.db.execute("SELECT * FROM cache WHERE day=? AND kind=?", (str(day), kind)).fetchone()
        if row:
            raw = gzip.decompress((self.root/row["path"]).read_bytes())
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError(f"Corrupted cache: {day} {kind}")
            return parse(kind, raw, day)
        return None

    def cooling_down(self, kind, day):
        row = self.db.execute("SELECT * FROM attempts WHERE day=? AND kind=? ORDER BY id DESC LIMIT 1",
                              (str(day), kind)).fetchone()
        if not row or row["status"] == "ok":
            return False
        age = datetime.now(timezone.utc)-datetime.fromisoformat(row["attempted_utc"])
        # A 404 means unavailable, not confirmed holiday. Recheck recent files.
        hours = .5 if day >= local_today()-timedelta(days=7) else 24*30 if row["http_status"] in (404, 410) else 1
        return age < timedelta(hours=hours)

    def fetch_many(self, kinds, day, refresh=False, retry_missing=False):
        result, jobs = {}, []
        for kind in kinds:
            cached = self.cached(kind, day)
            result[kind] = cached
            if self.offline or (cached is not None and not refresh):
                continue
            if cached is None and not retry_missing and self.cooling_down(kind, day):
                continue
            jobs.append((kind, source_url(kind, day)))
        def worker(job):
            kind, url = job
            try:
                raw, code = network(url, self.gate, self.timeout, self.retries)
                parsed = parse(kind, raw, day)
                return kind, url, raw, code, parsed, None
            except Exception as exc:
                return kind, url, None, getattr(exc, "code", None), None, str(exc)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for kind, url, raw, code, parsed, error in pool.map(worker, jobs):
                stamp = utcnow()
                digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
                self.db.execute("INSERT INTO attempts(day,kind,url,attempted_utc,status,http_status,error,sha256) VALUES(?,?,?,?,?,?,?,?)",
                                (str(day), kind, url, stamp, "error" if error else "ok", code, error, digest))
                if error is None:
                    result[kind] = self.save(kind, day, raw, url)
                # On failed refresh, keep the previous valid, dated source.
                self.db.commit()
        return result

    def process_day(self, day, refresh=False, retry_missing=False, probe_all=False):
        first = self.fetch_many(["nse_prices"], day, refresh, retry_missing)
        if first["nse_prices"] is None and not probe_all:
            return {"date": str(day), "status": "NSE price report unavailable; other exchanges not probed", "models": 0}
        rest = self.fetch_many(["nse_delivery", "bse_delivery", "bse_prices", "msei_prices"], day,
                               refresh, retry_missing)
        reports = {**first, **rest}
        if reports["msei_prices"] is None:
            reports.update(self.fetch_many(["msei_activity"], day, refresh, retry_missing))
        count = 0
        for exchange in EXCHANGES:
            summary = aggregate(exchange, reports)
            if summary is not None:
                summary.update(day=str(day), exchange=exchange, method=METHOD)
                self.db.execute("INSERT OR REPLACE INTO exchange_daily VALUES(?,?,?,?,?)",
                                (str(day), exchange, METHOD, json.dumps(summary), utcnow()))
                count += 1
        self.db.commit()
        return {"date": str(day), "status": "processed", "models": count}

    def put_institutions(self, day, fb, fs, db, ds, source, scope="combined_cash"):
        values = [fb, fs, db, ds]
        if any(v is None or not math.isfinite(float(v)) or float(v) < 0 for v in values):
            raise ValueError("Four nonnegative gross institutional values are required, in INR crore")
        if day > local_today():
            raise ValueError("Cannot store future actual institutional data")
        previous = self.db.execute("SELECT * FROM institutions WHERE day=?", (str(day),)).fetchone()
        if previous and any(abs(previous[key]-value) > .000001 for key,value in zip(
                ("fii_buy", "fii_sell", "dii_buy", "dii_sell"), values)):
            self.db.execute("INSERT INTO institution_revisions(day,previous_payload,replaced_utc) VALUES(?,?,?)",
                            (str(day), json.dumps(dict(previous)), utcnow()))
        self.db.execute("INSERT OR REPLACE INTO institutions VALUES(?,?,?,?,?,?,?,?)",
                        (str(day), *values, source, scope, utcnow()))

    def capture_institutions(self):
        if self.offline:
            return "offline: latest institutional request skipped"
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        try:
            raw, _ = network(url, self.gate, self.timeout, self.retries)
            obj = json.loads(raw)
            if not isinstance(obj, list):
                raise ValueError("Unexpected institutional schema")
            cats = {x["category"]: x for x in obj}
            f, d = cats["FII/FPI"], cats["DII"]
            days = [datetime.strptime(x["date"], "%d-%b-%Y").date() for x in (f, d)]
            if days[0] != days[1]:
                raise ValueError("Institutional category dates disagree")
            values = [n(x[k]) for x in (f, d) for k in ("buyValue", "sellValue")]
            for row in (f, d):
                if abs(n(row["buyValue"])-n(row["sellValue"])-n(row["netValue"])) > .021:
                    raise ValueError("Institutional buy/sell/net reconciliation failed")
            self.put_institutions(days[0], *values, url)
            folder = self.root/"raw"/"institutions"/str(days[0].year)
            folder.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(raw).hexdigest()
            (folder/f"{days[0]}_{digest[:16]}.json").write_bytes(raw)
            self.db.commit()
            return f"institutional snapshot stored under its actual date {days[0]}"
        except Exception as exc:
            return f"institutional fetch unavailable: {exc}"

    def seed(self, snapshot):
        snapshot = Path(snapshot)
        metadata = json.loads((snapshot/"sources.json").read_text())
        day = iso(metadata["trade_date"])
        mapping = {"nse_udiff": "nse_prices", "nse_delivery": "nse_delivery",
                   "bse_udiff": "bse_prices", "bse_delivery": "bse_delivery", "msei_statistics": "msei_prices"}
        for item in metadata["sources"]:
            if item["name"] in mapping:
                raw = (snapshot/"raw"/Path(item["path"].replace("\\", "/")).name).read_bytes()
                self.save(mapping[item["name"]], day, raw, item["url"])
        p = snapshot/"raw"/"institutional_nse.json"
        if p.exists():
            cats = {x["category"]: x for x in json.loads(p.read_text())}
            f, d = cats["FII/FPI"], cats["DII"]
            if not date_matches(f["date"], day) or not date_matches(d["date"], day):
                raise ValueError("Seed institutional date mismatch")
            self.put_institutions(day, *[n(x[k]) for x in (f, d) for k in ("buyValue", "sellValue")],
                                  "https://www.nseindia.com/api/fiidiiTradeReact [preserved snapshot]")
        self.db.commit()
        old = self.offline
        self.offline = True
        try:
            self.process_day(day)
        finally:
            self.offline = old
        return str(day)

    def export(self):
        reports = self.root/"reports"
        reports.mkdir(exist_ok=True)
        daily = [json.loads(x[0]) for x in self.db.execute("SELECT payload FROM exchange_daily ORDER BY day,exchange")]
        institutions = {x["day"]: dict(x) for x in self.db.execute("SELECT * FROM institutions")}
        grouped = {}
        for row in daily:
            grouped.setdefault(row["day"], {})[row["exchange"]] = row
        models = [combine(day, grouped.get(day, {}), institutions.get(day))
                  for day in sorted(set(grouped) | set(institutions))]
        write_csv(reports/"exchange_daily.csv", daily)
        write_csv(reports/"daily_model.csv", models)
        write_csv(reports/"institutions.csv", list(institutions.values()))
        attempts = [dict(x) for x in self.db.execute("SELECT day,kind,status,http_status,error,attempted_utc,url FROM attempts ORDER BY id")]
        write_csv(reports/"source_attempts.csv", attempts)
        run = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        status = {"generated_utc": utcnow(), "version": VERSION, "method": METHOD,
                  "exchange_days": len(daily), "dates_with_any_exchange": len(grouped),
                  "institutional_days": len(institutions), "cached_files": self.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0],
                  "bounded_three_exchange_model_days": sum(x["x_vwap_upper_crore"] is not None for x in models),
                  "last_exchange_date": max(grouped, default=None), "last_run": dict(run) if run else None}
        atomic_text(reports/"status.json", json.dumps(status, indent=2))
        def td(value):
            if value is None:
                return '<td class="missing">Unavailable</td>'
            if isinstance(value, (int, float)):
                return f'<td class="num">{value:,.2f}</td>'
            return '<td>'+html.escape(str(value))+'</td>'
        columns = [("day", "Trade date"), ("x_vwap_lower_crore", "Delivery lower ₹cr"),
                   ("x_vwap_upper_crore", "Delivery upper ₹cr"), ("rest_buy_lower_crore", "Rest buy lower ₹cr"),
                   ("rest_sell_lower_crore", "Rest sell lower ₹cr"), ("rest_net_crore", "Rest net ₹cr"),
                   ("data_status", "Data status")]
        table = ''.join('<tr>'+''.join(td(row.get(key)) for key, _ in columns)+'</tr>' for row in models[-250:][::-1])
        doc = f'''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="60"><title>Market delivery archive</title>
<style>body{{font:15px system-ui;background:#f5f7fa;color:#172d46;margin:32px}}main{{max-width:1450px;margin:auto}}h1{{font-size:26px}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:10px;border-bottom:1px solid #e1e7ef;text-align:left}}th{{background:#172d46;color:white}}.num{{text-align:right}}.missing{{color:#965b00}}.note{{background:#fff4d9;padding:14px;line-height:1.5}}pre{{white-space:pre-wrap}}a{{color:#1454b5}}</style></head><body><main>
<h1>Market delivery archive</h1><p>Updated {html.escape(status['generated_utc'])} UTC. {len(grouped):,} dates with exchange records; {len(institutions):,} dates with institutional values.</p>
<div class="note">Delivery money is a security-by-security VWAP estimate. Remaining buys/sells are conditional model outputs for everyone outside reported FII/DII, not observed retail trades. Institutional scope remains unverified. All reported CM instruments are included. Missing sources stay unavailable; no absent exchange is silently assigned zero.</div>
<p><a href="daily_model.csv">Daily model CSV</a> · <a href="exchange_daily.csv">Exchange totals CSV</a> · <a href="institutions.csv">Institutional CSV</a> · <a href="source_attempts.csv">Source coverage and errors</a> · <a href="status.json">Progress JSON</a></p>
<pre>{html.escape(json.dumps(status['last_run'], indent=2))}</pre><h2>Latest 250 available dates</h2><table><thead><tr>{''.join('<th>'+label+'</th>' for _,label in columns)}</tr></thead><tbody>{table}</tbody></table></main></body></html>'''
        atomic_text(reports/"status.html", doc)
        return status


def aggregate(exchange, reports):
    price_rows = reports.get(exchange.lower()+"_prices")
    delivery = reports.get(exchange.lower()+"_delivery")
    issues, items = [], []
    if exchange == "BSE" and delivery:
        # BSE delivery file itself contains dated daily turnover and quantity.
        pmap = {r["key"]: r for r in price_rows or []}
        for key, dr in delivery.items():
            if dr["q"] == 0:
                continue
            pr = pmap.get(key)
            close = pr["close"] if pr else None
            if pr and (pr["q"] != dr["q"] or abs(pr["v"]-dr["v"]) > 1.01):
                issues.append("BSE price/delivery totals disagree; close-price value unavailable for affected records")
                close = None
            items.append({**dr, "close": close, "derived": False})
        if price_rows and any(p["q"] > 0 and p["key"] not in delivery for p in price_rows):
            issues.append("Price records absent from BSE delivery file")
            for p in price_rows:
                if p["q"] > 0 and p["key"] not in delivery and not p.get("filename_date_only"):
                    items.append({**p, "dq": None, "derived": False})
    elif price_rows:
        if exchange == "BSE" and any(p.get("filename_date_only") for p in price_rows):
            return None  # Legacy price-only file cannot corroborate its date.
        for pr in price_rows:
            if pr["q"] == 0:
                continue
            dr = delivery.get(pr["key"]) if delivery else None
            dq, derived = None, False
            if dr:
                if dr["q"] == pr["q"]:
                    dq = dr["dq"]
                else:
                    issues.append("Traded quantity mismatch; affected delivery quantity left missing")
            elif exchange == "NSE" and pr["series"] in ("BE", "BZ"):
                dq, derived = pr["q"], True
            items.append({**pr, "dq": dq, "derived": derived})
            if exchange == "NSE" and pr["series"] in ("ST", "SZ") and dq is not None and dq != pr["q"]:
                issues.append("ST/SZ reported quantity below full TFT; source quantity retained")
        price_keys = {p["key"] for p in price_rows}
        if exchange == "NSE" and delivery and any(key not in price_keys for key in delivery):
            issues.append("NSE delivery records absent from price file; scope requires review")
    elif exchange == "MSEI" and reports.get("msei_activity") is not None:
        activity = reports["msei_activity"]
        zero, turnover = activity["verified_zero"], activity["v"]
        return {"scope": "all_reported_CM_instruments", "traded_records": 0 if zero else None,
                "turnover_inr": turnover, "traded_quantity": 0 if zero else None,
                "reported_delivery_quantity": 0 if zero else None, "derived_delivery_quantity": 0,
                "reported_delivery_records": 0, "derived_delivery_records": 0,
                "missing_delivery_records": 0 if zero else None,
                "delivery_vwap_known_inr": 0, "delivery_vwap_upper_inr": turnover,
                "missing_delivery_turnover_inr": turnover,
                "delivery_close_known_inr": 0 if zero else None,
                "delivery_close_upper_inr": 0 if zero else None,
                "published_delivery_value_inr": None, "delivery_quantity_coverage_by_turnover": None,
                "issues": ["Dated MSEI activity report explicitly confirms zero trading" if zero else
                           "MSEI aggregate-only activity turnover; security quantities unavailable; delivery range 0-100%"]}
    else:
        return None
    if not items:
        return None  # An empty file is not proof of exchange-wide zero activity.
    known = [r for r in items if r["dq"] is not None]
    missing = [r for r in items if r["dq"] is None]
    turnover = math.fsum(r["v"] for r in items)
    known_value = math.fsum(r["v"]*r["dq"]/r["q"] for r in known)
    unknown_value = math.fsum(r["v"] for r in missing)
    close_known = math.fsum(r["dq"]*r["close"] for r in known if r["close"] is not None)
    close_complete = all(r["close"] is not None for r in items)
    missing_close = math.fsum(r["q"]*r["close"] for r in missing) if close_complete else None
    if missing:
        issues.append("Delivery quantities missing; range uses 0-100% delivery for affected turnover")
    if any(r["derived"] for r in items):
        issues.append("NSE BE/BZ full delivery obligations derived; not observed completed settlement")
    if not close_complete:
        issues.append("Common closing-price valuation unavailable for some records")
    return {"scope": "all_reported_CM_instruments", "traded_records": len(items), "turnover_inr": turnover,
            "traded_quantity": sum(r["q"] for r in items),
            "reported_delivery_quantity": sum(r["dq"] for r in known if not r["derived"]),
            "derived_delivery_quantity": sum(r["dq"] for r in known if r["derived"]),
            "reported_delivery_records": sum(not r["derived"] for r in known),
            "derived_delivery_records": sum(r["derived"] for r in known), "missing_delivery_records": len(missing),
            "delivery_vwap_known_inr": known_value, "delivery_vwap_upper_inr": known_value+unknown_value,
            "missing_delivery_turnover_inr": unknown_value,
            "delivery_close_known_inr": close_known if close_complete else None,
            "delivery_close_upper_inr": close_known+missing_close if close_complete else None,
            "published_delivery_value_inr": math.fsum(r["official_dv"] for r in items) if all("official_dv" in r for r in items) else None,
            "delivery_quantity_coverage_by_turnover": (turnover-unknown_value)/turnover if turnover else None,
            "issues": sorted(set(issues))}


def combine(day, exchanges, inst):
    absent = [ex for ex in EXCHANGES if ex not in exchanges]
    lower = math.fsum(x["delivery_vwap_known_inr"] for x in exchanges.values())/CRORE if exchanges else None
    upper = math.fsum(x["delivery_vwap_upper_inr"] for x in exchanges.values())/CRORE if not absent else None
    close_ok = not absent and all(x["delivery_close_upper_inr"] is not None for x in exchanges.values())
    cl = math.fsum(x["delivery_close_known_inr"] for x in exchanges.values())/CRORE if close_ok else None
    cu = math.fsum(x["delivery_close_upper_inr"] for x in exchanges.values())/CRORE if close_ok else None
    buy = inst["fii_buy"]+inst["dii_buy"] if inst else None
    sell = inst["fii_sell"]+inst["dii_sell"] if inst else None
    result = {"day": day, "scope": "all_reported_CM_instruments", "x_vwap_lower_crore": lower,
              "x_vwap_upper_crore": upper, "x_close_lower_crore": cl, "x_close_upper_crore": cu,
              "institutional_buy_crore": buy, "institutional_sell_crore": sell,
              "rest_buy_lower_crore": lower-buy if lower is not None and buy is not None else None,
              "rest_buy_upper_crore": upper-buy if upper is not None and buy is not None else None,
              "rest_sell_lower_crore": lower-sell if lower is not None and sell is not None else None,
              "rest_sell_upper_crore": upper-sell if upper is not None and sell is not None else None,
              "rest_net_crore": sell-buy if inst else None,
              "missing_exchanges": ";".join(absent), "institutional_source": inst["source"] if inst else None,
              "comparability": "UNVERIFIED: model outputs, not observed retail categories",
              "data_status": "unbounded_missing_exchange" if absent else "missing_institutional_history" if not inst else "bounded_delivery_estimate"}
    total_turnover = math.fsum(x["turnover_inr"] for x in exchanges.values())/CRORE if not absent else None
    participation = (buy+sell)/2 if inst else None
    result.update(total_turnover_crore=total_turnover,
                  institutional_participation_crore=participation,
                  rest_participation_lower_crore=lower-participation if lower is not None and participation is not None else None,
                  rest_participation_upper_crore=upper-participation if upper is not None and participation is not None else None,
                  close_minus_vwap_lower_crore=cl-lower if cl is not None and lower is not None else None)
    if result["rest_buy_upper_crore"] is not None and min(result["rest_buy_upper_crore"], result["rest_sell_upper_crore"]) < 0:
        result["data_status"] = "incompatible_negative_remaining_side"
    return result


def atomic_text(path, content):
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    temp = path.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    temp.replace(path)


@contextlib.contextmanager
def single_writer(root):
    """An OS-released lock prevents a scheduled update racing a backfill."""
    root.mkdir(parents=True, exist_ok=True)
    stream = (root/"writer.lock").open("a+b")
    try:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt
            if stream.read(1) == b"":
                stream.write(b"0"); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise RuntimeError("Another pipeline writer is running; use status to monitor it") from exc
    try:
        yield
    finally:
        stream.close()


def run_range(pipeline, start, end, args, mode):
    if end > local_today():
        raise ValueError("End date is in the future. Forward updates collect published actuals only.")
    if start > end:
        raise ValueError("Start date must not exceed end date")
    run = pipeline.db.execute("INSERT INTO runs(started_utc,mode,start_day,end_day,status) VALUES(?,?,?,?,?)",
                              (utcnow(), mode, str(start), str(end), "running")).lastrowid
    pipeline.db.commit()
    count = 0
    try:
        day = start
        while day <= end:
            if not args.weekdays_only or day.weekday() < 5:
                result = pipeline.process_day(day, args.refresh, args.retry_missing, args.probe_all)
                count += 1
                pipeline.db.execute("UPDATE runs SET processed=? WHERE id=?", (count, run))
                pipeline.db.commit()
                print(json.dumps(result), flush=True)
                if count % args.report_every == 0:
                    pipeline.export()
            day += timedelta(days=1)
        pipeline.db.execute("UPDATE runs SET finished_utc=?,status='finished' WHERE id=?", (utcnow(), run))
    except (Exception, KeyboardInterrupt):
        pipeline.db.execute("UPDATE runs SET finished_utc=?,status='interrupted' WHERE id=?", (utcnow(), run))
        raise
    finally:
        pipeline.db.commit()
        pipeline.export()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=HOME/"data")
    parser.add_argument("--offline", action="store_true", help="Use cached files only; no network")
    parser.add_argument("--delay", type=float, default=.75, help="Minimum seconds between requests per host")
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--retries", type=int, default=2)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backfill", "update"):
        subp = sub.add_parser(name)
        subp.add_argument("--start", type=iso)
        subp.add_argument("--end", type=iso)
        subp.add_argument("--years", type=int, default=10)
        subp.add_argument("--lookback", type=int, default=10)
        subp.add_argument("--refresh", action="store_true", help="Re-fetch valid raw files; old SHA versions retained")
        subp.add_argument("--retry-missing", action="store_true", help="Ignore failed-request cooldowns")
        subp.add_argument("--weekdays-only", action="store_true", help="Faster but misses special weekend sessions")
        subp.add_argument("--probe-all", action="store_true", help="Probe BSE/MSEI even when NSE price file is unavailable")
        subp.add_argument("--report-every", type=int, default=20)
    sub.add_parser("status")
    sub.add_parser("report")
    seedp = sub.add_parser("seed")
    seedp.add_argument("snapshot", type=Path)
    imp = sub.add_parser("import-institutions")
    imp.add_argument("file", type=Path)
    imp.add_argument("--source", required=True, help="Actual source URL or provenance description")
    sub.add_parser("capture-latest")
    args = parser.parse_args(argv)
    if args.delay < 0 or args.timeout <= 0 or args.retries < 0:
        parser.error("Invalid network settings")
    if args.command in ("backfill", "update") and (args.report_every < 1 or args.years < 1 or args.lookback < 1):
        parser.error("Years, lookback and report-every must be positive")
    if args.command == "status":
        dbpath = args.data_dir.resolve()/"market.sqlite"
        if not dbpath.exists():
            print(json.dumps({"status": "not initialised", "data_dir": str(args.data_dir)}))
            return
        db = sqlite3.connect(dbpath.as_uri()+"?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            last = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            print(json.dumps({"last_run": dict(last) if last else None,
                "cached_files": db.execute("SELECT COUNT(*) FROM cache").fetchone()[0],
                "exchange_days": db.execute("SELECT COUNT(*) FROM exchange_daily").fetchone()[0],
                "institutional_days": db.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]}, indent=2))
        finally:
            db.close()
        return
    with single_writer(args.data_dir):
        p = Pipeline(args.data_dir, args.delay, args.timeout, args.retries, args.offline)
        try:
            if args.command in ("backfill", "update"):
                end = args.end or local_today()
                start = args.start or (years_ago(end, args.years) if args.command == "backfill" else end-timedelta(days=args.lookback-1))
                print(p.capture_institutions(), flush=True)
                run_range(p, start, end, args, args.command)
            elif args.command == "seed":
                print("Seeded", p.seed(args.snapshot))
            elif args.command == "capture-latest":
                print(p.capture_institutions())
            elif args.command == "import-institutions":
                records = list(csv.DictReader(args.file.open(encoding="utf-8-sig", newline="")))
                # One transaction: reject the entire import if any row is invalid.
                try:
                    for row in records:
                        p.put_institutions(iso(row["date"]), *[n(row[k]) for k in ("fii_buy", "fii_sell", "dii_buy", "dii_sell")], args.source)
                    p.db.commit()
                except Exception:
                    p.db.rollback(); raise
                print("Imported", len(records), "institutional dates")
            print(json.dumps(p.export(), indent=2))
        finally:
            p.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
