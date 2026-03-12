"""
Validate file metadata from RDSO crawl output.

Reads all file entries from either:
  - A catalog_hierarchy.json (has everything inline), or
  - A storage root with per-file *.meta.json scattered across subfolders

Checks:
  1. Uniqueness of etag and content_length across all files
  2. Sends HEAD requests to every source_url and compares the live
     etag / content-length against what was recorded in metadata
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("validate_files")

# ── helpers ──────────────────────────────────────────────────────────────────

FileRecord = dict[str, Any]


def extract_files_from_hierarchy(path: Path) -> list[FileRecord]:
    """Walk catalog_hierarchy.json and pull out every file-level record."""
    data = json.loads(path.read_text(encoding="utf-8"))
    files: list[FileRecord] = []

    for cat in data.get("categories", []):
        subheads = (
            cat.get("subheads", [])
            or cat.get("subheads_in_this_category", [])
        )
        for sh in subheads:
            drawings = (
                sh.get("drawings", [])
                or sh.get("drawings_in_this_subhead", [])
            )
            for drw in drawings:
                downloaded = (
                    drw.get("files", [])
                    or drw.get("downloaded_files", [])
                )
                for f in downloaded:
                    rec = _normalize(f, drw)
                    if rec:
                        files.append(rec)
    return files


def extract_files_from_meta_jsons(root: Path) -> list[FileRecord]:
    """Recursively find *.meta.json files and extract file records."""
    files: list[FileRecord] = []
    for meta_path in root.rglob("*.meta.json"):
        if meta_path.name == "__meta__.json":
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rec = _normalize(data)
        if rec:
            files.append(rec)
    return files


def _normalize(raw: dict, parent_drawing: dict | None = None) -> FileRecord | None:
    """Extract a uniform record from either schema v1 or v2."""
    url = (
        raw.get("source_url")
        or (raw.get("source") or {}).get("file_url")
    )
    if not url:
        return None

    # etag / content_length can be at top-level or under remote_headers
    headers = raw.get("remote_headers") or {}
    etag = raw.get("etag") or headers.get("etag")
    cl = raw.get("content_length") or headers.get("content_length")
    sha = raw.get("sha256") or (raw.get("integrity") or {}).get("sha256")
    size = raw.get("size") or (raw.get("integrity") or {}).get("size_bytes")

    drawing_id = raw.get("drawing_id") or (
        (parent_drawing or {}).get("identity") or parent_drawing or {}
    ).get("drawing_id") or (parent_drawing or {}).get("id")

    storage = raw.get("storage") or {}
    stored_relative_path = (
        raw.get("stored_relative_path")
        or storage.get("relative_path_from_root")
        or storage.get("relative_path")
    )
    stored_relative_path_from_drawing = (
        raw.get("stored_relative_path_from_drawing")
        or storage.get("relative_path_from_drawing")
    )
    drawing_relative_path = (
        raw.get("drawing_relative_path")
        or storage.get("drawing_relative_path")
        or (parent_drawing or {}).get("relative_path")
        or ((parent_drawing or {}).get("storage") or {}).get("relative_path")
    )

    return {
        "source_url": url,
        "etag": etag,
        "content_length": int(cl) if cl is not None else None,
        "sha256": sha,
        "size": int(size) if size is not None else None,
        "drawing_id": drawing_id,
        "stored_file": raw.get("stored_file")
            or storage.get("file_name"),
        "stored_relative_path": stored_relative_path,
        "stored_relative_path_from_drawing": stored_relative_path_from_drawing,
        "drawing_relative_path": drawing_relative_path,
    }


# ── uniqueness analysis ─────────────────────────────────────────────────────

def check_uniqueness(files: list[FileRecord]) -> dict:
    etag_counter: Counter[str] = Counter()
    cl_counter: Counter[int] = Counter()
    url_counter: Counter[str] = Counter()

    etag_map: dict[str, list[str]] = defaultdict(list)
    cl_map: dict[int, list[str]] = defaultdict(list)

    for f in files:
        url = f["source_url"]
        url_counter[url] += 1

        if f["etag"]:
            etag_counter[f["etag"]] += 1
            etag_map[f["etag"]].append(url)
        if f["content_length"] is not None:
            cl_counter[f["content_length"]] += 1
            cl_map[f["content_length"]].append(url)

    dup_etags = {k: v for k, v in etag_map.items() if len(v) > 1}
    dup_cls = {
        str(k): v for k, v in cl_map.items() if len(v) > 1
    }
    dup_urls = {k: v for k, v in url_counter.items() if v > 1}

    return {
        "total_files": len(files),
        "unique_urls": len(url_counter),
        "duplicate_urls": dup_urls,
        "unique_etags": len(etag_counter),
        "duplicate_etags": dup_etags,
        "null_etags": sum(1 for f in files if not f["etag"]),
        "unique_content_lengths": len(cl_counter),
        "duplicate_content_lengths": dup_cls,
        "null_content_lengths": sum(
            1 for f in files if f["content_length"] is None
        ),
    }


def resolve_disk_path(rec: FileRecord, storage_root: Path) -> Path | None:
    stored_relative_path = rec.get("stored_relative_path")
    if stored_relative_path:
        return storage_root / Path(stored_relative_path)

    drawing_relative_path = rec.get("drawing_relative_path")
    stored_relative_path_from_drawing = rec.get("stored_relative_path_from_drawing")
    stored_file = rec.get("stored_file")

    if drawing_relative_path and stored_relative_path_from_drawing:
        return storage_root / Path(drawing_relative_path) / Path(stored_relative_path_from_drawing)
    if drawing_relative_path and stored_file:
        return storage_root / Path(drawing_relative_path) / stored_file
    return None


def check_disk_consistency(files: list[FileRecord], storage_root: Path) -> dict[str, Any]:
    unique_by_url: dict[str, FileRecord] = {}
    for rec in files:
        unique_by_url.setdefault(rec["source_url"], rec)

    missing_path_metadata: list[dict[str, Any]] = []
    missing_on_disk: list[dict[str, Any]] = []
    ok = 0

    for rec in unique_by_url.values():
        disk_path = resolve_disk_path(rec, storage_root)
        if disk_path is None:
            missing_path_metadata.append({
                "source_url": rec["source_url"],
                "stored_file": rec.get("stored_file"),
                "drawing_relative_path": rec.get("drawing_relative_path"),
                "stored_relative_path": rec.get("stored_relative_path"),
            })
            continue

        if not disk_path.exists():
            missing_on_disk.append({
                "source_url": rec["source_url"],
                "resolved_disk_path": str(disk_path),
            })
            continue

        ok += 1

    return {
        "storage_root": str(storage_root),
        "checked_unique_urls": len(unique_by_url),
        "ok": ok,
        "missing_path_metadata": len(missing_path_metadata),
        "missing_on_disk": len(missing_on_disk),
        "missing_path_metadata_details": missing_path_metadata,
        "missing_on_disk_details": missing_on_disk,
    }


# ── live HEAD validation ────────────────────────────────────────────────────

def _build_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5,
                    status_forcelist=[500, 502, 503, 504])
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def _head_check(session: requests.Session, rec: FileRecord,
                timeout: int) -> dict:
    url = rec["source_url"]
    result: dict[str, Any] = {"source_url": url, "status": None,
                               "errors": [], "warnings": []}
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        result["status"] = resp.status_code

        if resp.status_code != 200:
            result["errors"].append(f"HTTP {resp.status_code}")
            return result

        live_etag = resp.headers.get("ETag")
        live_cl = resp.headers.get("Content-Length")

        # ── etag check ──
        if live_etag is None:
            result["warnings"].append("Server returned no ETag header")
        elif rec["etag"] and live_etag != rec["etag"]:
            result["errors"].append(
                f"ETag mismatch: metadata={rec['etag']}  live={live_etag}"
            )
        elif rec["etag"] and live_etag == rec["etag"]:
            pass  # match

        # ── content-length check ──
        if live_cl is None:
            result["warnings"].append(
                "Server returned no Content-Length header"
            )
        else:
            live_cl_int = int(live_cl)
            if rec["content_length"] is not None:
                if live_cl_int != rec["content_length"]:
                    result["errors"].append(
                        f"Content-Length mismatch: metadata="
                        f"{rec['content_length']}  live={live_cl_int}"
                    )
            # also cross-check against stored size
            if rec["size"] is not None and live_cl_int != rec["size"]:
                result["warnings"].append(
                    f"Content-Length ({live_cl_int}) != stored size "
                    f"({rec['size']})"
                )

    except requests.RequestException as exc:
        result["errors"].append(f"Request failed: {exc}")

    return result


def validate_live(files: list[FileRecord], *,
                  workers: int = 8,
                  timeout: int = 30) -> dict:
    """Send HEAD requests in parallel and summarise results."""
    # deduplicate by URL to avoid hitting the same file twice
    seen_urls: set[str] = set()
    unique_files: list[FileRecord] = []
    for f in files:
        if f["source_url"] not in seen_urls:
            seen_urls.add(f["source_url"])
            unique_files.append(f)

    session = _build_session()
    results: list[dict] = []
    ok = err = warn = 0

    log.info("Sending HEAD requests to %d unique URLs (%d workers)",
             len(unique_files), workers)

    done = 0
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_head_check, session, f, timeout): f
            for f in unique_files
        }
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            done += 1
            if res["errors"]:
                err += 1
            elif res["warnings"]:
                warn += 1
            else:
                ok += 1
            if done % 50 == 0 or done == len(unique_files):
                elapsed = time.perf_counter() - t0
                log.info("[%d/%d]  ok=%d err=%d warn=%d  (%.1fs)",
                         done, len(unique_files), ok, err, warn, elapsed)

    errors_list = [r for r in results if r["errors"]]
    warnings_list = [r for r in results if r["warnings"] and not r["errors"]]

    return {
        "total_checked": len(unique_files),
        "ok": ok,
        "errors": err,
        "warnings": warn,
        "error_details": errors_list,
        "warning_details": warnings_list,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Validate RDSO crawl file metadata (uniqueness + live HEAD check)")
    ap.add_argument(
        "source",
        help="Path to catalog_hierarchy.json OR a storage root containing "
             "per-file *.meta.json files")
    ap.add_argument(
        "--skip-head", action="store_true",
        help="Only run the offline uniqueness analysis, skip live HEAD requests")
    ap.add_argument(
        "--workers", type=int, default=8,
        help="Number of parallel HEAD-request workers (default: 8)")
    ap.add_argument(
        "--timeout", type=int, default=30,
        help="Per-request timeout in seconds (default: 30)")
    ap.add_argument(
        "--output", "-o", type=str, default=None,
        help="Write full JSON report to this file")
    ap.add_argument(
        "--storage-root", type=Path, default=None,
        help="Root folder used to resolve on-disk file paths from metadata")
    ap.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    source = Path(args.source)

    # ── Load file records ────────────────────────────────────────────────
    if source.is_file() and source.suffix == ".json":
        log.info("Reading catalog_hierarchy.json: %s", source)
        files = extract_files_from_hierarchy(source)
    elif source.is_dir():
        log.info("Scanning *.meta.json under: %s", source)
        files = extract_files_from_meta_jsons(source)
    else:
        log.error("%s is neither a .json file nor a directory", source)
        sys.exit(1)

    if not files:
        log.error("No file records found.")
        sys.exit(1)

    log.info("Loaded %d file record(s).", len(files))

    # ── Uniqueness check ─────────────────────────────────────────────────
    log.info("=" * 50)
    log.info("UNIQUENESS ANALYSIS")
    log.info("=" * 50)
    uniq = check_uniqueness(files)

    log.info("Total file entries     : %d", uniq['total_files'])
    log.info("Unique URLs            : %d", uniq['unique_urls'])
    log.info("Duplicate URLs         : %d", len(uniq['duplicate_urls']))
    log.info("Unique ETags           : %d", uniq['unique_etags'])
    log.info("Duplicate ETags        : %d", len(uniq['duplicate_etags']))
    log.info("Null ETags             : %d", uniq['null_etags'])
    log.info("Unique Content-Lengths : %d", uniq['unique_content_lengths'])
    log.info("Duplicate CL values    : %d", len(uniq['duplicate_content_lengths']))
    log.info("Null Content-Lengths   : %d", uniq['null_content_lengths'])

    if uniq["duplicate_etags"]:
        log.warning("%d ETags are shared by multiple URLs:",
                    len(uniq['duplicate_etags']))
        for etag, urls in list(uniq["duplicate_etags"].items())[:10]:
            log.warning("  %s  ->  %d files", etag, len(urls))
            for u in urls[:3]:
                log.debug("    %s", u)
            if len(urls) > 3:
                log.debug("    ... and %d more", len(urls) - 3)

    if uniq["duplicate_content_lengths"]:
        log.warning("%d Content-Length values are shared by multiple URLs:",
                    len(uniq['duplicate_content_lengths']))
        for cl, urls in list(uniq["duplicate_content_lengths"].items())[:10]:
            log.warning("  %s bytes  ->  %d files", cl, len(urls))

    # ── Live HEAD check ──────────────────────────────────────────────────
    report: dict[str, Any] = {"uniqueness": uniq, "disk_validation": None, "live_validation": None}

    storage_root = args.storage_root
    if storage_root is None and source.is_dir():
        storage_root = source

    if storage_root is not None:
        log.info("=" * 50)
        log.info("DISK PATH VALIDATION")
        log.info("=" * 50)
        disk = check_disk_consistency(files, storage_root)
        report["disk_validation"] = disk
        log.info("Resolved on disk      : %d", disk["ok"])
        log.info("Missing path metadata : %d", disk["missing_path_metadata"])
        log.info("Missing on disk       : %d", disk["missing_on_disk"])
    else:
        log.info("Skipping disk validation because no storage root was provided")

    if not args.skip_head:
        log.info("=" * 50)
        log.info("LIVE HEAD-REQUEST VALIDATION")
        log.info("=" * 50)
        live = validate_live(files, workers=args.workers,
                             timeout=args.timeout)
        report["live_validation"] = live

        log.info("Results: %d OK, %d errors, %d warnings",
                 live['ok'], live['errors'], live['warnings'])

        if live["error_details"]:
            log.error("Errors (%d):", live['errors'])
            for e in live["error_details"][:20]:
                log.error("  %s", e['source_url'])
                for msg in e["errors"]:
                    log.error("    -> %s", msg)

        if live["warning_details"]:
            log.warning("Warnings (%d):", live['warnings'])
            for w in live["warning_details"][:20]:
                log.warning("  %s", w['source_url'])
                for msg in w["warnings"]:
                    log.warning("    -> %s", msg)
    else:
        log.info("Skipping live HEAD requests (use without --skip-head to enable)")

    # ── Save report ──────────────────────────────────────────────────────
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(report, indent=2, default=str),
                            encoding="utf-8")
        log.info("Full report saved to %s", out_path)

    # ── Exit code ────────────────────────────────────────────────────────
    has_issues = (
        (report["disk_validation"] and (
            report["disk_validation"]["missing_path_metadata"] > 0
            or report["disk_validation"]["missing_on_disk"] > 0
        ))
        or
        uniq["null_etags"] > 0
        or uniq["null_content_lengths"] > 0
        or (report["live_validation"] and report["live_validation"]["errors"])
    )
    sys.exit(1 if has_issues else 0)


if __name__ == "__main__":
    main()
