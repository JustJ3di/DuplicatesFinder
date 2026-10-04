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
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from FolderHandler import FolderHandler
from FolderSelector import FolderSelector


def run_scan_with_progress(folder: Path, project_root: Path) -> None:
    updates: queue.Queue[tuple[str, str]] = queue.Queue()
    delete_decisions: queue.Queue[bool] = queue.Queue()

    window = tk.Tk()
    window.title("Duplicate File Finder")
    window.resizable(False, False)

    frame = ttk.Frame(window, padding=18)
    frame.grid(sticky="nsew")
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text="Scanning for duplicate files").grid(
        row=0, column=0, sticky="w", pady=(0, 8)
    )
    status = tk.StringVar(value="Preparing scan...")
    ttk.Label(frame, textvariable=status, wraplength=400).grid(
        row=1, column=0, sticky="w", pady=(0, 12)
    )
    progress = ttk.Progressbar(frame, mode="indeterminate", length=400)
    progress.grid(row=2, column=0, sticky="ew", pady=(0, 12))

    def scan() -> None:
        handler = None
        try:
            handler = FolderHandler(folder, project_root=project_root)
            updates.put(("status", "Scanning files..."))
            handler.explore()

            updates.put(("status", "Calculating quick hashes..."))
            handler.compute_quick_hashes_for_size_duplicates()

            updates.put(("status", "Checking duplicate candidates..."))
            handler.compute_full_hashes_for_quick_groups()

            updates.put(("status", "Generating report..."))
            report_path = handler.generate_html_report()

            duplicate_count = sum(
                len(paths) - 1 for _, paths in handler.find_duplicate_groups()
            )
            result_message = f"Report created: {report_path}"
            if duplicate_count:
                updates.put(("confirm_delete", str(duplicate_count)))
                if delete_decisions.get():
                    updates.put(("status", "Removing duplicate files..."))
                    deleted_paths, skipped_paths = handler.delete_duplicate_files()
                    result_message += f"\nDeleted {len(deleted_paths)} duplicate file(s)."
                    if skipped_paths:
                        result_message += (
                            f"\nSkipped {len(skipped_paths)} file(s) that changed "
                            "or could not be accessed."
                        )
                else:
                    result_message += "\nNo files were deleted."
        except Exception as error:
            updates.put(("error", str(error)))
        else:
            updates.put(("done", result_message))
        finally:
            if handler is not None:
                handler.close_db()

    worker = threading.Thread(target=scan, daemon=True)

    def close_window() -> None:
        if not worker.is_alive():
            window.destroy()

    close_button = ttk.Button(frame, text="Close", command=close_window, state="disabled")
    close_button.grid(row=3, column=0, sticky="e")
    window.protocol("WM_DELETE_WINDOW", close_window)

    def process_updates() -> None:
        try:
            while True:
                event, message = updates.get_nowait()
                if event == "status":
                    status.set(message)
                elif event == "confirm_delete":
                    should_delete = messagebox.askyesno(
                        "Delete duplicate files?",
                        f"Found {message} duplicate file(s). Delete them and keep one "
                        "copy per group? This cannot be undone.",
                        parent=window,
                    )
                    delete_decisions.put(should_delete)
                else:
                    progress.stop()
                    close_button.config(state="normal")
                    if event == "done":
                        status.set(f"Report created: {message}")
                    else:
                        status.set("Scan failed")
                        messagebox.showerror("Scan failed", message, parent=window)
        except queue.Empty:
            pass

        if worker.is_alive():
            window.after(100, process_updates)

    progress.start(12)
    worker.start()
    window.after(100, process_updates)
    window.mainloop()


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
    run_scan_with_progress(Path(path), Path(project_folder))


if __name__ == "__main__":
    main()