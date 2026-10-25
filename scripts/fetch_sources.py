#!/usr/bin/env python
"""Fetch the raw corpus and rebuild `data/manifest.csv` and `data/suppliers.csv`.

Sources (see docs/data/data-sourcing.md):
  cuad    CUAD v1 contracts, selected by contract type, label coverage and title pattern
  edgar   SEC EDGAR EX-10 amendments chained to their original agreements
  vendor  public vendor DPAs and SLAs
Synthetic documents come from `generate_synthetic.py`. Files already on disk are skipped, and the
manifest is always rebuilt from what is on disk.
"""

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import random
import re
import sys
import time
import zipfile
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from clausecheck.core import schema  # noqa: E402
from clausecheck.core.ids import doc_id  # noqa: E402

SEED = 42
DATA = ROOT / "data"
LOG_COLUMNS = ["ts", "source", "url", "status", "bytes", "sha256"]
CUAD_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip?download=1"
CUAD_MAX = 137
CUAD_TXT_SHARE = 0.2
EDGAR_MIN_INTERVAL = 0.12  # SEC allows 10 requests per second
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
VENDOR_USER_AGENT = "ClauseCheck-corpus-fetch (educational project; public documents only)"

PROCUREMENT_TYPES = {
    "supply",
    "manufacturing",
    "outsourcing",
    "service",
    "maintenance",
    "distributor",
    "hosting",
}
# Procurement label categories from data-sourcing.md 4.4 (metadata categories excluded)
PROCUREMENT_CATEGORIES = [
    "Renewal Term",
    "Notice Period To Terminate Renewal",
    "Expiration Date",
    "Cap On Liability",
    "Uncapped Liability",
    "Termination For Convenience",
    "Warranty Duration",
    "Liquidated Damages",
    "Price Restrictions",
    "Most Favored Nation",
    "Minimum Commitment",
    "Volume Restriction",
    "Insurance",
    "Audit Rights",
]
OLD_TITLE = re.compile(r"^.+_\d{2}_\d{2}_\d{4}-EX-")
NEW_TITLE = re.compile(r"^.+_\d{8}_[^_]+_EX-")

PROVIDER_ROLES = {
    "supplier",
    "seller",
    "manufacturer",
    "contractor",
    "provider",
    "vendor",
    "service provider",
    "servicer",
    "consultant",
    "licensor",
    "host",
    "developer",
    "repairer",
    "producer",
    "operator",
    "maintainer",
}
CUSTOMER_ROLES = {
    "buyer",
    "customer",
    "purchaser",
    "client",
    "distributor",
    "reseller",
    "licensee",
    "subscriber",
    "end-user",
    "user",
}
NOT_COMPANY = PROVIDER_ROLES | CUSTOMER_ROLES | {"company", "party", "parties", "agent", "partner"}

# Public vendor documents (data-sourcing.md 6.3). HTML only: the date rule needs readable text.
VENDOR_DOCS = [
    ("Google Cloud", "dpa", "https://cloud.google.com/terms/data-processing-addendum"),
    ("Google Cloud", "sla", "https://cloud.google.com/compute/sla"),
    ("Google Cloud", "sla", "https://cloud.google.com/storage/sla"),
    ("Google Cloud", "sla", "https://cloud.google.com/sql/sla"),
    ("Google Cloud", "sla", "https://cloud.google.com/kubernetes-engine/sla"),
    ("Google Cloud", "sla", "https://cloud.google.com/bigquery/sla"),
    ("Google Cloud", "sla", "https://cloud.google.com/run/sla"),
    ("Amazon Web Services", "sla", "https://aws.amazon.com/compute/sla/"),
    ("Amazon Web Services", "sla", "https://aws.amazon.com/s3/sla/"),
    ("Amazon Web Services", "sla", "https://aws.amazon.com/rds/sla/"),
    ("Amazon Web Services", "sla", "https://aws.amazon.com/dynamodb/sla/"),
    ("Amazon Web Services", "sla", "https://aws.amazon.com/lambda/sla/"),
    ("Amazon Web Services", "sla", "https://aws.amazon.com/eks/sla/"),
    ("Atlassian", "dpa", "https://www.atlassian.com/legal/data-processing-addendum"),
    ("Atlassian", "sla", "https://www.atlassian.com/legal/sla"),
    ("Stripe", "dpa", "https://stripe.com/legal/dpa"),
    ("Twilio", "dpa", "https://www.twilio.com/en-us/legal/data-protection-addendum"),
    ("HubSpot", "dpa", "https://legal.hubspot.com/dpa"),
]
VENDOR_LICENCE = "publicly published, (c) {vendor}; not redistributed"

