# RDSO Crawler

This crawler mirrors the RDSO drawing site into a local folder, writes hierarchical metadata at every level, and maintains a compact state file so future runs can skip unchanged files.

## What It Crawls

- Entry page: `http://10.100.2.4/drawing/frmLink.aspx`
- Base path: `http://10.100.2.4/drawing/`
- Site hierarchy:
  - categories
  - subheads
  - drawing pages
  - downloadable files

## Crawl Flow

1. Load the entry page and discover category links from `div.descrip2`.
2. Visit each category page and discover subhead links from `div.descrip1`.
3. Visit each subhead page and discover drawing pages pointing to `frmDrawingView.aspx?h=...`.
4. Visit each drawing page and extract file URLs from:
   - regex matches for `uploadedDrawing` or `uploaded`
   - `<object data="...">`
   - hidden input values such as `hndfilepath`
5. Build hierarchical metadata for category, subhead, drawing, and file levels.
6. Use previous crawl state to decide whether a file must be downloaded again.
7. Write the refreshed metadata, flat catalog, hierarchy catalog, state, and failed download queue.

## Incremental Update Logic

The crawler defaults to `crawl-and-update` mode.

- If a file is missing locally, it is downloaded.
- If there is no previous metadata for a local file, it is downloaded to rebuild state.
- If previous metadata exists, the crawler sends a `HEAD` request and compares:
  - `ETag`
  - `Last-Modified`
  - `Content-Length`
- If those remote headers are unchanged, the local file is kept and metadata is refreshed without re-downloading the file.
- If the headers changed, the file is downloaded again.
- If the file contents changed, the old local file is archived under `_archive`.

## Supported Modes

- Normal mode:
  - Refresh metadata and download only missing or changed files.
- `--force-site-crawl`:
  - Re-download all discovered files regardless of previous metadata.
- `--no-download`:
  - Rebuild crawl metadata without downloading file bodies.
- `--limit-drawings N`:
  - Useful for bounded test runs.

## Download Strategy

- Initial download worker count defaults to 16.
- If throttling-like failures appear, the crawler:
  - reduces worker count
  - increases timeout
  - sleeps before retrying
- Failed downloads are stored in `failed_downloads.json` so the next run can prioritize them.

## Main Outputs

- `__meta__.json`: root crawl summary
- `__state__.json`: compact state used for incremental checks
- `catalog_hierarchy.json`: full nested hierarchy export
- `catalog_flat.json`: flat list of drawing records
- `removed_since_previous.json`: removed drawings and file URLs compared with prior state
- `failed_downloads.json`: files that exhausted retries in the current run
- `logYYYYMMDDTHHMMSS.txt`: per-run log file

## Typical Commands

Full production crawl:

```powershell
c:/Users/Noodl/Scripts/Scapper/.venv/Scripts/python.exe rdso_site_crawler.py --storage-root D:/RDSO --download-workers 16
```

Metadata refresh without file download:

```powershell
c:/Users/Noodl/Scripts/Scapper/.venv/Scripts/python.exe rdso_site_crawler.py --storage-root D:/RDSO --no-download
```

Small test run:

```powershell
c:/Users/Noodl/Scripts/Scapper/.venv/Scripts/python.exe rdso_site_crawler.py --storage-root c:/Users/Noodl/Scripts/Scapper/_test_crawl_fixed --limit-drawings 3 --download-workers 4
```

## Important Implementation Notes

- The crawler now stores one file record per discovered file URL per drawing.
- File metadata includes a root-relative path so the downloaded file can be located directly from metadata.
- The current production metadata in `D:\RDSO` has already been refreshed with the fixed logic.