# Duplicate File Finder (Python) + HTML Dashboard

A Python tool that scans a user-selected directory, detects **byte-identical duplicate files**, stores scan data in an in-memory B-tree, and generates a **standalone HTML dashboard** to explore results.

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

Metadata and hashes are held in a **B-tree in memory** for the duration of the scan. Nothing is cached between runs, and memory use grows with the number of scanned files.

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

The selected output directory contains `duplicate_report.html` directly. The application does not create a timestamped subfolder; if a report with that name already exists, it asks before replacing it.

The application has a main window for choosing both folders, starting scans, and viewing progress. If duplicates are found, a review window lets you choose copies to remove; all files start unselected, and one copy per group is always kept. Use **Selezione automatica** to select the copies the previous automatic rule would have removed, or **Deseleziona tutto** to clear the selection. The app asks for confirmation before deleting. The HTML report opens when the review closes. If no duplicates are found, the app displays a completion message and opens the report.

---

## Requirements

- Python 3.10+ recommended
- No third-party Python packages are needed to run the source code.
- Tkinter/Tcl/Tk is required for the folder selection and duplicate-cleanup dialogs. On Linux, install the Tk package provided by your distribution (for example, `python3-tk` on Debian/Ubuntu).

## Standalone Executables

The GitHub Releases page provides standalone executables for Linux x86_64, Windows x86_64, and macOS. Each executable bundles the Python runtime and the dependencies needed by the application, including Tk/Tcl from the corresponding build environment. Download the asset matching your operating system and run it; no Python installation is required.

The executable opens an interactive main window with folder selection and scan progress.

## Building Locally

Building requires Python 3.10+ with Tkinter/Tcl/Tk installed, plus the pinned PyInstaller build dependency:

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm --onefile --windowed --name duplicates-finder main.py
```

The executable is written to `dist/`. Build on each target operating system; PyInstaller does not cross-compile executables between operating systems.

GitHub Actions builds all three platform executables and publishes them as release assets whenever a version tag (`v*`) is pushed.

---

## Running the tool

```bash
python main.py
