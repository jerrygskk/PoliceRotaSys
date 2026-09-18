"""README 公開截圖工具的安全與候選資料契約。

⚠️ 測試資料只使用專案既有虛構姓名與匿名單位。
"""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from tools import capture_screenshots, seed_screenshot_data


class TestSeedScreenshotData(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-screenshot-")
        self.output = Path(self._temp.name) / "candidate.db"

    def tearDown(self):
        self._temp.cleanup()

    def test_root_database_is_rejected_even_when_force_is_requested(self):
        with self.assertRaisesRegex(ValueError, "正式資料庫"):
            seed_screenshot_data.validate_output_path(
                seed_screenshot_data.ROOT_DATABASE, force=True
            )

    def test_existing_output_requires_force(self):
        self.output.write_bytes(b"keep-me")

        with self.assertRaises(FileExistsError):
            seed_screenshot_data.validate_output_path(self.output, force=False)

        self.assertEqual(self.output.read_bytes(), b"keep-me")

    def test_build_database_has_two_adjacent_complete_months(self):
        summary = seed_screenshot_data.build_database(self.output)

        with closing(sqlite3.connect(self.output)) as conn, conn:
            marker = conn.execute(
                "SELECT value FROM App_Settings WHERE key = ?",
                (seed_screenshot_data.CANDIDATE_MARKER_KEY,),
            ).fetchone()[0]
            unit = conn.execute(
                "SELECT value FROM App_Settings WHERE key = 'unit_name'"
            ).fetchone()[0]
            plans = conn.execute(
                "SELECT year, month, origin, snapshot FROM Month_Plan "
                "ORDER BY year, month"
            ).fetchall()
            inactive = conn.execute(
                "SELECT COUNT(*) FROM Member WHERE active = 0"
            ).fetchone()[0]
            stored_digest = conn.execute(
                "SELECT value FROM App_Settings WHERE key = ?",
                (seed_screenshot_data.CANDIDATE_DIGEST_KEY,),
            ).fetchone()[0]
            actual_digest = seed_screenshot_data.candidate_digest(conn)

        self.assertEqual(marker, seed_screenshot_data.CANDIDATE_MARKER_VALUE)
        self.assertEqual(unit, "○○分局○○派出所")
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[1][2], "接續上月")
        self.assertTrue(plans[0][3])
        self.assertTrue(plans[1][3])
        self.assertEqual(inactive, 1)
        self.assertEqual(stored_digest, actual_digest)
        self.assertEqual(summary["digest"], actual_digest)
        self.assertEqual(summary["months"], [(row[0], row[1]) for row in plans])


class TestCaptureScreenshots(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-capture-")
        self.db_path = Path(self._temp.name) / "candidate.db"

    def tearDown(self):
        self._temp.cleanup()

    def test_database_argument_is_required(self):
        with self.assertRaises(SystemExit) as caught:
            capture_screenshots.parse_args(["--output", self._temp.name])

        self.assertEqual(caught.exception.code, 2)

    def test_root_database_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "正式資料庫"):
            capture_screenshots.validate_candidate_database(
                seed_screenshot_data.ROOT_DATABASE
            )

    def test_unmarked_database_is_rejected(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE App_Settings(key TEXT PRIMARY KEY, value TEXT)")

        with self.assertRaisesRegex(ValueError, "候選資料庫"):
            capture_screenshots.validate_candidate_database(self.db_path)

    def test_marker_present_but_incomplete_database_is_rejected(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE App_Settings(key TEXT PRIMARY KEY, value TEXT)")
            conn.executemany(
                "INSERT INTO App_Settings(key, value) VALUES (?, ?)",
                (
                    (
                        seed_screenshot_data.CANDIDATE_MARKER_KEY,
                        seed_screenshot_data.CANDIDATE_MARKER_VALUE,
                    ),
                    (seed_screenshot_data.CANDIDATE_DIGEST_KEY, "not-a-real-digest"),
                ),
            )

        with self.assertRaisesRegex(ValueError, "候選資料庫"):
            capture_screenshots.validate_candidate_database(self.db_path)

    def test_valid_seeded_database_is_accepted(self):
        seed_screenshot_data.build_database(self.db_path)

        self.assertEqual(
            capture_screenshots.validate_candidate_database(self.db_path),
            self.db_path.resolve(),
        )

    def test_tampered_member_is_rejected(self):
        seed_screenshot_data.build_database(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE Member SET name = '遭竄改假名' WHERE member_id = 1")

        with self.assertRaisesRegex(ValueError, "內容指紋不符"):
            capture_screenshots.validate_candidate_database(self.db_path)

    def test_tampered_snapshot_is_rejected(self):
        seed_screenshot_data.build_database(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE Month_Plan SET snapshot = '{}' WHERE plan_id = 1")

        with self.assertRaisesRegex(ValueError, "內容指紋不符"):
            capture_screenshots.validate_candidate_database(self.db_path)

    def test_tampered_unit_is_rejected(self):
        seed_screenshot_data.build_database(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE App_Settings SET value = '遭竄改單位' WHERE key = 'unit_name'"
            )

        with self.assertRaisesRegex(ValueError, "內容指紋不符"):
            capture_screenshots.validate_candidate_database(self.db_path)

    def test_screenshot_filenames_are_fixed(self):
        self.assertEqual(
            capture_screenshots.SCREENSHOT_FILENAMES,
            (
                "01-month-preview.png",
                "02-pairing.png",
                "03-rules.png",
                "04-group-dialog.png",
                "05-personnel.png",
                "06-maintenance.png",
                "07-help.png",
            ),
        )


if __name__ == "__main__":
    unittest.main()
