from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Tuple

from FolderHandler import FolderHandler


class DuplicateCleaner:
    def __init__(
        self,
        folder_handler: FolderHandler,
        groups: List[Tuple[str, List[str]]],
        *,
        parent: tk.Misc | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.folder_handler = folder_handler
        self.groups = groups
        self.parent = parent
        self.on_close = on_close
        self.selections: List[Tuple[str, tk.BooleanVar]] = []
        self.window: tk.Tk | None = None
        self.count_label: ttk.Label | None = None

    def show(self) -> None:
        window = tk.Toplevel(self.parent) if self.parent is not None else tk.Tk()
        self.window = window
        window.title("Rimozione file duplicati")
        window.geometry("900x620")
        window.minsize(600, 400)
        window.protocol("WM_DELETE_WINDOW", self._close)
        if self.parent is not None:
            window.transient(self.parent)
            window.grab_set()

        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Seleziona i file duplicati da eliminare. Una copia per gruppo viene conservata.",
            wraplength=850,
        ).pack(anchor="w", pady=(0, 10))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas)
        content.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for group_number, (full_hash, paths) in enumerate(self.groups, start=1):
            group_frame = ttk.LabelFrame(content, text=f"Gruppo {group_number} · {len(paths)} copie", padding=8)
            group_frame.pack(fill="x", expand=True, pady=5)
            ttk.Label(group_frame, text=f"Conserva: {paths[0]}", wraplength=820).pack(anchor="w", pady=(0, 4))
            for path in paths[1:]:
                variable = tk.BooleanVar(value=True)
                self.selections.append((path, variable))
                ttk.Checkbutton(
                    group_frame,
                    text=path,
                    variable=variable,
                    command=self._update_count,
                    wraplength=820,
                ).pack(anchor="w", fill="x")

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        self.count_label = ttk.Label(actions)
        self.count_label.pack(side="left")
        ttk.Button(actions, text="Elimina file selezionati", command=self._delete_selected).pack(side="right")
        self._update_count()
        if self.parent is None:
            window.mainloop()

    def _update_count(self) -> None:
        if self.count_label is not None:
            count = sum(variable.get() for _, variable in self.selections)
            self.count_label.configure(text=f"File selezionati: {count}")

    def _delete_selected(self) -> None:
        assert self.window is not None
        selected = [path for path, variable in self.selections if variable.get()]
        if not selected:
            messagebox.showinfo("Nessuna selezione", "Seleziona almeno un file da eliminare.", parent=self.window)
            return

        confirmed = messagebox.askyesno(
            "Conferma eliminazione",
            f"Eliminare definitivamente {len(selected)} file selezionati?",
            parent=self.window,
        )
        if not confirmed:
            return

        try:
            deleted, failures = self.folder_handler.delete_duplicate_files(selected)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Eliminazione non eseguita", str(exc), parent=self.window)
            return

        if failures:
            details = "\n".join(f"{path}: {error}" for path, error in failures)
            messagebox.showwarning(
                "Eliminazione parziale",
                f"Eliminati {len(deleted)} file.\n\nNon eliminati:\n{details}",
                parent=self.window,
            )
        else:
            messagebox.showinfo("Completato", f"Eliminati {len(deleted)} file.", parent=self.window)
        self._close()

    def _close(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        if self.on_close is not None:
            callback = self.on_close
            self.on_close = None
            callback()