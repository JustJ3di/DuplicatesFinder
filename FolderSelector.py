"""
Folder selection helper (Tkinter).

This module is intentionally small and focused:
- It provides a GUI dialog to select a directory path.
- It returns an absolute path and validates it.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog
from typing import Optional


class FolderSelector:
    """
    GUI folder picker based on Tkinter's `askdirectory()` dialog.

    Usage:
        selector = FolderSelector(title="Select a directory")
        folder_path = selector.select()
    """

    def __init__(self, title: str = "Select a folder") -> None:
        self.title = title

    def select(self) -> str:
        """
        Open a folder selection dialog and return the selected folder.

        Returns:
            Absolute path to the chosen folder.

        Raises:
            RuntimeError: If the user cancels or the selected path is invalid.
        """
        root: Optional[tk.Tk] = None
        try:
            # Create a minimal hidden root so the dialog can appear.
            root = tk.Tk()
            root.withdraw()
            root.update()

            folder_path = filedialog.askdirectory(
                parent=root,
                title=self.title,
                mustexist=True,
            )

            if not folder_path:
                raise RuntimeError("Folder selection was cancelled by the user.")

            folder_path = os.path.abspath(folder_path)
            if not os.path.isdir(folder_path):
                raise RuntimeError(f"Selected path is not a valid directory: {folder_path}")

            return folder_path

        except Exception as e:
            raise RuntimeError(f"Error during folder selection: {e}") from e

        finally:
            # Always attempt to destroy the root to avoid lingering Tk instances.
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass