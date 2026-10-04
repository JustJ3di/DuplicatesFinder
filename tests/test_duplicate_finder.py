from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from FolderHandler import FolderHandler, compute_full_hash, compute_quick_hash


class HashTests(unittest.TestCase):
    def test_hashes_match_for_identical_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            content = b"same content\n"
            first.write_bytes(content)
            second.write_bytes(content)

            self.assertEqual(compute_quick_hash(first), compute_quick_hash(second))
            self.assertEqual(compute_full_hash(first), compute_full_hash(second))

    def test_full_hash_detects_changes_outside_quick_hash_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.bin"
            second = root / "second.bin"
            content = bytearray(b"a" * (512 * 1024))
            changed_content = bytearray(content)
            changed_content[128 * 1024] = ord("b")
            first.write_bytes(content)
            second.write_bytes(changed_content)

            self.assertEqual(compute_quick_hash(first), compute_quick_hash(second))
            self.assertNotEqual(compute_full_hash(first), compute_full_hash(second))


class DuplicateFinderIntegrationTests(unittest.TestCase):
    def test_scan_hashes_groups_and_generates_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan_folder = root / "scan-input"
            nested_folder = scan_folder / "nested"
            output_root = root / "scan-output"
            nested_folder.mkdir(parents=True)

            first_group_content = b"duplicate-one-content\n"
            second_group_content = b"duplicate-two-content\n"
            same_size_different_content = b"duplicate-abc-content\n"

            first_group_a = scan_folder / "group-one-a.txt"
            first_group_b = nested_folder / "group-one-b.txt"
            second_group_a = scan_folder / "group-two-a.txt"
            second_group_b = nested_folder / "group-two-b.txt"
            first_group_paths = {first_group_a, first_group_b}
            second_group_paths = {second_group_a, second_group_b}
            files = {
                first_group_a: first_group_content,
                first_group_b: first_group_content,
                second_group_a: second_group_content,
                second_group_b: second_group_content,
                scan_folder / "same-size-different.txt": same_size_different_content,
                scan_folder / "unique.txt": b"unique file with a different size",
                scan_folder / "ignored.bin": first_group_content,
            }
            for path, content in files.items():
                path.write_bytes(content)

            handler = FolderHandler(scan_folder, project_root=output_root)
            try:
                handler.explore()

                self.assertEqual(handler.compute_quick_hashes_for_size_duplicates(), 5)
                self.assertEqual(handler.compute_full_hashes_for_quick_groups(), 4)

                actual_groups = {
                    frozenset(Path(path) for path in paths)
                    for _, paths in handler.find_duplicate_groups()
                }
                expected_groups = {
                    frozenset(path.resolve() for path in first_group_paths),
                    frozenset(path.resolve() for path in second_group_paths),
                }
                self.assertEqual(actual_groups, expected_groups)

                report_path = handler.generate_html_report()
                self.assertTrue(report_path.is_file())
                report = report_path.read_text(encoding="utf-8")
                for path in first_group_paths | second_group_paths:
                    self.assertIn(path.name, report)
                self.assertNotIn("same-size-different.txt", report)
                self.assertNotIn("ignored.bin", report)
            finally:
                handler.close_db()


if __name__ == "__main__":
    unittest.main()