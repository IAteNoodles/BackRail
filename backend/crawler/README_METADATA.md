# RDSO Metadata Layout

The crawler stores metadata at five levels:

1. Crawl root
2. Category
3. Subhead
4. Drawing page
5. Downloaded file

## Root-Level Files

The storage root contains these top-level files:

- `__meta__.json`
  - Human-readable crawl summary and totals
- `__state__.json`
  - Compact lookup state used for incremental update checks
- `catalog_hierarchy.json`
  - Full nested export of the crawl
- `catalog_flat.json`
  - Flat list of drawing records
- `removed_since_previous.json`
  - Drawings and file URLs that disappeared since the previous crawl
- `failed_downloads.json`
  - Retry queue for files that could not be fetched in the current run

## Folder Structure

The on-disk folder structure mirrors the site hierarchy:

```text
storage-root/
  Category__c{id}/
    __meta__.json
    Subhead__s{id}/
      __meta__.json
      Drawing__h{id}/
        __meta__.json
        file.pdf
        file.pdf.meta.json
        _archive/
```

## Naming Scheme

- Categories use `__c{category_id}` when available.
- Subheads use `__s{subhead_id}` or `__h{value}` when derived from query parameters.
- Drawings use `__h{drawing_id}`.
- Names are sanitized for Windows-safe paths.

## Root Metadata

`__meta__.json` at the storage root contains:

- crawl summary and status
- crawl context
- counts of categories, subheads, drawings, and files
- counts of downloads, changes, and archives for the current run
- removed drawings and removed file URLs compared with previous state
- category overview with relative paths

## Compact State

`__state__.json` is optimized for future runs.

It contains:

- `drawings_by_page_url`
- `files_by_url`
- `categories_by_url`
- `subheads_by_url`
- `pending_retry_files`

The crawler reads this file on startup to decide whether a file can be skipped or must be downloaded again.

## Drawing Metadata

Each drawing folder contains a `__meta__.json` file with:

- drawing identity
- source page URL
- page hash
- category and subhead context
- local relative path
- the list of discovered file records

Key fields:

- `page_url`
- `page_hash`
- `relative_path`
- `files`
- `file_count`

## File Metadata

Each downloaded file has a sidecar metadata file such as `file.pdf.meta.json`.

Important fields include:

- `source_url`
- `source_page`
- `stored_file`
- `drawing_relative_path`
- `stored_relative_path`
- `stored_relative_path_from_drawing`
- `sha256`
- `etag`
- `last_modified`
- `content_length`
- `downloaded_this_run`
- `changed_this_run`
- `archived_to`

## How To Resolve A File On Disk

The direct rule is:

```text
absolute_file_path = storage_root + stored_relative_path
```

Example:

- storage root: `D:\RDSO`
- stored relative path: `Abutments__c18/.../10340-R2.pdf`

The validator now checks that every unique file URL can be resolved on disk through this metadata.

## Validation

`validate_files.py` supports three checks:

1. URL, ETag, and content-length uniqueness
2. Disk path resolution from metadata
3. Optional live `HEAD` validation against the server

Typical offline validation command:

```powershell
c:/Users/Noodl/Scripts/Scapper/.venv/Scripts/python.exe validate_files.py D:\RDSO --storage-root D:\RDSO --skip-head -o D:\RDSO\validation_report.json
```

## Known Semantics

- A duplicate source URL across multiple drawings is allowed if the site reuses the exact same remote file.
- Duplicate content lengths alone do not prove two files are the same.
- The exact duplicate bug that previously doubled file counts has been fixed.