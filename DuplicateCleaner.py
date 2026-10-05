from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Tuple

from duplicate_selection import automatic_candidate_paths
from FolderHandler import FolderHandler


class DuplicateCleaner:
    PAGE_SIZE = 200

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
        self.rows: List[Tuple[int, str, bool]] = []
        self.selected_paths: set[str] = set()
        self.page = 0
        self.window: tk.Tk | None = None
        self.tree: ttk.Treeview | None = None
        self.count_label: ttk.Label | None = None
        self.page_label: ttk.Label | None = None

    def show(self) -> None:
        window = tk.Toplevel(self.parent) if self.parent is not None else tk.Tk()
        self.window = window
        window.title("Rimozione file duplicati")
        window.geometry("1000x700")
        window.minsize(700, 450)
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

        self.rows = [
            (group_number, path, path == paths[0])
            for group_number, (_, paths) in enumerate(self.groups, start=1)
            for path in paths
        ]

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("group", "selection", "path"),
            show="headings",
            selectmode="none",
        )
        self.tree.heading("group", text="Gruppo")
        self.tree.heading("selection", text="Elimina")
        self.tree.heading("path", text="Percorso file")
        self.tree.column("group", width=75, stretch=False, anchor="center")
        self.tree.column("selection", width=85, stretch=False, anchor="center")
        self.tree.column("path", width=780, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        vertical_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical_scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
        self.tree.bind("<Button-1>", self._toggle_clicked_row)
        self.tree.bind("<space>", self._toggle_focused_row)

        navigation = ttk.Frame(frame)
        navigation.pack(fill="x", pady=(6, 0))
        ttk.Button(navigation, text="Pagina precedente", command=self._previous_page).pack(side="left")
        self.page_label = ttk.Label(navigation)
        self.page_label.pack(side="left", padx=10)
        ttk.Button(navigation, text="Pagina successiva", command=self._next_page).pack(side="left")

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        self.count_label = ttk.Label(actions)
        self.count_label.pack(side="left")
        ttk.Button(
            actions,
            text="Selezione automatica",
            command=self._select_automatic_candidates,
        ).pack(side="left", padx=(12, 0))
        ttk.Button(
            actions,
            text="Deseleziona tutto",
            command=self._clear_selection,
        ).pack(side="left", padx=8)
        ttk.Button(actions, text="Elimina file selezionati", command=self._delete_selected).pack(side="right")
        self._render_page()
        if self.parent is None:
            window.mainloop()

    def _select_automatic_candidates(self) -> None:
        self.selected_paths = set(automatic_candidate_paths(self.groups))
        self._render_page()

    def _clear_selection(self) -> None:
        self.selected_paths.clear()
        self._render_page()

    def _previous_page(self) -> None:
        if self.page > 0:
            self.page -= 1
            self._render_page()

    def _next_page(self) -> None:
        if (self.page + 1) * self.PAGE_SIZE < len(self.rows):
            self.page += 1
            self._render_page()

    def _render_page(self) -> None:
        if self.tree is None:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

        start = self.page * self.PAGE_SIZE
        for row_index, (group_number, path, is_keeper) in enumerate(
            self.rows[start:start + self.PAGE_SIZE], start=start
        ):
            marker = "KEEP" if is_keeper else "[x]" if path in self.selected_paths else "[ ]"
            self.tree.insert("", "end", iid=f"file-{row_index}", values=(group_number, marker, path))

        page_count = max(1, (len(self.rows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self.page_label is not None:
            self.page_label.configure(text=f"Pagina {self.page + 1} di {page_count}")
        self._update_count()

    def _toggle_path(self, item: str) -> None:
        assert self.tree is not None
        group, marker, path = self.tree.item(item, "values")
        if marker == "KEEP":
            return
        if path in self.selected_paths:
            self.selected_paths.remove(path)
            marker = "[ ]"
        else:
            self.selected_paths.add(path)
            marker = "[x]"
        self.tree.set(item, "selection", marker)
        self._update_count()

    def _toggle_clicked_row(self, event: tk.Event) -> str | None:
        assert self.tree is not None
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.focus(item)
            self._toggle_path(item)
            return "break"
        return None

    def _toggle_focused_row(self, _event: tk.Event) -> str:
        assert self.tree is not None
        item = self.tree.focus()
        if item:
            self._toggle_path(item)
        return "break"

    def _update_count(self) -> None:
        if self.count_label is not None:
            self.count_label.configure(text=f"File selezionati: {len(self.selected_paths)}")

    def _delete_selected(self) -> None:
        assert self.window is not None
        selected = sorted(self.selected_paths)
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