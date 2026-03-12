from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from lxml import html
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "http://10.100.2.4/drawing/"
ENTRY_URL = urljoin(BASE_URL, "frmLink.aspx")
DEFAULT_STORAGE_ROOT = Path(r"D:\RDSO")
REQUEST_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 60
RETRY_LIMIT = 3
RETRY_BACKOFF = 1.5
CRAWL_DELAY = 0.05
STATE_FILE_NAME = "__state__.json"
META_FILE_NAME = "__meta__.json"
ARCHIVE_DIR_NAME = "_archive"
LOG_FILE_NAME = "crawl.log"
FAILED_DOWNLOADS_FILE_NAME = "failed_downloads.json"
MAX_DOWNLOAD_ATTEMPTS = 5
INITIAL_DOWNLOAD_WORKERS = 16
THROTTLE_SLEEP_SECONDS = 60

FILE_PATTERN = re.compile(
    r'(?:uploadedDrawing|uploaded)/[^\s"\'<>]+\.(?:jpg|jpeg|png|gif|bmp|tif|tiff|pdf)',
    re.IGNORECASE,
)
DOWNLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".pdf"}
STATIC_PATH_MARKERS = ("/drawing/images/",)
STATIC_FILE_NAMES = {"search3.jpg", "download.png"}
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]')


@dataclass
class CrawlContext:
    storage_root: Path
    force_site_crawl: bool
    no_download: bool
    limit_drawings: int | None
    initial_download_workers: int
    run_started_at: str
    previous_state: dict[str, Any]


logger = logging.getLogger("rdso_site_crawler")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_reason_message(reason_code: str, *, force_site_crawl: bool, local_exists: bool, previous_file_state: dict[str, Any] | None) -> str:
    if reason_code == "forced-or-missing":
        if force_site_crawl:
            return "The crawler was forced to fetch this file again, so it was downloaded regardless of prior metadata."
        if not local_exists:
            return "The file did not exist in local storage, so it was downloaded."
        if previous_file_state is None:
            return "The file existed locally, but there was no previous crawl state for it, so it was downloaded to rebuild metadata."
        return "The crawler could not rely on previous local state, so it downloaded the file."
    if reason_code == "remote-headers-changed":
        return "The remote file headers changed since the previous crawl, so the file was downloaded again for verification."
    if reason_code == "remote-headers-unchanged":
        return "The remote file headers matched the previous crawl, so the existing local file was kept."
    if reason_code == "remote-headers-unavailable":
        return "The server did not provide enough header information to compare safely, so the file was downloaded again."
    return "The crawler made a download decision using the available local and remote metadata."


def file_lifecycle_status(*, had_previous_state: bool, local_exists_before_run: bool, downloaded: bool, archived_to: str | None) -> str:
    if archived_to:
        return "updated-and-archived"
    if downloaded and (not had_previous_state or not local_exists_before_run):
        return "newly-downloaded"
    if downloaded:
        return "re-checked"
    return "unchanged"


def file_lifecycle_message(status: str) -> str:
    messages = {
        "updated-and-archived": "A newer version replaced the previous local file, and the older version was moved into the archive.",
        "newly-downloaded": "This file was added to local storage during this crawl.",
        "re-checked": "The file was downloaded again for verification, but the active local copy did not need archival replacement.",
        "unchanged": "The existing local file remained valid, so no new download was required.",
    }
    return messages.get(status, "The crawler recorded the current state of this file.")


def page_summary(kind: str, title: str, *, relative_path_value: str, item_count_name: str | None = None, item_count: int | None = None, file_count: int | None = None) -> dict[str, Any]:
    summary = {
        "kind": kind,
        "title": title,
        "relative_path": relative_path_value,
    }
    if item_count_name is not None and item_count is not None:
        summary[item_count_name] = item_count
    if file_count is not None:
        summary["file_count"] = file_count
    return summary


def configure_logging(storage_root: Path, run_started_at: str) -> Path:
    ensure_directory(storage_root)
    stamp = run_started_at.replace("-", "").replace(":", "").split(".")[0].replace("+0000", "")
    log_path = storage_root / f"log{stamp}.txt"
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return log_path


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=RETRY_LIMIT,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_name(name: str, max_len: int = 80) -> str:
    cleaned = INVALID_PATH_CHARS.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned or "unnamed"
    return cleaned[:max_len].rstrip(" .") or "unnamed"


