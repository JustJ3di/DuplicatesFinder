from __future__ import annotations

"""
Duplicate file finder + reporting.

This module provides:
- Fast content-based duplicate detection (byte-identical) using a 2-stage hashing pipeline:
  1) group by size
  2) quick hash on samples (start/middle/end)
  3) full hash on candidates (streamed)

- In-memory B-tree storage for scanned metadata and hashes.

- A standalone HTML dashboard for analyzing duplicates.

Design notes:
- We store `mtime_ns` and `size` and automatically invalidate cached hashes if either changes.
- We intentionally filter to a set of common extensions (configurable) to keep scans reasonable.
- We use `blake2b` because it is fast and secure enough for content identity checks.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import hashlib
import logging
import math
import os

from BTree import BTreeMap


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Defaults / Configuration
# ---------------------------------------------------------------------
COMMON_FILE_EXTENSIONS: List[str] = [
    # --- Text ---
    "txt", "md", "rtf", "csv", "tsv", "json", "xml", "yaml", "yml",
    "html", "htm", "css", "js", "log", "pdf",

    # --- Images ---
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "ico",

    # --- Audio ---
    "mp3", "wav", "aac", "flac", "ogg", "m4a",

    # --- Video ---
    "mp4", "avi", "mkv", "mov", "wmv", "flv", "webm",

    # --- Microsoft Office ---
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",

    # --- OpenDocument ---
    "odt", "ods", "odp",

    # --- Google shortcuts ---
    "gdoc", "gsheet", "gslides",

    # --- Apple iWork ---
    "pages", "numbers", "key",

    # --- Databases ---
    "sql", "db", "sqlite", "sqlite3",

    # --- Archives ---
    "zip", "rar", "7z", "tar", "gz",
]


# ---------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------
def compute_quick_hash(path: Path, sample_size: int = 64 * 1024) -> str:
    """
    Compute a *quick* hash by sampling file bytes: start + middle + end.

    Purpose:
    - A fast pre-filter to avoid hashing entire large files unnecessarily.
    - Not used as the final equality proof; only to reduce candidates for full hashing.

    Args:
        path: File path.
        sample_size: Size of each sample read in bytes.

    Returns:
        Hex digest string (blake2b, 128-bit).
    """
    st = path.stat()
    size = st.st_size
    h = hashlib.blake2b(digest_size=16)  # 128-bit

    with path.open("rb") as f:
        # start
        h.update(f.read(min(sample_size, size)))

        if size > sample_size:
            # middle
            mid_off = max(0, (size // 2) - (sample_size // 2))
            f.seek(mid_off, os.SEEK_SET)
            h.update(f.read(min(sample_size, max(0, size - mid_off))))

            # end
            end_off = max(0, size - sample_size)
            f.seek(end_off, os.SEEK_SET)
            h.update(f.read(min(sample_size, size - end_off)))

    return h.hexdigest()


def compute_full_hash(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    """
    Compute a *full* hash of the entire file by streaming it in chunks.

    This is the final identity check: if full_hash matches (same algorithm),
    we treat files as duplicates (byte-identical with overwhelming probability).

    Args:
        path: File path.
        chunk_size: Chunk size in bytes.

    Returns:
        Hex digest string (blake2b, 256-bit).
    """
    h = hashlib.blake2b(digest_size=32)  # 256-bit
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class FileRow:
    """A normalized view of a scanned file."""
    path: str
    ext: str
    size: int
    mtime_ns: int
    quick_hash: Optional[str] = None
    full_hash: Optional[str] = None


# ---------------------------------------------------------------------
# FolderHandler
# ---------------------------------------------------------------------
class FolderHandler:
    """
    Scan a folder, store file metadata and hashes in an in-memory B-tree, and generate an HTML report.

    Typical usage:
        fh = FolderHandler(Path("/some/folder"))
        fh.explore()
        fh.compute_quick_hashes_for_size_duplicates()
        fh.compute_full_hashes_for_quick_groups()
        report = fh.generate_html_report()
    """

    def __init__(
        self,
        folder: Path,
        *,
        allowed_extensions: Optional[Iterable[str]] = None,
        project_root: Optional[Path] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> None:
        """
        Args:
            folder: Root folder to scan.
            allowed_extensions: If provided, only these extensions are considered.
            project_root: Where to store the HTML report. Defaults to a timestamped folder next to this file.
            progress_callback: Optional callback receiving (phase, completed, total).
        """
        self.folder = folder.resolve()
        self._ext_set = set((allowed_extensions or COMMON_FILE_EXTENSIONS))

        artifact_root = project_root or Path(__file__).resolve().parent
        base = artifact_root / datetime.now().strftime("%Y%m%d_%H%M%S")
        base.mkdir(parents=True, exist_ok=True)
        self.project_folder = base
        self.progress_callback = progress_callback
        self.files: BTreeMap[str, FileRow] = BTreeMap()

    def _report_progress(self, phase: str, completed: int, total: int) -> None:
        if self.progress_callback is not None:
            self.progress_callback(phase, completed, total)

    def _upsert_file(self, row: FileRow) -> None:
        """
        Insert or update a file record, invalidating hashes when its metadata changes.
        """
        previous = self.files.get(row.path)
        if previous is not None and (previous.size, previous.mtime_ns) == (row.size, row.mtime_ns):
            row = replace(row, quick_hash=previous.quick_hash, full_hash=previous.full_hash)
        self.files[row.path] = row

    # -----------------------------
    # Scan / Explore
    # -----------------------------
    def explore(self) -> None:
        """
        Scan the folder recursively and store file metadata in the in-memory B-tree.

        Notes:
        - Uses os.walk for robustness and performance (avoids deep recursion).
        - Skips non-files and filters by allowed extensions.
        """
        logger.info("Scanning folder: %s", self.folder)
        total = sum(1 for path in self._iter_files(self.folder) if self._has_allowed_extension(path))
        completed = 0
        for file_path in self._iter_files(self.folder):
            if not self._has_allowed_extension(file_path):
                continue
            completed += 1
            try:
                st = file_path.stat()
            except (FileNotFoundError, PermissionError, OSError) as e:
                # A file might disappear mid-scan or be unreadable—skip gracefully.
                logger.debug("Skipping unreadable file %s: %s", file_path, e)
                self._report_progress("Scansione", completed, total)
                continue

            ext = (file_path.suffix[1:].lower() if file_path.suffix else "")
            self._upsert_file(
                FileRow(
                    path=str(file_path.resolve()), ext=ext,
                    size=int(st.st_size), mtime_ns=int(st.st_mtime_ns),
                )
            )
            self._report_progress("Scansione", completed, total)

        if total == 0:
            self._report_progress("Scansione", 0, 0)

    def _iter_files(self, root: Path) -> Iterable[Path]:
        """Yield file paths under root using os.walk (robust for deep trees)."""
        for dirpath, _dirnames, filenames in os.walk(root):
            base = Path(dirpath)
            for name in filenames:
                yield base / name

    def _has_allowed_extension(self, path: Path) -> bool:
        extension = path.suffix[1:].lower() if path.suffix else ""
        return bool(extension and extension in self._ext_set)

    # -----------------------------
    # Hash computation pipelines
    # -----------------------------
    def compute_quick_hashes_for_size_duplicates(self, limit: Optional[int] = None) -> int:
        """
        Compute quick_hash for files that are *potential* duplicates by size.

        Pipeline:
        1) Find file sizes with count > 1.
        2) For files with those sizes and quick_hash IS NULL, compute quick_hash.

        Args:
            limit: Optional max number of rows to process in this call.

        Returns:
            Number of updated rows.
        """
        size_counts: Dict[int, int] = {}
        records = list(self.files.values())
        for row in records:
            size_counts[row.size] = size_counts.get(row.size, 0) + 1
        candidates = [row for row in records if size_counts[row.size] > 1 and row.quick_hash is None]
        if limit is not None:
            candidates = candidates[:limit]

        updated = 0
        for completed, row in enumerate(candidates, start=1):
            path = Path(row.path)
            try:
                qh = compute_quick_hash(path)
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.debug("Quick-hash failed for %s: %s", path, e)
            else:
                self.files[row.path] = replace(row, quick_hash=qh)
                updated += 1
            self._report_progress("Hash rapido", completed, len(candidates))
        if not candidates:
            self._report_progress("Hash rapido", 0, 0)
        return updated

    def compute_full_hashes_for_quick_groups(self, limit: Optional[int] = None) -> int:
        """
        Compute full_hash for files that match on (size, quick_hash) with multiplicity > 1.

        Pipeline:
        1) Find (size, quick_hash) groups with count > 1.
        2) For files in those groups with full_hash IS NULL, compute full_hash.

        Args:
            limit: Optional max number of rows to process in this call.

        Returns:
            Number of updated rows.
        """
        quick_groups: Dict[Tuple[int, str], List[FileRow]] = {}
        for row in self.files.values():
            if row.quick_hash is not None:
                quick_groups.setdefault((row.size, row.quick_hash), []).append(row)
        candidates = [
            row
            for group in quick_groups.values() if len(group) > 1
            for row in group if row.full_hash is None
        ]
        if limit is not None:
            candidates = candidates[:limit]

        updated = 0
        for completed, row in enumerate(candidates, start=1):
            path = Path(row.path)
            try:
                fh = compute_full_hash(path)
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.debug("Full-hash failed for %s: %s", path, e)
            else:
                self.files[row.path] = replace(row, full_hash=fh)
                updated += 1
            self._report_progress("Hash completo", completed, len(candidates))
        if not candidates:
            self._report_progress("Hash completo", 0, 0)
        return updated

    def find_duplicate_groups(self) -> List[Tuple[str, List[str]]]:
        """
        Return duplicate groups identified by full_hash.

        Returns:
            List of tuples:
                [(full_hash, [path1, path2, ...]), ...]
        """
        groups: Dict[str, List[str]] = {}
        for row in self.files.values():
            if row.full_hash is not None:
                groups.setdefault(row.full_hash, []).append(row.path)
        return [(full_hash, paths) for full_hash, paths in groups.items() if len(paths) > 1]

    def delete_duplicate_files(self, paths: Iterable[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
        """Delete selected scanned duplicates while retaining one unchanged copy per group."""
        groups = self.find_duplicate_groups()
        requested = {Path(path).resolve() for path in paths}
        if not requested:
            return [], []

        root = self.folder.resolve()
        path_groups: Dict[Path, Tuple[str, List[Path]]] = {}
        for full_hash, group_paths in groups:
            resolved_group = [Path(path).resolve() for path in group_paths]
            for path in resolved_group:
                path_groups[path] = (full_hash, resolved_group)

        selected_by_hash: Dict[str, List[Path]] = {}
        for path in requested:
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Il file non appartiene alla cartella analizzata: {path}") from exc
            if path not in path_groups:
                raise ValueError(f"Il file non risulta in un gruppo di duplicati: {path}")
            full_hash, _ = path_groups[path]
            selected_by_hash.setdefault(full_hash, []).append(path)

        for full_hash, selected in selected_by_hash.items():
            group_paths = path_groups[selected[0]][1]
            if len(selected) >= len(group_paths):
                raise ValueError("La selezione eliminerebbe tutte le copie di un gruppo.")

            for path in selected:
                if not path.is_file() or compute_full_hash(path) != full_hash:
                    raise ValueError(f"Il file è stato modificato o non è più disponibile: {path}")

            remaining = [path for path in group_paths if path not in selected]
            if not any(path.is_file() and compute_full_hash(path) == full_hash for path in remaining):
                raise ValueError("Non è rimasta una copia valida del gruppo selezionato.")

        deleted: List[str] = []
        failures: List[Tuple[str, str]] = []
        for path in requested:
            try:
                path.unlink()
                deleted.append(str(path))
            except OSError as exc:
                failures.append((str(path), str(exc)))
        deleted_paths = set(deleted)
        if deleted_paths:
            remaining_records = [
                (path, row) for path, row in self.files.items()
                if path not in deleted_paths
            ]
            self.files = BTreeMap()
            for path, row in remaining_records:
                self.files[path] = row
        return deleted, failures

    # -----------------------------
    # Reporting helpers
    # -----------------------------
    @staticmethod
    def _ext_category(ext: str) -> str:
        """
        Map extensions to macro-categories used by the dashboard.

        The goal is interpretability: users want to understand where duplicates come from
        (media vs work documents vs archives, etc.), not just raw extensions.
        """
        ext = (ext or "").lower()

        text = {"txt", "md", "rtf", "csv", "tsv", "json", "xml", "yaml", "yml", "html", "htm", "css", "js", "log", "pdf"}
        images = {"jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "svg", "ico"}
        audio = {"mp3", "wav", "aac", "flac", "ogg", "m4a"}
        video = {"mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"}

        office = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}
        opendoc = {"odt", "ods", "odp"}
        google = {"gdoc", "gsheet", "gslides"}
        iwork = {"pages", "numbers", "key"}

        db = {"sql", "db", "sqlite", "sqlite3"}
        archives = {"zip", "rar", "7z", "tar", "gz"}

        if ext in images or ext in audio or ext in video:
            return "Media"
        if ext in office or ext in opendoc or ext in google or ext in iwork:
            return "Work documents"
        if ext in text:
            return "Text"
        if ext in db:
            return "Databases"
        if ext in archives:
            return "Archives"
        return "Other"

    @staticmethod
    def _pie_svg(counts: Dict[str, int], title: str, size: int = 220) -> str:
        """
        Inline SVG pie chart (no external dependencies).

        Args:
            counts: Mapping label -> count
            title: Chart title
            size: SVG width/height

        Returns:
            HTML string containing chart + legend.
        """
        total = sum(counts.values())
        if total <= 0:
            return (
                f"<div class='chart'>"
                f"<div class='chart-title'>{escape(title)}</div>"
                f"<div class='muted'>No data</div></div>"
            )

        palette = [
            "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
            "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
        ]

        cx = cy = size / 2
        r = size * 0.42
        start_angle = -math.pi / 2

        def polar(angle: float) -> Tuple[float, float]:
            return (cx + r * math.cos(angle), cy + r * math.sin(angle))

        def arc_path(a0: float, a1: float) -> str:
            x0, y0 = polar(a0)
            x1, y1 = polar(a1)
            large = 1 if (a1 - a0) > math.pi else 0
            return (
                f"M {cx:.2f} {cy:.2f} "
                f"L {x0:.2f} {y0:.2f} "
                f"A {r:.2f} {r:.2f} 0 {large} 1 {x1:.2f} {y1:.2f} Z"
            )

        items = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        svg_parts = [
            f"<svg width='{size}' height='{size}' viewBox='0 0 {size} {size}' role='img' aria-label='{escape(title)}'>"
        ]
        legend_parts = ["<div class='legend'>"]

        angle = start_angle
        for i, (label, val) in enumerate(items):
            if val <= 0:
                continue
            frac = val / total
            a0 = angle
            a1 = angle + frac * 2 * math.pi
            color = palette[i % len(palette)]
            svg_parts.append(f"<path d='{arc_path(a0, a1)}' fill='{color}'></path>")
            pct = 100.0 * frac
            legend_parts.append(
                "<div class='legend-row'>"
                f"<span class='swatch' style='background:{color}'></span>"
                f"<span class='legend-label'>{escape(label)}</span>"
                f"<span class='legend-val'>{val} ({pct:.1f}%)</span>"
                "</div>"
            )
            angle = a1

        svg_parts.append("</svg>")
        legend_parts.append("</div>")

        return (
            "<div class='chart'>"
            f"<div class='chart-title'>{escape(title)}</div>"
            f"{''.join(svg_parts)}"
            f"{''.join(legend_parts)}"
            "</div>"
        )

    def _fetch_examined_counts_by_category(self) -> Dict[str, int]:
        """Counts examined files by macro-category."""
        counts: Dict[str, int] = {}
        for row in self.files.values():
            category = self._ext_category(row.ext)
            counts[category] = counts.get(category, 0) + 1
        return counts

    def _fetch_duplicate_file_rows(self) -> List[Tuple[str, str, str]]:
        """
        Return (full_hash, ext, path) rows only for files in duplicate groups.
        """
        duplicate_hashes = {full_hash for full_hash, _ in self.find_duplicate_groups()}
        rows = [
            (row.full_hash, row.ext, row.path)
            for row in self.files.values()
            if row.full_hash in duplicate_hashes
        ]
        return sorted(rows, key=lambda row: (row[1], row[0], row[2]))

    # -----------------------------
    # HTML report
    # -----------------------------
    def generate_html_report(self, output_path: Optional[Path] = None) -> Path:
        """
        Generate a standalone HTML dashboard.

        The report contains:
        - Summary metrics (file count, extension count, duplicate groups, files involved)
        - Pie charts:
          - distribution of examined files by category
          - distribution of duplicate-involved files by category
        - Detailed sections per extension:
          - each extension lists its duplicate groups and file paths

        Args:
            output_path: Where to write the HTML. Defaults to <project_folder>/duplicate_report.html

        Returns:
            Path to the generated HTML.
        """
        if output_path is None:
            output_path = self.project_folder / "duplicate_report.html"
        output_path = output_path.resolve()

        records = list(self.files.values())
        total_files = len(records)
        distinct_exts = len({row.ext for row in records})
        dup_groups = len(self.find_duplicate_groups())

        examined_by_cat = self._fetch_examined_counts_by_category()

        dup_rows = self._fetch_duplicate_file_rows()
        dup_by_cat: Dict[str, int] = {}
        dup_map: Dict[str, Dict[str, List[str]]] = {}  # ext -> full_hash -> [paths]

        for fh, ext, path in dup_rows:
            cat = self._ext_category(ext)
            dup_by_cat[cat] = dup_by_cat.get(cat, 0) + 1
            dup_map.setdefault(ext, {}).setdefault(fh, []).append(path)

        # Extension sections (only extensions that actually have duplicates)
        ext_sections: List[str] = []
        for ext in sorted(dup_map.keys()):
            groups = dup_map[ext]
            group_blocks: List[str] = []

            # enumerate groups for this extension for nicer readability
            for idx, (fh, paths) in enumerate(groups.items(), start=1):
                safe_paths = "".join(f"<li><code>{escape(p)}</code></li>" for p in paths)
                group_blocks.append(
                    f"""
                    <details class="group">
                      <summary>
                        <span class="gtitle">Group {idx}</span>
                        <span class="muted">hash: <code>{escape(fh[:16])}…</code> · files: <b>{len(paths)}</b></span>
                      </summary>
                      <ul class="paths">{safe_paths}</ul>
                    </details>
                    """
                )

            ext_sections.append(
                f"""
                <section class="ext-section">
                  <h2>.{escape(ext)} <span class="pill">{len(groups)} groups</span></h2>
                  {''.join(group_blocks)}
                </section>
                """
            )

        chart_examined = self._pie_svg(examined_by_cat, "Examined files by category")
        chart_dup = self._pie_svg(dup_by_cat, "Duplicate-involved files by category")

        folder_str = str(self.folder)
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Duplicate Report</title>
  <style>
    :root {{
      --bg: #0b0f14;
      --card: #101826;
      --text: #e8eef6;
      --muted: #9fb0c3;
      --line: rgba(255,255,255,.08);
      --pill: rgba(255,255,255,.10);
      --accent: #7aa2ff;
      --code: rgba(255,255,255,.07);
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      background: var(--bg);
      color: var(--text);
    }}
    .container {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 22px 16px 48px;
    }}
    h1 {{
      margin: 0 0 8px 0;
      font-size: 22px;
      letter-spacing: .2px;
    }}
    .muted {{ color: var(--muted); }}
    .top {{
      background: linear-gradient(180deg, rgba(122,162,255,.18), transparent 60%);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px 16px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-top: 12px;
    }}
    .stat {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 12px;
    }}
    .stat .k {{ font-size: 12px; color: var(--muted); }}
    .stat .v {{ font-size: 18px; margin-top: 6px; }}
    .charts {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-top: 14px;
    }}
    .chart {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
    }}
    .chart-title {{
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .legend {{
      margin-top: 10px;
      display: grid;
      gap: 6px;
    }}
    .legend-row {{
      display: grid;
      grid-template-columns: 14px 1fr auto;
      gap: 8px;
      align-items: center;
      font-size: 12px;
      color: var(--text);
    }}
    .swatch {{
      width: 12px; height: 12px;
      border-radius: 3px;
      display: inline-block;
      border: 1px solid rgba(255,255,255,.12);
    }}
    .legend-val {{ color: var(--muted); }}
    .content {{
      margin-top: 18px;
    }}
    .ext-section {{
      margin-top: 18px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 14px;
    }}
    h2 {{
      margin: 0 0 10px 0;
      font-size: 16px;
    }}
    .pill {{
      display: inline-block;
      margin-left: 8px;
      font-size: 12px;
      padding: 3px 8px;
      border-radius: 999px;
      background: var(--pill);
      color: var(--muted);
      border: 1px solid var(--line);
      vertical-align: middle;
    }}
    details.group {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
      margin-top: 10px;
    }}
    details.group:first-of-type {{
      border-top: none;
      padding-top: 0;
      margin-top: 0;
    }}
    summary {{
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      list-style: none;
    }}
    summary::-webkit-details-marker {{ display: none; }}
    .gtitle {{
      font-weight: 600;
      color: var(--accent);
    }}
    code {{
      background: var(--code);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 2px 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      word-break: break-all;
    }}
    ul.paths {{
      margin: 10px 0 0 0;
      padding-left: 18px;
      color: var(--text);
    }}
    li {{
      margin: 6px 0;
    }}
    @media (max-width: 900px) {{
      .stats {{ grid-template-columns: repeat(2, 1fr); }}
      .charts {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="top">
      <h1>Duplicate Files Report</h1>
      <div class="muted">Scanned folder: <code>{escape(folder_str)}</code></div>

      <div class="stats">
        <div class="stat">
          <div class="k"># examined files</div>
          <div class="v">{total_files}</div>
        </div>
        <div class="stat">
          <div class="k"># distinct extensions</div>
          <div class="v">{distinct_exts}</div>
        </div>
        <div class="stat">
          <div class="k"># duplicate groups</div>
          <div class="v">{dup_groups}</div>
        </div>
        <div class="stat">
          <div class="k"># files involved in duplicates</div>
          <div class="v">{len(dup_rows)}</div>
        </div>
      </div>

      <div class="charts">
        {chart_examined}
        {chart_dup}
      </div>
    </div>

    <div class="content">
      <h2 style="margin-top:18px;">Duplicates by extension</h2>
      <div class="muted">
        Each section lists duplicate groups (by full hash) and the file paths in the group.
      </div>
      {''.join(ext_sections) if ext_sections else "<div class='muted' style='margin-top:12px;'>No duplicates found.</div>"}
    </div>
  </div>
</body>
</html>
"""
        output_path.write_text(html, encoding="utf-8")
        return output_path