EDGAR_QUERIES = [
    '"amendment to supply agreement"',
    '"amendment no. 1" "supply agreement"',
    '"amendment to manufacturing agreement"',
    '"amendment to master services agreement"',
]

_MONTH_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
MONTHS = {m: i for i, m in enumerate(_MONTH_NAMES, 1)}
MONTHS.update({m[:3]: i for i, m in enumerate(_MONTH_NAMES, 1)})
MONTHS["sept"] = 9
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:\s?(?:st|nd|rd|th))?\s*,?\s+(\d{{4}})\b", re.I),
    re.compile(
        rf"\b(\d{{1,2}})(?:\s?(?:st|nd|rd|th))?\s+(?:day\s+of\s+)?({_MONTH})\.?\s*,?\s+(\d{{4}})\b",
        re.I,
    ),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b"),
]


# ---------------------------------------------------------------------------------------------
# Small helpers (used by the tests)
# ---------------------------------------------------------------------------------------------


def edgar_headers(user_agent: str) -> dict[str, str]:
    """Return SEC-compliant request headers; the user agent must contain a contact email."""
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "EDGAR_USER_AGENT must include a contact email, e.g. 'Name me@example.com'"
        )
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}


def needs_download(path: Path) -> bool:
    """Return True if the file is missing or empty."""
    return not path.exists() or path.stat().st_size == 0


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def append_fetch_log(log_path: Path, row: dict) -> None:
    """Append one row to the fetch log, writing the header only when the file is created."""
    new = not log_path.exists() or log_path.stat().st_size == 0
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LOG_COLUMNS})


# ---------------------------------------------------------------------------------------------
# Dates and text
# ---------------------------------------------------------------------------------------------


def parse_date(text: str) -> str | None:
    """Return the first calendar date found in `text` as YYYY-MM-DD, or None."""
    best: tuple[int, str] | None = None
    for i, pattern in enumerate(DATE_PATTERNS):
        m = pattern.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if i == 0:
                day = dt.date(int(g[2]), MONTHS[g[0].lower()], int(g[1]))
            elif i == 1:
                day = dt.date(int(g[2]), MONTHS[g[1].lower()], int(g[0]))
            elif i == 2:
                day = dt.date(int(g[0]), int(g[1]), int(g[2]))
            else:  # US month/day/year
                year = int(g[2])
                year = year if len(g[2]) == 4 else (2000 + year if year <= 30 else 1900 + year)
                day = dt.date(year, int(g[0]), int(g[1]))
        except (ValueError, KeyError):
            continue
        if best is None or m.start() < best[0]:
            best = (m.start(), day.isoformat())
    return best[1] if best else None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_text(raw: bytes) -> tuple[str, str]:
    """Return (title, visible text) of an HTML document."""
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="ignore"))
    text = re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts)))
    return re.sub(r"\s+", " ", html.unescape(parser.title)).strip(), text


VERSION_LABEL = re.compile(
    r"(?:last\s+(?:updated|modified|revised)|effective\s+(?:starting|as\s+of|date|from)|updated)"
    r"\W{0,6}",
    re.I,
)


def vendor_effective_date(text: str) -> str | None:
    """Read a vendor document's version date from labels like 'Last Updated: <date>'."""
    for m in VERSION_LABEL.finditer(text):
        found = parse_date(text[m.end() : m.end() + 40])
        if found and text[m.end() : m.end() + 40].strip()[:1].isalnum():
            return found
    return None


# ---------------------------------------------------------------------------------------------
# Configuration and HTTP
# ---------------------------------------------------------------------------------------------


