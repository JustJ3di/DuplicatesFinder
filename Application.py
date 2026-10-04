from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from DuplicateCleaner import DuplicateCleaner
from FolderHandler import FolderHandler


logger = logging.getLogger(__name__)


def open_report(report_path: Path) -> bool:
    if sys.platform == "win32":
        try:
            os.startfile(str(report_path))
            return True
        except OSError:
            pass
    return webbrowser.open(report_path.as_uri())


class DuplicateFinderApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Duplicate File Finder")
        self.root.geometry("760x410")
        self.root.minsize(620, 380)

        self.scan_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status = tk.StringVar(value="Seleziona le cartelle per iniziare.")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.progress_lock = threading.Lock()
        self.pending_progress: tuple[str, int, int] | None = None
        self.last_report: Path | None = None

        self._build_ui()
        self.root.after(100, self._process_events)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=22)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Ricerca duplicati", font=("TkDefaultFont", 17, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Seleziona la cartella da analizzare e dove salvare il report.").pack(
            anchor="w", pady=(4, 18)
        )

        paths = ttk.Frame(frame)
        paths.pack(fill="x")
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="Cartella da analizzare").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self.scan_entry = ttk.Entry(paths, textvariable=self.scan_path)
        self.scan_entry.grid(row=0, column=1, sticky="ew", pady=6)
        self.scan_button = ttk.Button(paths, text="Sfoglia...", command=self._choose_scan_folder)
        self.scan_button.grid(row=0, column=2, padx=(8, 0), pady=6)

        ttk.Label(paths, text="Destinazione report").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.output_entry = ttk.Entry(paths, textvariable=self.output_path)
        self.output_entry.grid(row=1, column=1, sticky="ew", pady=6)
        self.output_button = ttk.Button(paths, text="Sfoglia...", command=self._choose_output_folder)
        self.output_button.grid(row=1, column=2, padx=(8, 0), pady=6)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(18, 14))
        self.start_button = ttk.Button(actions, text="Avvia scansione", command=self._start_scan)
        self.start_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Apri report", command=self._open_last_report, state="disabled")
        self.open_button.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=1, value=0)
        self.progress.pack(fill="x", pady=(2, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=700).pack(anchor="w")

    def _choose_scan_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Seleziona la cartella da analizzare", mustexist=True)
        if selected:
            self.scan_path.set(selected)

    def _choose_output_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Seleziona la destinazione del report", mustexist=True)
        if selected:
            self.output_path.set(selected)

    def _start_scan(self) -> None:
        scan_folder = Path(self.scan_path.get()).expanduser()
        output_folder = Path(self.output_path.get()).expanduser()
        if not scan_folder.is_dir():
            messagebox.showerror("Cartella non valida", "Seleziona una cartella esistente da analizzare.", parent=self.root)
            return
        if not output_folder.is_dir():
            messagebox.showerror("Destinazione non valida", "Seleziona una cartella esistente per il report.", parent=self.root)
            return

        report_path = output_folder / "duplicate_report.html"
        if report_path.exists() and not messagebox.askyesno(
            "Sovrascrivere il report?",
            f"Il file esiste già:\n{report_path}\n\nVuoi sostituirlo?",
            parent=self.root,
        ):
            return

        self._set_busy(True)
        self.progress.configure(maximum=1, value=0)
        self.status.set("Preparazione scansione...")
        worker = threading.Thread(
            target=self._scan_worker,
            args=(scan_folder, output_folder),
            daemon=True,
        )
        worker.start()

    def _scan_worker(self, scan_folder: Path, output_folder: Path) -> None:
        try:
            handler = FolderHandler(
                scan_folder,
                project_root=output_folder,
                progress_callback=self._record_progress,
            )
            handler.explore()
            handler.compute_quick_hashes_for_size_duplicates()
            handler.compute_full_hashes_for_quick_groups()
            groups = handler.find_duplicate_groups()
            report_path = handler.project_folder / "duplicate_report.html"
            if not groups:
                report_path = handler.generate_html_report()
            self.events.put(("complete", (handler, groups, report_path)))
        except Exception as exc:
            logger.exception("Scan failed")
            self.events.put(("error", exc))

    def _record_progress(self, phase: str, completed: int, total: int) -> None:
        with self.progress_lock:
            self.pending_progress = (phase, completed, total)

    def _process_events(self) -> None:
        with self.progress_lock:
            progress = self.pending_progress
            self.pending_progress = None
        if progress is not None:
            phase, completed, total = progress
            self.progress.configure(maximum=max(total, 1), value=completed if total else 1)
            self.status.set(f"{phase}: {completed:,} / {total:,}" if total else f"{phase}: nessun file candidato")

        try:
            event, payload = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self._process_events)
            return

        if event == "error":
            self._set_busy(False)
            self.status.set("Scansione non completata.")
            messagebox.showerror("Errore durante la scansione", str(payload), parent=self.root)
        elif event == "report_ready":
            self._set_busy(False)
            self.last_report = payload
            self.open_button.configure(state="normal")
            self.status.set(f"Report aggiornato: {payload}")
            self._open_report(payload)
        else:
            self._set_busy(False)
            handler, groups, report_path = payload
            if groups:
                self.status.set(
                    f"Trovati {len(groups)} gruppi duplicati in {len(handler.files):,} file. Report: {report_path}"
                )
                DuplicateCleaner(
                    handler,
                    groups,
                    parent=self.root,
                    on_close=lambda: self._generate_report_after_review(handler, report_path),
                ).show()
            else:
                self.last_report = report_path
                self.open_button.configure(state="normal")
                self.status.set(f"Nessun duplicato tra {len(handler.files):,} file. Report: {report_path}")
                messagebox.showinfo("Scansione completata", self.status.get(), parent=self.root)
                self._open_report(report_path)
        self.root.after(100, self._process_events)

    def _generate_report_after_review(self, handler: FolderHandler, report_path: Path) -> None:
        self._set_busy(True)
        self.status.set("Aggiornamento report dopo la revisione...")

        def generate() -> None:
            try:
                handler.generate_html_report(output_path=report_path)
            except Exception as exc:
                logger.exception("Report generation failed")
                self.events.put(("error", exc))
            else:
                self.events.put(("report_ready", report_path))

        threading.Thread(target=generate, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in (self.scan_entry, self.output_entry, self.scan_button, self.output_button, self.start_button):
            widget.configure(state=state)
        if busy:
            self.open_button.configure(state="disabled")

    def _open_last_report(self) -> None:
        if self.last_report is not None:
            self._open_report(self.last_report)

    def _open_report(self, report_path: Path) -> None:
        if not open_report(report_path):
            messagebox.showwarning(
                "Report non aperto",
                f"Apri manualmente questo file nel browser:\n{report_path}",
                parent=self.root,
            )

    def run(self) -> None:
        self.root.mainloop()