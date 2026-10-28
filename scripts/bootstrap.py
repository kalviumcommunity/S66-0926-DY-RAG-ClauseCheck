#!/usr/bin/env python
"""Make sure an index exists before the API starts: reuse it, restore an archive, or build it."""

import subprocess
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clausecheck.core.config import Settings, get_settings  # noqa: E402
from clausecheck.store import sqlite as db  # noqa: E402


def _has_chunks(path: Path) -> bool:
    if not path.exists():
        return False
    conn = db.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
    except Exception:  # file exists but has no schema yet
        return False
    finally:
        conn.close()


def download_archive(url: str, index_dir: Path) -> None:
    """Download a `.tar.gz` of the index and extract it into `index_dir`."""
    index_dir.mkdir(parents=True, exist_ok=True)
    archive, _ = urllib.request.urlretrieve(url)
    with tarfile.open(archive) as tar:
        tar.extractall(index_dir, filter="data")


def build_index() -> None:
    """Fetch the corpus, generate the synthetic documents and ingest everything."""
    for cmd in (
        [sys.executable, "scripts/fetch_sources.py"],
        [sys.executable, "scripts/generate_synthetic.py", "--seed", "42"],
        [sys.executable, "-m", "clausecheck.ingest", "--rebuild"],
    ):
        subprocess.run(cmd, cwd=ROOT, check=True)


def ensure_index(
    settings: Settings,
    build_fn: Callable[[], None] | None = None,
    download_fn: Callable[[str, Path], None] | None = None,
) -> str:
    """Return `"present"`, `"restored"` or `"built"` depending on how the index was obtained."""
    if _has_chunks(Path(settings.sqlite_path)):
        return "present"
    if settings.index_archive_url:
        (download_fn or download_archive)(settings.index_archive_url, Path(settings.index_dir))
        return "restored"
    (build_fn or build_index)()
    return "built"


def pack(index_dir: Path, out_path: Path) -> Path:
    """Create the `.tar.gz` that `INDEX_ARCHIVE_URL` points to."""
    index_dir, out_path = Path(index_dir), Path(out_path)
    with tarfile.open(out_path, "w:gz") as tar:
        for item in sorted(index_dir.iterdir()):
            tar.add(item, arcname=item.name)
    return out_path


def main() -> int:
    """Command line entry point."""
    print(f"index: {ensure_index(get_settings())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
