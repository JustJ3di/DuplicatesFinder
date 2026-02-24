"""
CLI entry point.

This script:
1) asks the user for a folder,
2) scans and stores file metadata into SQLite,
3) computes quick hashes for same-size candidates,
4) computes full hashes for quick-hash candidate groups,
5) generates an HTML dashboard.
"""

from __future__ import annotations

import logging
from pathlib import Path

from FolderHandler import FolderHandler
from FolderSelector import FolderSelector


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
    fh = FolderHandler(Path(path), project_root=Path(project_folder))
    try:
        fh.explore()

        # Hash pipeline:
        # size duplicates -> quick hash -> full hash.
        fh.compute_quick_hashes_for_size_duplicates()
        fh.compute_full_hashes_for_quick_groups()

        report_path = fh.generate_html_report()
        print("Report created:", report_path)

    finally:
        # Ensure DB resources are always released even if something goes wrong.
        fh.close_db()


if __name__ == "__main__":
    main()