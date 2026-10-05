from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from FolderHandler import FolderHandler
from duplicate_selection import automatic_candidate_paths


class DuplicateSelectionTests(unittest.TestCase):
    def test_automatic_candidates_match_previous_rule(self) -> None:
        groups = [
            ("first-hash", ["/files/a.txt", "/files/b.txt", "/files/c.txt"]),
            ("second-hash", ["/files/d.txt", "/files/e.txt"]),
        ]

        self.assertEqual(
            automatic_candidate_paths(groups),
            ["/files/b.txt", "/files/c.txt", "/files/e.txt"],
        )

    def test_backend_preserves_an_unselected_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan_folder = root / "scan"
            scan_folder.mkdir()
            files = [scan_folder / f"copy-{index}.txt" for index in range(3)]
            for path in files:
                path.write_bytes(b"identical content")

            handler = FolderHandler(scan_folder, project_root=root / "output")
            handler.explore()
            handler.compute_quick_hashes_for_size_duplicates()
            handler.compute_full_hashes_for_quick_groups()
            deleted, failures = handler.delete_duplicate_files([str(files[1])])

            self.assertEqual(deleted, [str(files[1].resolve())])
            self.assertEqual(failures, [])
            self.assertTrue(files[0].exists())
            self.assertTrue(files[2].exists())


if __name__ == "__main__":
    unittest.main()