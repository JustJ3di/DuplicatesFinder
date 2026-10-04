"""
CLI entry point.

This script:
1) asks the user for a folder,
2) scans and stores file metadata in an in-memory B-tree,
3) computes quick hashes for same-size candidates,
4) computes full hashes for quick-hash candidate groups,
5) generates an HTML dashboard.
"""

from __future__ import annotations

import logging
import os
import sys
import webbrowser
from pathlib import Path
from tkinter import messagebox

from FolderHandler import FolderHandler
from FolderSelector import FolderSelector
from DuplicateCleaner import DuplicateCleaner


def show_progress(phase: str, completed: int, total: int) -> None:
    if total == 0:
        print(f"{phase}: nessun file da elaborare")
        return

    width = 32
    percent = completed / total
    filled = int(width * percent)
    bar = "#" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r{phase}: [{bar}] {percent:6.1%} ({completed}/{total})")
    if completed >= total:
        sys.stdout.write("\n")
    sys.stdout.flush()


def open_report(report_path: Path) -> bool:
    if sys.platform == "win32":
        try:
            os.startfile(str(report_path))
            return True
        except OSError:
            pass
    return webbrowser.open(report_path.as_uri())


def main() -> None:
    # Basic logging configuration for a small script.
    # If you later package this, consider using a richer configuration.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    print("Select the folder to scan...")
    selector = FolderSelector(title="Select the folder to scan")
    path = selector.select()
    print("Select where to save the results...")
    project_folder = FolderSelector(title="Select where to save the results")
    project_folder = project_folder.select()
    fh = FolderHandler(
        Path(path),
        project_root=Path(project_folder),
        progress_callback=show_progress,
    )
    fh.explore()

    # Hash pipeline: same-size candidates -> quick hash -> full hash.
    fh.compute_quick_hashes_for_size_duplicates()
    fh.compute_full_hashes_for_quick_groups()

    duplicate_groups = fh.find_duplicate_groups()
    if duplicate_groups:
        DuplicateCleaner(fh, duplicate_groups).show()
    report_path = fh.generate_html_report()
    if not duplicate_groups:
        messagebox.showinfo(
            "Scansione completata",
            f"Nessun file duplicato trovato tra i {len(fh.files)} file analizzati.\n\n"
            f"Report: {report_path}",
        )
    if not open_report(report_path):
        messagebox.showwarning(
            "Report non aperto",
            f"Apri manualmente questo report nel browser:\n{report_path}",
        )
    print("Report created:", report_path)


if __name__ == "__main__":
    main()