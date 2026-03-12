# RDSO Site Notes

This crawler targets the internal RDSO drawing site hosted at:

- `http://10.100.2.4/drawing/`

The entry page is:

- `http://10.100.2.4/drawing/frmLink.aspx`

## Site Shape

The site behaves like a four-level hierarchy:

1. Entry page
2. Category page
3. Subhead page
4. Drawing page with one or more downloadable files

Typical URL patterns:

- Entry page:
  - `frmLink.aspx`
- Category page:
  - `frmSubHead.aspx?c=...`
- Drawing listing page under a subhead:
  - `frmDrawing.aspx?s=...`
- Final drawing page:
  - `frmDrawingView.aspx?h=...`

## HTML Conventions Used By The Crawler

- Categories are discovered from links under elements with class `descrip2`.
- Subheads are discovered from links under elements with class `descrip1`.
- Drawing pages are discovered from links that contain `frmDrawingView`.
- Drawing descriptions are read from spans containing `lblDrawingDesc`.
- Breadcrumb-like labels may be read from spans containing `lblItem`.

## File Extraction Sources

Files are extracted from the final drawing page using three sources:

1. Regex matches for paths under `uploadedDrawing` or `uploaded`
2. `<object data="...">`
3. Hidden form fields such as `hndfilepath`

Only supported downloadable file extensions are kept:

- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`
- `.gif`
- `.bmp`
- `.tif`
- `.tiff`

The crawler intentionally ignores known static UI assets such as search and download icons.

## Site Quirks

- Some pages contain repeated or reused file URLs across different drawing pages.
- Some file names are generic, such as `scan.pdf`, and are only meaningful in page context.
- Some content is exposed through `<object data>` rather than standard download links.
- Certain older pages can use inconsistent naming or embedded path fragments.

## Exact Duplicate Source URLs Found In Production

The refreshed production metadata shows 4 exact duplicate source URLs reused across different drawing pages.

1. `22224NSV-SR-CG-01_coPART-20-38.pdf`
   - used by drawing ids 3568, 3570, and 3572
   - drawing names: `NSV-SR-CG-01`, `NSV-SR-CG-16`, `NSV-SR-CG-21`
   - same SHA-256, same ETag, same content length

2. `22224NSV-SR-CG-01_co_PART-1-19.pdf`
   - used by drawing ids 3569 and 3571
   - drawing names: `NSV-SR-CG-16`, `NSV-SR-CG-21`
   - same SHA-256, same ETag, same content length

3. `2233SV-SCR-BSG-01.pdf`
   - used by drawing ids 3736 and 3745
   - drawing names: `SV-SCR-CG-01`, `SV-SCR-BSG-01`
   - same SHA-256, same ETag, same content length

4. `scan.pdf`
   - used by drawing ids 4817 and 3769
   - drawing names: `RDSO/B-10434/11R` and `RDSO/B-10431/3`
   - same SHA-256, same ETag, same content length

These are not crawler duplicates. They are exact server-side file reuse cases where distinct drawing pages point to the same remote file URL.

## Operational Summary

- The site is stable enough for repeated incremental crawls.
- The crawler depends on current HTML classes and URL conventions.
- If the site layout changes, category/subhead/drawing discovery is the first place to check.