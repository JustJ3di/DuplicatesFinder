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


def confirm_duplicate_deletion(
    parent: tk.Tk,
    duplicate_groups: list[tuple[str, list[str]]],
) -> bool:
    duplicate_count = sum(len(paths) - 1 for _, paths in duplicate_groups)
    dialog = tk.Toplevel(parent)
    dialog.title("Review duplicate files")
    dialog.geometry("900x460")
    dialog.minsize(680, 320)
    dialog.transient(parent)

    frame = ttk.Frame(dialog, padding=14)
    frame.grid(row=0, column=0, sticky="nsew")
    dialog.columnconfigure(0, weight=1)
    dialog.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)

    ttk.Label(
        frame,
        text=(
            f"{duplicate_count} duplicate file(s) are marked for deletion. "
            "One file in each group will be kept."
        ),
        wraplength=850,
    ).grid(row=0, column=0, sticky="w", pady=(0, 10))

    table_frame = ttk.Frame(frame)
    table_frame.grid(row=1, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)

    tree = ttk.Treeview(
        table_frame,
        columns=("group", "action", "path"),
        show="headings",
        height=14,
    )
    tree.heading("group", text="Group")
    tree.heading("action", text="Action")
    tree.heading("path", text="File path")
    tree.column("group", width=70, stretch=False)
    tree.column("action", width=90, stretch=False)
    tree.column("path", width=680, stretch=True)
    tree.grid(row=0, column=0, sticky="nsew")

    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    for group_number, (_, paths) in enumerate(duplicate_groups, start=1):
        ordered_paths = sorted(paths)
        if not ordered_paths:
            continue
        tree.insert("", "end", values=(group_number, "KEEP", ordered_paths[0]))
        for path in ordered_paths[1:]:
            tree.insert("", "end", values=(group_number, "DELETE", path))

    result = tk.BooleanVar(master=dialog, value=False)

    def close_dialog(confirmed: bool = False) -> None:
        result.set(confirmed)
        dialog.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=2, column=0, sticky="e", pady=(12, 0))
    ttk.Button(buttons, text="Cancel", command=close_dialog).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(
        buttons,
        text="Delete marked files",
        command=lambda: close_dialog(True),
    ).grid(row=0, column=1)

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)
    dialog.grab_set()
    dialog.wait_window()
    return result.get()


def run_scan_with_progress(folder: Path, project_root: Path) -> None:
    updates: queue.Queue[tuple[str, object]] = queue.Queue()
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

            duplicate_groups = [
                (full_hash, sorted(paths))
                for full_hash, paths in handler.find_duplicate_groups()
            ]
            duplicate_count = sum(len(paths) - 1 for _, paths in duplicate_groups)
            result_message = f"Report created: {report_path}"
            if duplicate_count:
                updates.put(("confirm_delete", duplicate_groups))
                if delete_decisions.get():
                    updates.put(("status", "Removing duplicate files..."))
                    deleted_paths, skipped_paths = handler.delete_duplicate_files(
                        duplicate_groups
                    )
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
                    status.set(str(message))
                elif event == "confirm_delete":
                    assert isinstance(message, list)
                    should_delete = confirm_duplicate_deletion(window, message)
                    delete_decisions.put(should_delete)
                else:
                    progress.stop()
                    close_button.config(state="normal")
                    if event == "done":
                        status.set(str(message))
                    else:
                        status.set("Scan failed")
                        messagebox.showerror("Scan failed", str(message), parent=window)
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