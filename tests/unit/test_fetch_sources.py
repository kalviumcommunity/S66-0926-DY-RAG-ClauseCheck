import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fs():
    spec = importlib.util.spec_from_file_location("fetch_sources", ROOT / "scripts/fetch_sources.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_edgar_headers_require_contact_email(fs):
    assert fs.edgar_headers("Diya diya@example.com")["User-Agent"] == "Diya diya@example.com"
    with pytest.raises(ValueError):
        fs.edgar_headers("")
    with pytest.raises(ValueError):
        fs.edgar_headers("no-email-here")


def test_needs_download(fs, tmp_path):
    p = tmp_path / "x.pdf"
    assert fs.needs_download(p)
    p.write_bytes(b"")
    assert fs.needs_download(p)
    p.write_bytes(b"%PDF")
    assert not fs.needs_download(p)


def test_sha256_file(fs, tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"abc")
    assert fs.sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_fetch_log_header_written_once(fs, tmp_path):
    log = tmp_path / "fetch_log.csv"
    row = {"ts": "t", "source": "cuad", "url": "u", "status": 200, "bytes": 3, "sha256": "s"}
    fs.append_fetch_log(log, row)
    fs.append_fetch_log(log, row)
    with log.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert log.read_text().count("ts,source,url,status,bytes,sha256") == 1