def load_config() -> tuple[str, Path]:
    """Return (edgar user agent, raw data dir) from settings, or the environment if unset."""
    try:
        from clausecheck.core.config import get_settings

        s = get_settings()
        user_agent, raw = s.edgar_user_agent, s.raw_data_dir
    except Exception:  # missing API keys must not block corpus building
        user_agent = os.environ.get("EDGAR_USER_AGENT", "")
        raw = Path(os.environ.get("RAW_DATA_DIR", "data/raw"))
    return user_agent, raw if raw.is_absolute() else ROOT / raw


class Fetcher:
    """HTTP helper that logs every download and throttles EDGAR requests."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.session = requests.Session()
        self._last_edgar = 0.0

    def get(self, source: str, url: str, headers: dict, dest: Path | None = None, **kw):
        """GET `url`, log it, and return the response (or None on a network error)."""
        if source == "edgar":
            wait = EDGAR_MIN_INTERVAL - (time.monotonic() - self._last_edgar)
            if wait > 0:
                time.sleep(wait)
            self._last_edgar = time.monotonic()
        try:
            response = self.session.get(
                url, headers=headers, timeout=120, stream=dest is not None, **kw
            )
        except requests.RequestException as exc:
            print(f"  ! {url}: {type(exc).__name__}", file=sys.stderr)
            return None
        size, digest = len(response.content) if dest is None else 0, ""
        if response.status_code == 200 and dest is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for block in response.iter_content(1 << 20):
                    f.write(block)
            size, digest = dest.stat().st_size, sha256_file(dest)
        elif response.status_code == 200:
            digest = hashlib.sha256(response.content).hexdigest()
        append_fetch_log(
            self.log_path,
            {
                "ts": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": source,
                "url": url,
                "status": response.status_code,
                "bytes": size,
                "sha256": digest,
            },
        )
        return response


# ---------------------------------------------------------------------------------------------
# CUAD
# ---------------------------------------------------------------------------------------------


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" \t\r\n,;:.\"'“”‘’()[]")
    return re.sub(r"^(?:the)\s+", "", name, flags=re.I)


def _is_company(name: str) -> bool:
    low = name.lower()
    if not 2 < len(name) <= 80 or low in NOT_COMPANY or not name[0].isalpha():
        return False
    if re.search(r"hereinafter|referred|parties|\bparty\b|agreement|\bshall\b|\bmay\b", low):
        return False
    return name[0].isupper() or name.isupper()


_QUOTED = re.compile(r"[\"“”'‘’]\s*(?:the\s+)?([A-Za-z][A-Za-z\- ]{2,30}?)\s*[\"“”'’]")


def _roles_of(name: str, context: str) -> set[str]:
    """Return the party roles defined right after each mention of `name` in the preamble."""
    roles = set()
    for m in re.finditer(re.escape(name), context[:8000], re.I):
        for d in _QUOTED.finditer(context[m.end() : m.end() + 250]):
            term = d.group(1).strip().lower()
            if term in PROVIDER_ROLES | CUSTOMER_ROLES:
                roles.add(term)
                break
    return roles


_PROVIDER_VERBS = r"(?:supply|provide|manufacture|deliver|sell|perform|host|maintain|service)"
_CUSTOMER_VERBS = r"(?:purchase|buy|pay|order)"


def _verb_roles(name: str, context: str) -> set[str]:
    """Infer a role from 'X shall supply ...' or 'X shall purchase ...' style sentences."""
    esc = re.escape(name)
    roles = set()
    if re.search(
        rf"{esc}\W+(?:shall|will|agrees to|hereby agrees to)\s+{_PROVIDER_VERBS}", context, re.I
    ):
        roles.add("supplier")
    if re.search(rf"{esc}\W+(?:shall|will|agrees to)\s+{_CUSTOMER_VERBS}", context, re.I):
        roles.add("buyer")
    return roles


def _group_names(names: list[str]) -> list[list[str]]:
    """Group short forms with the full name they start with ('Accuray' with 'Accuray Inc')."""
    groups: list[list[str]] = []
    for name in sorted(names, key=lambda n: -len(schema.normalise_name(n))):
        key = schema.normalise_name(name)
        for group in groups:
            full = schema.normalise_name(group[0])
            if full == key or full.startswith(key + " "):
                group.append(name)
                break
        else:
            groups.append([name])
    return groups


def find_supplier(parties: list[str], context: str) -> tuple[str, list[str]] | None:
    """Return (supplier display name, aliases) for a contract, or None if the roles are unclear."""
    names: list[str] = []
    for raw in parties:
        cleaned = _clean_name(raw)
        if _is_company(cleaned) and cleaned.lower() not in {n.lower() for n in names}:
            names.append(cleaned)
    providers, customers, others = [], [], []
    for group in _group_names(names):
        roles = set()
        for name in group:
            roles |= _roles_of(name, context) | _verb_roles(name, context)
        is_provider = bool(roles & (PROVIDER_ROLES | {"supplier"}))
        is_customer = bool(roles & (CUSTOMER_ROLES | {"buyer"}))
        if is_provider and not is_customer:
            providers.append(group)
        elif is_customer and not is_provider:
            customers.append(group)
        else:
            others.append(group)
    if len(providers) == 1:
        chosen = providers[0]
    elif not providers and customers and len(others) == 1:
        chosen = others[0]
    else:
        return None
    return chosen[0], chosen[1:]


def parse_title(title: str) -> str | None:
    """Return the filer segment of a CUAD title if it matches one of the two file patterns."""
    if OLD_TITLE.match(title):
        return re.split(r"_\d{2}_\d{2}_\d{4}-EX-", title)[0]
    if NEW_TITLE.match(title):
        return title.split("_")[0]
    return None


def _labels(contract: dict) -> dict[str, list[str]]:
    out = {}
    for qa in contract["paragraphs"][0]["qas"]:
        out[qa["id"].split("__", 1)[1]] = [a["text"] for a in qa["answers"]]
    return out


def _folder_type(folder: str) -> str:
    return folder.lower().replace("_", " ").strip()


def select_cuad(contracts: list[dict], folders: dict[str, str], seed: int = SEED) -> list[dict]:
    """Apply the data-sourcing.md 4.3 filters and return one entry per selected contract."""
    selected = []
    for c in sorted(contracts, key=lambda c: c["title"]):
        title = c["title"]
        kind = _folder_type(folders.get(title, ""))
        title_types = {t for t in PROCUREMENT_TYPES if t in title.lower()}
        if kind not in PROCUREMENT_TYPES and not title_types:
            continue
        if re.search(r"amend", title, re.I) or parse_title(title) is None:
            continue
        labels = _labels(c)
        if sum(bool(labels.get(k)) for k in PROCUREMENT_CATEGORIES) < 3:
            continue
        context = c["paragraphs"][0]["context"]
        found = find_supplier(labels.get("Parties", []), context)
        if found is None:
            continue
        date = None
        for text in (*labels.get("Effective Date", []), *labels.get("Agreement Date", [])):
            date = date or parse_date(text)
        date = date or parse_date(context[:3000])
        if date is None:
            continue
        name, aliases = found
        selected.append(
            {
                "title": title,
                "folder": folders.get(title, ""),
                "supplier_name": name,
                "aliases": aliases,
                "effective_date": date,
            }
        )
    rng = random.Random(seed)
    if len(selected) > CUAD_MAX:
        selected = sorted(rng.sample(selected, CUAD_MAX), key=lambda e: e["title"])
    as_text = {e["title"] for e in rng.sample(selected, int(len(selected) * CUAD_TXT_SHARE))}
    for e in selected:
        e["format"] = "txt" if e["title"] in as_text else "pdf"
    return selected


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name)


def fetch_cuad(fetcher: Fetcher, raw_dir: Path, limit: int | None) -> list[dict]:
    """Download CUAD, copy the selected contracts to `raw_dir/cuad` and return their entries."""
    cache = raw_dir / ".cache" / "CUAD_v1.zip"
    if needs_download(cache):
        print("downloading CUAD_v1.zip (about 100 MB)")
        resp = fetcher.get("cuad", CUAD_URL, {}, dest=cache)
        if resp is None or resp.status_code != 200:
            print("  ! CUAD download failed", file=sys.stderr)
            return []
    with zipfile.ZipFile(cache) as z:
        contracts = json.loads(z.read("CUAD_v1/CUAD_v1.json"))["data"]
        pdfs = {}
        for name in z.namelist():
            parts = name.split("/")
            if name.lower().endswith(".pdf") and len(parts) >= 5:
                pdfs[parts[-1].rsplit(".", 1)[0]] = name
        folders = {t: n.split("/")[3] for t, n in pdfs.items()}
        selected = select_cuad(contracts, folders)
        by_title = {c["title"]: c for c in contracts}
        if limit:
            selected = selected[:limit]
        out = raw_dir / "cuad"
        entries = []
        for e in selected:
            title = e["title"]
            context = by_title[title]["paragraphs"][0]["context"]
            text_path = out / "json_text" / f"{_safe(title)}.txt"
            if needs_download(text_path):
                text_path.parent.mkdir(parents=True, exist_ok=True)
                text_path.write_text(context, encoding="utf-8", newline="\n")
            ext = e["format"]
            dest = out / f"{_safe(title)}.{ext}"
            if needs_download(dest):
                if ext == "pdf" and title in pdfs:
                    dest.write_bytes(z.read(pdfs[title]))
                else:
                    dest.write_text(context, encoding="utf-8", newline="\n")
            entries.append(
                {
                    "source": "cuad",
                    "doc_type": "contract",
                    "format": ext if dest.exists() else "txt",
                    "path": dest.relative_to(ROOT).as_posix(),
                    "title": title,
                    "effective_date": e["effective_date"],
                    "parent_doc_id": "",
                    "licence": "CC BY 4.0",
                    "url": "https://zenodo.org/records/4595826",
                    "supplier_name": e["supplier_name"],
                    "aliases": e["aliases"],
                }
            )
    print(f"cuad: {len(entries)} contracts")
    return entries


# ---------------------------------------------------------------------------------------------
# Vendor DPAs and SLAs
# ---------------------------------------------------------------------------------------------


def fetch_vendor(fetcher: Fetcher, raw_dir: Path, limit: int | None) -> list[dict]:
    """Download the vendor documents in VENDOR_DOCS and return entries for those with a date."""
    out = raw_dir / "vendor"
    index_path = out / "_index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    docs = VENDOR_DOCS[:limit] if limit else VENDOR_DOCS
    for vendor, kind, url in docs:
        key = re.sub(r"\W+", "-", url.split("://", 1)[1]).strip("-").lower()
        dest = out / f"{key}.html"
        if needs_download(dest):
            resp = fetcher.get("vendor", url, {"User-Agent": VENDOR_USER_AGENT}, dest=dest)
            if resp is None or resp.status_code != 200:
                dest.unlink(missing_ok=True)
                continue
        elif key in index:
            continue
        title, text = html_text(dest.read_bytes())
        date = vendor_effective_date(text)
        if date is None:
            print(f"  - excluded (no version date): {url}")
            dest.unlink()
            continue
        index[key] = {
            "source": "vendor",
            "doc_type": kind,
            "format": "html",
            "path": dest.relative_to(ROOT).as_posix(),
            "title": f"{vendor} {kind.upper()}: {title}"[:200],
            "effective_date": date,
            "parent_doc_id": "",
            "licence": VENDOR_LICENCE.format(vendor=vendor),
            "url": url,
            "supplier_name": vendor,
            "aliases": [],
        }
    out.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True))
    entries = [e for e in index.values() if (ROOT / e["path"]).exists()]
    print(f"vendor: {len(entries)} documents")
    return entries


# ---------------------------------------------------------------------------------------------
# SEC EDGAR amendments
# ---------------------------------------------------------------------------------------------

ORDINALS = {
    w: i
    for i, w in enumerate(
        [
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "sixth",
            "seventh",
            "eighth",
            "ninth",
            "tenth",
        ],
        1,
    )
}


def amendment_number(title: str) -> int:
    """Return the amendment number in a title ('Fifth Amendment', 'Amendment No. 2'), default 1."""
    m = re.search(r"amendment\s+no\.?\s*(\d+)", title, re.I)
    if m:
        return int(m.group(1))
    for word, n in ORDINALS.items():
        if re.search(rf"\b{word}\s+amendment", title, re.I):
            return n
    return 1


def amendment_effective_date(text: str) -> str | None:
    """Calendar effective date from the text, else the signature date, else None (DV-9)."""
    m = re.search(r"effective\s+(?:as\s+of\s+|on\s+)?", text[:8000], re.I)
    if m:
        found = parse_date(text[m.end() : m.end() + 40])
        if found:
            return found
    return parse_date(text[-2500:])


def _edgar_hits(fetcher: Fetcher, headers: dict, query: str, limit: int) -> list[dict]:
    resp = fetcher.get(
        "edgar", EDGAR_SEARCH, headers, params={"q": query, "forms": "8-K,10-K,10-Q"}
    )
    if resp is None or resp.status_code != 200:
        return []
    hits = []
    for hit in resp.json().get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        if not str(src.get("file_type", "")).upper().startswith("EX-10"):
            continue
        accession, _, filename = hit["_id"].partition(":")
        cik = int(src["ciks"][0])
        hits.append(
            {
                "company": re.sub(r"\s*\(CIK.*$", "", src.get("display_names", [""])[0]),
                "url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{accession.replace('-', '')}/{filename}"
                ),
                "filename": filename,
                "accession": accession,
            }
        )
        if len(hits) >= limit:
            break
    return hits


def fetch_edgar(
    fetcher: Fetcher, raw_dir: Path, user_agent: str, cuad: list[dict], limit: int | None
) -> list[dict]:
    """Find amendments whose original is in the CUAD selection, download both, return entries.

    Only pairs whose original is already in the corpus are kept (data-sourcing.md 5.4).
    """
    headers = edgar_headers(user_agent)
    out = raw_dir / "edgar"
    index_path = out / "_index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    originals = {schema.normalise_name(e["supplier_name"]): e for e in cuad}
    seen = {e["url"] for e in index.values()}
    for query in EDGAR_QUERIES:
        for hit in _edgar_hits(fetcher, headers, query, limit or 100):
            if hit["url"] in seen:
                continue
            parent = originals.get(schema.normalise_name(hit["company"]))
            if parent is None:
                continue
            dest = out / f"{hit['accession']}_{_safe(hit['filename'])}"
            resp = fetcher.get("edgar", hit["url"], headers, dest=dest)
            if resp is None or resp.status_code != 200:
                continue
            title, text = html_text(dest.read_bytes())
            if not re.search(r"amendment|modification", (title + " " + text[:400]), re.I):
                dest.unlink()
                continue
            date = amendment_effective_date(text)
            if date is None:
                dest.unlink()
                continue
            heading = text[:200].strip() or title
            parent_id = doc_id("cuad", parent["title"])
            index[hit["accession"]] = {
                "source": "edgar",
                "doc_type": "amendment",
                "format": "html" if dest.suffix.lower() in {".htm", ".html"} else "txt",
                "path": dest.relative_to(ROOT).as_posix(),
                "title": f"{hit['company']} amendment {amendment_number(heading)}: {heading[:80]}",
                "effective_date": date,
                "parent_doc_id": parent_id,
                "licence": "public SEC filing",
                "url": hit["url"],
                "supplier_name": parent["supplier_name"],
                "aliases": sorted({hit["company"]} - {parent["supplier_name"]}),
            }
            seen.add(hit["url"])
    out.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True))
    entries = [e for e in index.values() if (ROOT / e["path"]).exists()]
    print(f"edgar: {len(entries)} amendments")
    return entries


# ---------------------------------------------------------------------------------------------
# Manifest and suppliers
# ---------------------------------------------------------------------------------------------


def build_suppliers(entries: list[dict]) -> list[dict]:
    """Merge supplier names and aliases into suppliers.csv rows with unique names."""
    names: dict[str, dict] = {}
    for e in entries:
        sid = schema.supplier_id_from_name(e["supplier_name"])
        s = names.setdefault(sid, {"display_name": e["supplier_name"], "aliases": set()})
        s["aliases"].update(e["aliases"])
        s["aliases"].add(schema.normalise_name(e["supplier_name"]).title())
    claimed: dict[str, str] = {}
    for sid in sorted(names):
        claimed.setdefault(names[sid]["display_name"].strip().lower(), sid)
    rows = []
    for sid in sorted(names):
        s = names[sid]
        aliases = []
        for alias in sorted(s["aliases"]):
            key = alias.strip().lower()
            if key == s["display_name"].strip().lower() or "|" in alias:
                continue
            if claimed.setdefault(key, sid) == sid:
                aliases.append(alias)
        rows.append(
            {"supplier_id": sid, "display_name": s["display_name"], "aliases": "|".join(aliases)}
        )
    return rows


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Write rows with a fixed column order and LF line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rebuild_manifest(entries: list[dict], seed: int = SEED) -> tuple[int, int]:
    """Rebuild manifest.csv and suppliers.csv from the entries plus the synthetic documents."""
    import generate_synthetic as gen

    suppliers = build_suppliers(entries)
    key_names = gen.pick_key_suppliers([s["display_name"] for s in suppliers], seed)
    write_csv(DATA / "suppliers.csv", schema.SUPPLIER_COLUMNS, suppliers)

    rows = []
    for e in entries:
        path = ROOT / e["path"]
        if not path.exists():
            continue
        rows.append(
            {
                "doc_id": doc_id(e["source"], e["title"]),
                "supplier_id": schema.supplier_id_from_name(e["supplier_name"]),
                "source": e["source"],
                "doc_type": e["doc_type"],
                "format": e["format"],
                "path": e["path"],
                "title": e["title"],
                "effective_date": e["effective_date"],
                "parent_doc_id": e["parent_doc_id"],
                "licence": e["licence"],
                "url": e["url"],
                "sha256": sha256_file(path),
                "is_synthetic": "false",
            }
        )
    synthetic = gen.generate(seed, ROOT / "data" / "raw" / "synthetic", key_names)
    rows += synthetic
    rows.sort(key=lambda r: (r["source"], r["doc_id"]))
    write_csv(DATA / "manifest.csv", schema.MANIFEST_COLUMNS, rows)
    return len(rows), len(suppliers)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["cuad", "edgar", "vendor"])
    parser.add_argument("--limit", type=int, help="maximum documents per source (quick check)")
    args = parser.parse_args(argv)

    user_agent, raw_dir = load_config()
    fetcher = Fetcher(DATA / "fetch_log.csv")
    want = {args.only} if args.only else {"cuad", "edgar", "vendor"}

    entries: list[dict] = []
    cuad: list[dict] = []
    # EDGAR needs the CUAD selection to find originals, so CUAD is always read.
    if "cuad" in want or "edgar" in want:
        cuad = fetch_cuad(fetcher, raw_dir, args.limit)
        entries += cuad
    if "edgar" in want:
        try:
            edgar_headers(user_agent)
        except ValueError as exc:
            if args.only == "edgar":
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"skipping EDGAR: {exc}", file=sys.stderr)
        else:
            entries += fetch_edgar(fetcher, raw_dir, user_agent, cuad, args.limit)
    if "vendor" in want:
        entries += fetch_vendor(fetcher, raw_dir, args.limit)

    # Sources not fetched in this run are still on disk: keep their rows.
    for source in ("edgar", "vendor"):
        index_path = raw_dir / source / "_index.json"
        if source not in want and index_path.exists():
            entries += [
                e
                for e in json.loads(index_path.read_text()).values()
                if (ROOT / e["path"]).exists()
            ]
    if "cuad" not in want:
        entries += fetch_cuad(fetcher, raw_dir, None)

    total, suppliers = rebuild_manifest(entries)
    counts = defaultdict(int)
    for e in entries:
        counts[e["source"]] += 1
    print(
        f"manifest: {total} documents, {suppliers} suppliers; "
        f"real documents per source: {dict(counts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