def query_value(url: str, key: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(key)
    return values[0] if values else None


def category_dir_name(name: str, url: str) -> str:
    suffix = query_value(url, "c")
    return f"{sanitize_name(name, 50)}__c{suffix}" if suffix else sanitize_name(name, 60)


def subhead_dir_name(name: str, url: str) -> str:
    suffix = query_value(url, "s") or query_value(url, "h")
    return f"{sanitize_name(name, 55)}__s{suffix}" if suffix else sanitize_name(name, 65)


def drawing_dir_name(name: str, drawing_id: int | None) -> str:
    suffix = f"__h{drawing_id}" if drawing_id is not None else ""
    return f"{sanitize_name(name, 55)}{suffix}"


def file_name_from_url(url: str) -> str:
    return Path(urlparse(url).path).name


def ext_from_url(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def is_download_candidate(file_url: str) -> bool:
    lowered = file_url.lower()
    filename = file_name_from_url(file_url).lower()
    if any(marker in lowered for marker in STATIC_PATH_MARKERS):
        return False
    if filename in STATIC_FILE_NAMES:
        return False
    return ext_from_url(file_url) in DOWNLOAD_EXTENSIONS


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def fetch_response(session: requests.Session, url: str, *, method: str = "GET", stream: bool = False, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    response = session.request(method, url, timeout=timeout, stream=stream, allow_redirects=True)
    response.raise_for_status()
    return response


def fetch_html(session: requests.Session, url: str) -> tuple[requests.Response, html.HtmlElement, str]:
    response = fetch_response(session, url)
    content = response.content
    tree = html.fromstring(content)
    tree.make_links_absolute(url)
    page_hash = sha256_bytes(content)
    time.sleep(CRAWL_DELAY)
    return response, tree, page_hash


def prompt_storage_root(default_root: Path) -> Path:
    if not sys.stdin.isatty():
        return default_root

    raw = input(f"Download location [{default_root}]: ").strip()
    return Path(raw) if raw else default_root


def load_previous_state(storage_root: Path) -> dict[str, Any]:
    state_path = storage_root / STATE_FILE_NAME
    if state_path.exists():
        return read_json(state_path)
    return {
        "drawings_by_page_url": {},
        "files_by_url": {},
        "categories_by_url": {},
        "subheads_by_url": {},
        "pending_retry_files": [],
    }


def relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def probe_remote_file(session: requests.Session, file_url: str, *, timeout: int = DOWNLOAD_TIMEOUT) -> dict[str, Any]:
    headers_info = {
        "etag": None,
        "last_modified": None,
        "content_length": None,
        "content_type": None,
        "probe_status": "unavailable",
    }
    try:
        response = fetch_response(session, file_url, method="HEAD", timeout=timeout)
    except Exception:
        logger.debug("HEAD probe failed for %s", file_url)
        return headers_info

    headers_info.update(
        {
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "content_length": int(response.headers.get("Content-Length")) if response.headers.get("Content-Length", "").isdigit() else None,
            "content_type": response.headers.get("Content-Type"),
            "probe_status": "head",
        }
    )
    return headers_info


def download_file(session: requests.Session, file_url: str, target_path: Path, *, timeout: int = DOWNLOAD_TIMEOUT) -> dict[str, Any]:
    temp_path = target_path.with_name(f".{target_path.name}.tmp")
    digest = hashlib.sha256()
    size = 0

    response = fetch_response(session, file_url, stream=True, timeout=timeout)
    try:
        with temp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    finally:
        response.close()

    return {
        "temp_path": temp_path,
        "sha256": digest.hexdigest(),
        "size": size,
        "content_type": response.headers.get("Content-Type"),
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "status_code": response.status_code,
    }


def archive_existing_file(file_path: Path, archive_dir: Path, archived_at: str) -> str:
    ensure_directory(archive_dir)
    archived_name = f"{archived_at.replace(':', '').replace('-', '')}__{file_path.name}"
    archived_path = archive_dir / archived_name
    shutil.move(str(file_path), str(archived_path))

    meta_path = file_path.with_suffix(file_path.suffix + ".meta.json")
    if meta_path.exists():
        shutil.move(str(meta_path), str(archive_dir / f"{archived_name}.meta.json"))

    return archived_path.name


def dedupe_file_items(file_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in file_items:
        source_url = item.get("source_url")
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        deduped.append(item)
    return deduped


def sync_downloaded_file(
    session: requests.Session,
    storage_root: Path,
    drawing_dir: Path,
    file_url: str,
    drawing_page_url: str,
    previous_file_state: dict[str, Any] | None,
    *,
    force_site_crawl: bool,
    no_download: bool,
    run_started_at: str,
    request_timeout: int,
) -> dict[str, Any]:
    original_name = file_name_from_url(file_url)
    safe_name = sanitize_name(original_name, 120)
    file_path = drawing_dir / safe_name
    archive_dir = drawing_dir / ARCHIVE_DIR_NAME
    drawing_relative_path = relative_path(drawing_dir, storage_root)
    file_relative_path_from_root = relative_path(file_path, storage_root)
    file_relative_path_from_drawing = relative_path(file_path, drawing_dir)

    remote_probe = probe_remote_file(session, file_url, timeout=request_timeout)
    local_exists = file_path.exists()
    had_previous_state = previous_file_state is not None
    should_download = force_site_crawl or not local_exists or previous_file_state is None
    decision_reason = "forced-or-missing"

    if not should_download:
        comparable_keys = ["etag", "last_modified", "content_length"]
        probe_values = {key: remote_probe.get(key) for key in comparable_keys if remote_probe.get(key) is not None}
        if probe_values:
            mismatch = any(previous_file_state.get(key) != value for key, value in probe_values.items())
            should_download = mismatch
            decision_reason = "remote-headers-changed" if mismatch else "remote-headers-unchanged"
        else:
            should_download = True
            decision_reason = "remote-headers-unavailable"

    archived_versions = list((previous_file_state or {}).get("archived_versions", []))
    file_changed = False
    downloaded = False
    archived_to = None

    if no_download:
        downloaded = False
        file_changed = False
        sha256_value = previous_file_state.get("sha256") if previous_file_state else None
        size_value = previous_file_state.get("size") if previous_file_state else None
        content_type = remote_probe.get("content_type") or (previous_file_state.get("content_type") if previous_file_state else None)
        etag = remote_probe.get("etag") or (previous_file_state.get("etag") if previous_file_state else None)
        last_modified = remote_probe.get("last_modified") or (previous_file_state.get("last_modified") if previous_file_state else None)
        content_length = remote_probe.get("content_length") or (previous_file_state.get("content_length") if previous_file_state else None)
        decision_reason = "metadata-only"
    elif should_download:
        result = download_file(session, file_url, file_path, timeout=request_timeout)
        downloaded = True
        new_hash = result["sha256"]
        new_size = result["size"]

        if local_exists:
            existing_hash = previous_file_state.get("sha256") if previous_file_state else hash_file(file_path)
            if existing_hash != new_hash:
                archived_name = archive_existing_file(file_path, archive_dir, run_started_at)
                archived_versions.append(
                    {
                        "archived_at": run_started_at,
                        "archive_file": f"{ARCHIVE_DIR_NAME}/{archived_name}",
                        "previous_sha256": existing_hash,
                    }
                )
                archived_to = f"{ARCHIVE_DIR_NAME}/{archived_name}"
                file_changed = True
                shutil.move(str(result["temp_path"]), str(file_path))
            else:
                result["temp_path"].unlink(missing_ok=True)
        else:
            file_changed = True
            shutil.move(str(result["temp_path"]), str(file_path))

        sha256_value = new_hash if file_path.exists() else previous_file_state.get("sha256")
        size_value = new_size if file_path.exists() else previous_file_state.get("size")
        content_type = result.get("content_type") or remote_probe.get("content_type")
        etag = result.get("etag") or remote_probe.get("etag")
        last_modified = result.get("last_modified") or remote_probe.get("last_modified")
        content_length = new_size
    else:
        sha256_value = previous_file_state.get("sha256")
        size_value = previous_file_state.get("size")
        content_type = remote_probe.get("content_type") or previous_file_state.get("content_type")
        etag = remote_probe.get("etag") or previous_file_state.get("etag")
        last_modified = remote_probe.get("last_modified") or previous_file_state.get("last_modified")
        content_length = remote_probe.get("content_length") or previous_file_state.get("content_length")

    lifecycle_status = "metadata-only" if no_download else file_lifecycle_status(
        had_previous_state=had_previous_state,
        local_exists_before_run=local_exists,
        downloaded=downloaded,
        archived_to=archived_to,
    )
    decision_message = "Download was intentionally skipped because the crawler was running in metadata-only mode." if no_download else decision_reason_message(
        decision_reason,
        force_site_crawl=force_site_crawl,
        local_exists=local_exists,
        previous_file_state=previous_file_state,
    )

    file_meta = {
        "schema_version": 2,
        "summary": {
            "kind": "downloaded_file",
            "title": safe_name,
            "status": lifecycle_status,
            "status_message": "The crawler recorded source and remote metadata without downloading the file." if no_download else file_lifecycle_message(lifecycle_status),
            "decision_reason": decision_reason,
            "decision_message": decision_message,
        },
        "source": {
            "file_url": file_url,
            "discovered_on_page": drawing_page_url,
            "original_name": original_name,
        },
        "storage": {
            "file_name": safe_name,
            "drawing_relative_path": drawing_relative_path,
            "relative_path": file_relative_path_from_root,
            "relative_path_from_root": file_relative_path_from_root,
            "relative_path_from_drawing": file_relative_path_from_drawing,
            "archive_directory": ARCHIVE_DIR_NAME,
        },
        "integrity": {
            "sha256": sha256_value,
            "size_bytes": size_value,
            "content_type": content_type,
        },
        "remote_headers": {
            "etag": etag,
            "last_modified": last_modified,
            "content_length": content_length,
            "probe_status": remote_probe.get("probe_status"),
        },
        "update_tracking": {
            "downloaded_at": run_started_at if downloaded else previous_file_state.get("downloaded_at"),
            "last_checked_at": run_started_at,
            "downloaded_this_run": downloaded,
            "changed_this_run": file_changed,
            "metadata_only_run": no_download,
            "archived_to": archived_to,
            "archived_versions": archived_versions,
        },
        "source_url": file_url,
        "source_page": drawing_page_url,
        "stored_file": safe_name,
        "drawing_relative_path": drawing_relative_path,
        "stored_relative_path": file_relative_path_from_root,
        "stored_relative_path_from_drawing": file_relative_path_from_drawing,
        "sha256": sha256_value,
        "size": size_value,
        "content_type": content_type,
        "etag": etag,
        "last_modified": last_modified,
        "content_length": content_length,
        "downloaded_at": run_started_at if downloaded else previous_file_state.get("downloaded_at"),
        "last_checked_at": run_started_at,
        "probe_status": remote_probe.get("probe_status"),
        "downloaded_this_run": downloaded,
        "changed_this_run": file_changed,
        "metadata_only_run": no_download,
        "archived_to": archived_to,
        "archived_versions": archived_versions,
        "decision_reason": decision_reason,
    }

    write_json(file_path.with_suffix(file_path.suffix + ".meta.json"), file_meta)
    time.sleep(CRAWL_DELAY)
    return file_meta


def is_throttling_failure(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    indicators = [
        "429",
        "503",
        "504",
        "too many requests",
        "timed out",
        "timeout",
        "connection aborted",
        "connection reset",
        "temporarily unavailable",
        "remote end closed connection",
    ]
    return any(token in lowered for token in indicators)


def make_file_task(
    *,
    drawing_meta: dict[str, Any],
    drawing_dir: Path,
    file_url: str,
    previous_file_state: dict[str, Any] | None,
    retry_priority_urls: set[str],
) -> dict[str, Any]:
    return {
        "drawing_meta": drawing_meta,
        "drawing_dir": drawing_dir,
        "file_url": file_url,
        "drawing_page_url": drawing_meta["page_url"],
        "previous_file_state": previous_file_state,
        "attempts": 0,
        "priority": 0 if file_url in retry_priority_urls else 1,
    }


def run_file_task(task: dict[str, Any], context: CrawlContext, request_timeout: int) -> tuple[bool, dict[str, Any], dict[str, Any] | None, str | None]:
    session = build_session()
    try:
        file_meta = sync_downloaded_file(
            session,
            context.storage_root,
            task["drawing_dir"],
            task["file_url"],
            task["drawing_page_url"],
            task["previous_file_state"],
            force_site_crawl=context.force_site_crawl,
            no_download=context.no_download,
            run_started_at=context.run_started_at,
            request_timeout=request_timeout,
        )
        return True, task, file_meta, None
    except Exception as exc:
        return False, task, None, str(exc)
    finally:
        session.close()


def process_download_tasks(context: CrawlContext, tasks: list[dict[str, Any]]) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    if not tasks:
        return {
            "downloaded": 0,
            "changed": 0,
            "archived": 0,
            "failed": 0,
            "workers_final": context.initial_download_workers,
        }, [], []

    pending = sorted(tasks, key=lambda item: (item["priority"], item["file_url"]))
    completed: list[dict[str, Any]] = []
    failed_forever: list[dict[str, Any]] = []
    workers = max(1, context.initial_download_workers)
    request_timeout = DOWNLOAD_TIMEOUT
    stats = {"downloaded": 0, "changed": 0, "archived": 0, "failed": 0, "workers_final": workers}

    while pending:
        logger.info("Download round starting: %s pending files, workers=%s, timeout=%ss", len(pending), workers, request_timeout)
        throttling_seen = False
        next_pending: list[dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(run_file_task, task, context, request_timeout): task
                for task in pending
            }
            for future in concurrent.futures.as_completed(future_map):
                task = future_map[future]
                success, original_task, file_meta, error_text = future.result()
                if success:
                    drawing_meta = original_task["drawing_meta"]
                    drawing_meta["downloaded_files"].append(file_meta)
                    drawing_meta["file_count"] = len(drawing_meta["downloaded_files"])
                    drawing_meta["summary"]["downloaded_file_count"] = drawing_meta["file_count"]
                    drawing_meta["summary"]["file_count"] = drawing_meta["file_count"]
                    drawing_meta["storage"]["file_count"] = drawing_meta["file_count"]
                    stats["downloaded"] += 1 if file_meta["downloaded_this_run"] else 0
                    stats["changed"] += 1 if file_meta["changed_this_run"] else 0
                    stats["archived"] += 1 if file_meta["archived_to"] else 0
                    logger.info(
                        "File %s -> downloaded=%s changed=%s archived=%s reason=%s",
                        original_task["file_url"],
                        file_meta["downloaded_this_run"],
                        file_meta["changed_this_run"],
                        bool(file_meta["archived_to"]),
                        file_meta["decision_reason"],
                    )
                else:
                    original_task["attempts"] += 1
                    failure_record = {
                        "file_url": original_task["file_url"],
                        "drawing_page_url": original_task["drawing_page_url"],
                        "attempts": original_task["attempts"],
                        "last_error": error_text,
                    }
                    logger.warning(
                        "File download failed (%s/%s): %s -> %s",
                        original_task["attempts"],
                        MAX_DOWNLOAD_ATTEMPTS,
                        original_task["file_url"],
                        error_text,
                    )
                    if is_throttling_failure(error_text):
                        throttling_seen = True
                    if original_task["attempts"] < MAX_DOWNLOAD_ATTEMPTS:
                        next_pending.append(original_task)
                    else:
                        failed_forever.append(failure_record)
                        stats["failed"] += 1

        pending = sorted(next_pending, key=lambda item: (item["attempts"], item["priority"], item["file_url"]))
        if pending and throttling_seen:
            workers = max(1, workers // 2)
            request_timeout = min(300, request_timeout + 30)
            logger.warning(
                "Throttling-like errors detected. Sleeping %s seconds, reducing workers to %s, increasing timeout to %ss.",
                THROTTLE_SLEEP_SECONDS,
                workers,
                request_timeout,
            )
            time.sleep(THROTTLE_SLEEP_SECONDS)
        elif pending and workers > 1 and len(pending) < workers:
            workers = len(pending)

    stats["workers_final"] = workers
    return stats, completed, failed_forever


def discover_categories(session: requests.Session) -> tuple[list[dict[str, Any]], str]:
    _, tree, entry_hash = fetch_html(session, ENTRY_URL)
    found = {}
    for anchor in tree.xpath("//*[contains(@class,'descrip2')]//a[@href]"):
        href = anchor.get("href", "")
        name = anchor.text_content().strip()
        if href and name:
            found[href] = {"name": name, "url": href}
    categories = [found[url] for url in sorted(found, key=lambda item: found[item]["name"].lower())]
    return categories, entry_hash


def discover_subheads(session: requests.Session, categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for category in categories:
        logger.info("Scanning category: %s", category["name"])
        _, tree, page_hash = fetch_html(session, category["url"])
        category["page_hash"] = page_hash
        label = tree.xpath("//span[contains(@id,'lblItem')]/text()")
        category_name = label[0].strip() if label else category["name"]
        category["display_name"] = category_name

        for anchor in tree.xpath("//*[contains(@class,'descrip1')]//a[@href]"):
            href = anchor.get("href", "")
            name = anchor.text_content().strip()
            if href and name and "frmDrawing" in href and href not in seen_urls:
                seen_urls.add(href)
                discovered.append(
                    {
                        "name": name,
                        "url": href,
                        "category": category_name,
                        "category_url": category["url"],
                    }
                )
    return discovered


def discover_drawings(session: requests.Session, subheads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drawings: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for subhead in subheads:
        logger.info("Scanning subhead: %s", subhead["name"])
        _, tree, page_hash = fetch_html(session, subhead["url"])
        subhead["page_hash"] = page_hash
        for anchor in tree.xpath("//*[contains(@class,'descrip1')]//a[@href]"):
            href = anchor.get("href", "")
            name = anchor.text_content().strip()
            if href and name and "frmDrawingView" in href and href not in seen_urls:
                seen_urls.add(href)
                drawing_id = query_value(href, "h")
                drawings.append(
                    {
                        "id": int(drawing_id) if drawing_id and drawing_id.isdigit() else None,
                        "name": name,
                        "url": href,
                        "category": subhead["category"],
                        "category_url": subhead["category_url"],
                        "subhead": subhead["name"],
                        "subhead_url": subhead["url"],
                    }
                )
    return drawings


def extract_drawing_files(draw_url: str, raw_html: str, tree: html.HtmlElement) -> list[str]:
    candidates: set[str] = set()

    for match in FILE_PATTERN.finditer(raw_html):
        candidates.add(urljoin(draw_url, match.group(0)))

    for obj_data in tree.xpath("//object/@data"):
        value = obj_data.strip()
        if value and value.lower() != "no" and "." in value:
            candidates.add(urljoin(draw_url, value))

    for input_value in tree.xpath("//input[contains(@id,'hndfilepath')]/@value"):
        value = input_value.strip()
        if value and value.lower() != "no" and "." in value:
            candidates.add(urljoin(draw_url, value))

    return sorted(file_url for file_url in candidates if is_download_candidate(file_url))


def build_hierarchy(context: CrawlContext, session: requests.Session) -> dict[str, Any]:
    categories, entry_hash = discover_categories(session)
    subheads = discover_subheads(session, categories)
    drawings = discover_drawings(session, subheads)

    if context.limit_drawings is not None:
        drawings = drawings[: context.limit_drawings]

    categories_by_name: dict[str, dict[str, Any]] = {}

    for category in categories:
        category_path = context.storage_root / category_dir_name(category.get("display_name", category["name"]), category["url"])
        categories_by_name[category.get("display_name", category["name"])] = {
            "category": category.get("display_name", category["name"]),
            "category_url": category["url"],
            "page_hash": category.get("page_hash"),
            "relative_path": relative_path(category_path, context.storage_root),
            "subheads": {},
        }

    for subhead in subheads:
        category_bucket = categories_by_name[subhead["category"]]
        category_dir = context.storage_root / category_bucket["relative_path"]
        subhead_path = category_dir / subhead_dir_name(subhead["name"], subhead["url"])
        category_bucket["subheads"][subhead["name"]] = {
            "subhead": subhead["name"],
            "subhead_url": subhead["url"],
            "page_hash": subhead.get("page_hash"),
            "relative_path": relative_path(subhead_path, context.storage_root),
            "drawings": [],
        }

    files_downloaded = 0
    files_changed = 0
    archived_files = 0
    retry_priority_urls = set(context.previous_state.get("pending_retry_files", []))
    download_tasks: list[dict[str, Any]] = []

    for index, drawing in enumerate(drawings, start=1):
        logger.info("Processing drawing %s/%s: %s", index, len(drawings), drawing["name"])
        response, tree, page_hash = fetch_html(session, drawing["url"])
        raw_html = response.text
        files = extract_drawing_files(drawing["url"], raw_html, tree)
        description_nodes = tree.xpath("//span[contains(@id,'lblDrawingDesc')]/text()")
        description = description_nodes[0].strip() if description_nodes and description_nodes[0].strip() else None

        category_bucket = categories_by_name[drawing["category"]]
        subhead_bucket = category_bucket["subheads"][drawing["subhead"]]
        drawing_path = context.storage_root / subhead_bucket["relative_path"] / drawing_dir_name(drawing["name"], drawing["id"])
        ensure_directory(drawing_path)

        previous_drawing_state = context.previous_state.get("drawings_by_page_url", {}).get(drawing["url"], {})
        previous_files_by_url = previous_drawing_state.get("files_by_url", {})

        synced_files: list[dict[str, Any]] = []
        drawing_meta = {
            "schema_version": 2,
            "summary": page_summary(
                "drawing",
                drawing["name"],
                relative_path_value=relative_path(drawing_path, context.storage_root),
                item_count_name="downloaded_file_count",
                item_count=0,
                file_count=0,
            ),
            "generated_at_utc": context.run_started_at,
            "identity": {
                "drawing_id": drawing["id"],
                "drawing_name": drawing["name"],
                "description": description,
            },
            "source": {
                "drawing_page_url": drawing["url"],
                "drawing_page_hash": page_hash,
                "category": drawing["category"],
                "category_url": drawing["category_url"],
                "subhead": drawing["subhead"],
                "subhead_url": drawing["subhead_url"],
            },
            "storage": {
                "relative_path": relative_path(drawing_path, context.storage_root),
                "file_count": 0,
            },
            "downloaded_files": [],
            "id": drawing["id"],
            "file_name": drawing["name"],
            "description": description,
            "page_url": drawing["url"],
            "page_hash": page_hash,
            "category": drawing["category"],
            "category_url": drawing["category_url"],
            "subhead": drawing["subhead"],
            "subhead_url": drawing["subhead_url"],
            "relative_path": relative_path(drawing_path, context.storage_root),
            "file_count": 0,
            "files": synced_files,
        }

        for file_url in files:
            download_tasks.append(
                make_file_task(
                    drawing_meta=drawing_meta,
                    drawing_dir=drawing_path,
                    file_url=file_url,
                    previous_file_state=previous_files_by_url.get(file_url),
                    retry_priority_urls=retry_priority_urls,
                )
            )
        write_json(drawing_path / META_FILE_NAME, drawing_meta)
        subhead_bucket["drawings"].append(drawing_meta)

        if index % 100 == 0:
            logger.info("Progress: %s/%s drawing pages processed", index, len(drawings))

    download_stats, _completed, failed_forever = process_download_tasks(context, download_tasks)
    files_downloaded = download_stats["downloaded"]
    files_changed = download_stats["changed"]
    archived_files = download_stats["archived"]

    for category_bucket in categories_by_name.values():
        for subhead_bucket in category_bucket["subheads"].values():
            for drawing_meta in subhead_bucket["drawings"]:
                deduped_files = dedupe_file_items(drawing_meta["downloaded_files"])
                drawing_meta["downloaded_files"] = sorted(deduped_files, key=lambda item: item["source_url"])
                drawing_meta["files"] = drawing_meta["downloaded_files"]
                drawing_meta["file_count"] = len(drawing_meta["files"])
                drawing_meta["summary"]["downloaded_file_count"] = drawing_meta["file_count"]
                drawing_meta["summary"]["file_count"] = drawing_meta["file_count"]
                drawing_meta["storage"]["file_count"] = drawing_meta["file_count"]
                write_json(context.storage_root / drawing_meta["relative_path"] / META_FILE_NAME, drawing_meta)

    hierarchy_categories = []
    for category_name in sorted(categories_by_name):
        category_bucket = categories_by_name[category_name]
        category_dir = context.storage_root / category_bucket["relative_path"]
        ensure_directory(category_dir)

        subhead_items = []
        for subhead_name in sorted(category_bucket["subheads"]):
            subhead_bucket = category_bucket["subheads"][subhead_name]
            subhead_dir = context.storage_root / subhead_bucket["relative_path"]
            ensure_directory(subhead_dir)

            drawings_sorted = sorted(
                subhead_bucket["drawings"],
                key=lambda item: (item["id"] is None, item["id"] or 0, item["file_name"]),
            )
            subhead_meta = {
                "schema_version": 2,
                "summary": page_summary(
                    "subhead",
                    subhead_bucket["subhead"],
                    relative_path_value=subhead_bucket["relative_path"],
                    item_count_name="drawing_count",
                    item_count=len(drawings_sorted),
                    file_count=sum(len(item["files"]) for item in drawings_sorted),
                ),
                "generated_at_utc": context.run_started_at,
                "identity": {
                    "category": category_bucket["category"],
                    "subhead": subhead_bucket["subhead"],
                },
                "source": {
                    "category_url": category_bucket["category_url"],
                    "subhead_url": subhead_bucket["subhead_url"],
                    "subhead_page_hash": subhead_bucket["page_hash"],
                },
                "storage": {
                    "relative_path": subhead_bucket["relative_path"],
                },
                "drawings_in_this_subhead": drawings_sorted,
                "category": category_bucket["category"],
                "category_url": category_bucket["category_url"],
                "subhead": subhead_bucket["subhead"],
                "subhead_url": subhead_bucket["subhead_url"],
                "page_hash": subhead_bucket["page_hash"],
                "relative_path": subhead_bucket["relative_path"],
                "drawing_count": len(drawings_sorted),
                "file_count": sum(len(item["files"]) for item in drawings_sorted),
                "drawings": drawings_sorted,
            }
            write_json(subhead_dir / META_FILE_NAME, subhead_meta)
            subhead_items.append(subhead_meta)

        category_meta = {
            "schema_version": 2,
            "summary": page_summary(
                "category",
                category_bucket["category"],
                relative_path_value=category_bucket["relative_path"],
                item_count_name="subhead_count",
                item_count=len(subhead_items),
                file_count=sum(item["file_count"] for item in subhead_items),
            ),
            "generated_at_utc": context.run_started_at,
            "identity": {
                "category": category_bucket["category"],
            },
            "source": {
                "category_url": category_bucket["category_url"],
                "category_page_hash": category_bucket["page_hash"],
            },
            "storage": {
                "relative_path": category_bucket["relative_path"],
            },
            "subheads_in_this_category": subhead_items,
            "category": category_bucket["category"],
            "category_url": category_bucket["category_url"],
            "page_hash": category_bucket["page_hash"],
            "relative_path": category_bucket["relative_path"],
            "subhead_count": len(subhead_items),
            "drawing_count": sum(item["drawing_count"] for item in subhead_items),
            "file_count": sum(item["file_count"] for item in subhead_items),
            "subheads": subhead_items,
        }
        write_json(category_dir / META_FILE_NAME, category_meta)
        hierarchy_categories.append(category_meta)

    return {
        "schema_version": 2,
        "summary": {
            "kind": "site_catalog",
            "title": "RDSO drawing crawl",
            "category_count": len(hierarchy_categories),
            "subhead_count": sum(item["subhead_count"] for item in hierarchy_categories),
            "drawing_count": sum(item["drawing_count"] for item in hierarchy_categories),
            "file_count": sum(item["file_count"] for item in hierarchy_categories),
        },
        "generated_at_utc": context.run_started_at,
        "entry_url": ENTRY_URL,
        "base_url": BASE_URL,
        "entry_page_hash": entry_hash,
        "totals": {
            "categories": len(hierarchy_categories),
            "subheads": sum(item["subhead_count"] for item in hierarchy_categories),
            "drawings": sum(item["drawing_count"] for item in hierarchy_categories),
            "files": sum(item["file_count"] for item in hierarchy_categories),
            "downloaded_this_run": files_downloaded,
            "changed_this_run": files_changed,
            "archived_this_run": archived_files,
            "failed_this_run": len(failed_forever),
            "workers_final": download_stats["workers_final"],
        },
        "failed_downloads": failed_forever,
        "categories": hierarchy_categories,
    }


def build_flat_catalog(hierarchy: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = []
    for category in hierarchy["categories"]:
        for subhead in category["subheads"]:
            for drawing in subhead["drawings"]:
                catalog.append(
                    {
                        "id": drawing["id"],
                        "file_name": drawing["file_name"],
                        "category": drawing["category"],
                        "subhead": drawing["subhead"],
                        "page_url": drawing["page_url"],
                        "files": [file_item["source_url"] for file_item in drawing["files"]],
                        "description": drawing["description"],
                        "storage_path": drawing["relative_path"],
                    }
                )
    return catalog


def build_state(hierarchy: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    state = {
        "schema_version": 2,
        "summary": {
            "kind": "crawler_state",
            "title": "Compact crawl state used for incremental update checks",
        },
        "generated_at_utc": hierarchy["generated_at_utc"],
        "entry_url": hierarchy["entry_url"],
        "entry_page_hash": hierarchy["entry_page_hash"],
        "drawings_by_page_url": {},
        "files_by_url": {},
        "categories_by_url": {},
        "subheads_by_url": {},
        "pending_retry_files": [],
    }

    for category in hierarchy["categories"]:
        state["categories_by_url"][category["category_url"]] = {
            "category": category["category"],
            "page_hash": category["page_hash"],
            "relative_path": category["relative_path"],
        }
        for subhead in category["subheads"]:
            state["subheads_by_url"][subhead["subhead_url"]] = {
                "category": subhead["category"],
                "subhead": subhead["subhead"],
                "page_hash": subhead["page_hash"],
                "relative_path": subhead["relative_path"],
            }
            for drawing in subhead["drawings"]:
                drawing_record = {
                    "id": drawing["id"],
                    "file_name": drawing["file_name"],
                    "category": drawing["category"],
                    "subhead": drawing["subhead"],
                    "page_hash": drawing["page_hash"],
                    "relative_path": drawing["relative_path"],
                    "files_by_url": {},
                }
                for file_item in drawing["files"]:
                    file_record = {
                        key: file_item.get(key)
                        for key in [
                            "stored_file",
                            "stored_relative_path",
                            "stored_relative_path_from_drawing",
                            "drawing_relative_path",
                            "sha256",
                            "size",
                            "content_type",
                            "etag",
                            "last_modified",
                            "content_length",
                            "downloaded_at",
                            "last_checked_at",
                            "archived_versions",
                        ]
                    }
                    drawing_record["files_by_url"][file_item["source_url"]] = file_record
                    state["files_by_url"][file_item["source_url"]] = {
                        **file_record,
                        "drawing_page_url": drawing["page_url"],
                        "drawing_relative_path": drawing["relative_path"],
                    }
                state["drawings_by_page_url"][drawing["page_url"]] = drawing_record

    state["storage_root"] = str(storage_root)
    state["pending_retry_files"] = [item["file_url"] for item in hierarchy.get("failed_downloads", [])]
    return state


def summarize_removed(previous_state: dict[str, Any], current_state: dict[str, Any]) -> dict[str, Any]:
    previous_drawings = set(previous_state.get("drawings_by_page_url", {}))
    current_drawings = set(current_state.get("drawings_by_page_url", {}))
    previous_files = set(previous_state.get("files_by_url", {}))
    current_files = set(current_state.get("files_by_url", {}))
    return {
        "removed_drawings": sorted(previous_drawings - current_drawings),
        "removed_files": sorted(previous_files - current_files),
    }


def write_root_outputs(context: CrawlContext, hierarchy: dict[str, Any], catalog: list[dict[str, Any]], state: dict[str, Any]) -> None:
    removed_summary = summarize_removed(context.previous_state, state)
    root_meta = {
        "schema_version": 2,
        "summary": {
            "kind": "crawl_root",
            "title": "RDSO crawl output",
            "status": "crawl-complete",
            "status_message": "This folder contains the latest crawl, the hierarchical metadata, the flat catalog, and the compact state used for future update checks.",
        },
        "generated_at_utc": context.run_started_at,
        "crawl_context": {
            "storage_root": str(context.storage_root),
            "base_url": BASE_URL,
            "entry_url": ENTRY_URL,
            "entry_page_hash": hierarchy["entry_page_hash"],
            "mode": "force-site-crawl" if context.force_site_crawl else "crawl-and-update",
            "previous_state_found": bool(context.previous_state.get("drawings_by_page_url")),
        },
        "totals": {
            "category_count": hierarchy["totals"]["categories"],
            "subhead_count": hierarchy["totals"]["subheads"],
            "drawing_count": hierarchy["totals"]["drawings"],
            "file_count": hierarchy["totals"]["files"],
            "downloaded_this_run": hierarchy["totals"]["downloaded_this_run"],
            "changed_this_run": hierarchy["totals"]["changed_this_run"],
            "archived_this_run": hierarchy["totals"]["archived_this_run"],
        },
        "changes_since_previous_crawl": {
            "removed_drawing_count": len(removed_summary["removed_drawings"]),
            "removed_file_count": len(removed_summary["removed_files"]),
            "removed_drawings": removed_summary["removed_drawings"],
            "removed_files": removed_summary["removed_files"],
        },
        "categories_overview": [
            {
                "category": item["category"],
                "category_url": item["category_url"],
                "page_hash": item["page_hash"],
                "relative_path": item["relative_path"],
                "subhead_count": item["subhead_count"],
                "drawing_count": item["drawing_count"],
                "file_count": item["file_count"],
            }
            for item in hierarchy["categories"]
        ],
    }

    write_json(context.storage_root / META_FILE_NAME, root_meta)
    write_json(context.storage_root / STATE_FILE_NAME, state)
    write_json(context.storage_root / "catalog_hierarchy.json", hierarchy)
    write_json(context.storage_root / "catalog_flat.json", catalog)
    write_json(context.storage_root / "removed_since_previous.json", removed_summary)
    write_json(context.storage_root / FAILED_DOWNLOADS_FILE_NAME, hierarchy.get("failed_downloads", []))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incremental RDSO drawing crawler with hierarchy metadata and archive-on-change.")
    parser.add_argument("--storage-root", type=Path, help=r"Root folder for downloads and metadata. Defaults to prompting with D:\RDSO.")
    parser.add_argument("--force-site-crawl", action="store_true", help="Ignore previous file metadata and re-download all discovered files.")
    parser.add_argument("--no-download", action="store_true", help="Generate crawl metadata without downloading files.")
    parser.add_argument("--download-workers", type=int, default=INITIAL_DOWNLOAD_WORKERS, help="Initial number of download workers. Defaults to 16.")
    parser.add_argument("--limit-drawings", type=int, help="Process only the first N drawings. Useful for testing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    storage_root = args.storage_root or prompt_storage_root(DEFAULT_STORAGE_ROOT)
    ensure_directory(storage_root)
    run_started_at = now_iso()
    log_path = configure_logging(storage_root, run_started_at)

    previous_state = load_previous_state(storage_root)
    context = CrawlContext(
        storage_root=storage_root,
        force_site_crawl=args.force_site_crawl,
        no_download=args.no_download,
        limit_drawings=args.limit_drawings,
        initial_download_workers=max(1, args.download_workers),
        run_started_at=run_started_at,
        previous_state=previous_state,
    )

    logger.info("Storage root: %s", storage_root)
    logger.info("Mode: %s", "force-site-crawl" if args.force_site_crawl else "crawl-and-update")
    logger.info("Downloads: %s", "disabled (metadata-only)" if args.no_download else "enabled")
    logger.info("Initial download workers: %s", context.initial_download_workers)
    if args.limit_drawings is not None:
        logger.info("Drawing limit: %s", args.limit_drawings)
    logger.info("Log file: %s", log_path)

    session = build_session()
    hierarchy = build_hierarchy(context, session)
    catalog = build_flat_catalog(hierarchy)
    state = build_state(hierarchy, storage_root)
    write_root_outputs(context, hierarchy, catalog, state)

    logger.info("=== Crawl Complete ===")
    logger.info("Categories: %s", hierarchy['totals']['categories'])
    logger.info("Subheads: %s", hierarchy['totals']['subheads'])
    logger.info("Drawings: %s", hierarchy['totals']['drawings'])
    logger.info("Files: %s", hierarchy['totals']['files'])
    logger.info("Downloaded this run: %s", hierarchy['totals']['downloaded_this_run'])
    logger.info("Changed this run: %s", hierarchy['totals']['changed_this_run'])
    logger.info("Archived this run: %s", hierarchy['totals']['archived_this_run'])
    logger.info("Failed this run: %s", hierarchy['totals']['failed_this_run'])
    logger.info("Saved root metadata: %s", storage_root / META_FILE_NAME)
    logger.info("Saved state file: %s", storage_root / STATE_FILE_NAME)
    logger.info("Saved flat catalog: %s", storage_root / 'catalog_flat.json')
    logger.info("Saved hierarchy: %s", storage_root / 'catalog_hierarchy.json')
    logger.info("Saved failed download queue: %s", storage_root / FAILED_DOWNLOADS_FILE_NAME)


if __name__ == "__main__":
    main()