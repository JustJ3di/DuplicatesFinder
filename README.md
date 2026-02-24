# Duplicate File Finder (Python) + HTML Dashboard

A Python tool that scans a user-selected directory, detects **byte-identical duplicate files**, stores scan data locally in SQLite, and generates a **standalone HTML dashboard** to explore results.

## What counts as a duplicate?

Two files are considered duplicates if they have **exactly the same content** (byte-for-byte).  
File names and locations do **not** matter.

---

## How it works (pipeline)

Duplicate detection is done in **three stages** for both correctness and performance:

### 1) Scan (metadata collection)
The tool recursively walks the selected folder and collects file metadata:

- absolute path
- extension
- size
- modification timestamp (nanoseconds)

All metadata is stored in a **local SQLite database**.

Why store data in SQLite?
- It enables fast reporting queries without re-scanning.
- It allows caching computed hashes and invalidating them if a file changes.
- It supports large scans without keeping everything in memory.

### 2) Candidate filtering by size
If two files have different sizes, they cannot be identical.
So the tool first groups files by `size` and only continues with size groups where `COUNT(size) > 1`.

This stage is extremely fast and dramatically reduces the number of files that require hashing.

### 3) Quick hash (sampling)
For size-duplicate candidates, the tool computes a **quick hash** using samples from:
- beginning of the file
- middle of the file
- end of the file

This is a pre-filter to avoid fully hashing large files when they clearly differ.

### 4) Full hash (final proof)
For candidates that match on `(size, quick_hash)` with multiplicity > 1, the tool computes a **full hash** by streaming the entire file.

Files that share the same `full_hash` are considered duplicates.

---

## Output: HTML Dashboard

At the end, the tool generates `duplicate_report.html`, a standalone dashboard that contains:

- Summary metrics:
  - total examined files
  - number of distinct extensions
  - number of duplicate groups (by full hash)
  - number of files involved in duplicates
- Pie charts:
  - examined files by category (Media / Work documents / Text / Archives / etc.)
  - duplicate-involved files by category
- Detailed sections per extension:
  - each extension lists its duplicate groups and all file paths in each group

No backend required: open the HTML file in any browser.

---

## Project layout

Typical output folder:
- a timestamped directory containing:
  - `activity_db.db` (SQLite database)
  - `duplicate_report.html` (dashboard)

---

## Requirements

- Python 3.10+ recommended
- Standard library only (tkinter required for the folder dialog)

On some Linux distributions you may need to install Tkinter separately.

---

## Running the tool

```bash
python main.py
