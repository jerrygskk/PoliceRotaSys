# -*- coding: utf-8 -*-
"""lib/db_backup.py：GFS 輪替、手動備份、損毀偵測、壓縮（暫存資料夾，不碰真實資料）。"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import main
from lib import db_backup
from lib.db_utils import KEY_BACKUP_SECOND_DIR, opened, set_setting


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-backup-")
        self.dir = Path(self._temp.name)
        self.db = str(self.dir / "dbfile.db")
        main.prepare_database(self.db)
        db_backup._LAST_ERRORS.clear()

    def tearDown(self):
        db_backup._LAST_ERRORS.clear()
        self._temp.cleanup()

    def backups(self, folder=None):
        return sorted(os.listdir(folder or db_backup.backup_dir(self.db)))


class TestGfsRules(unittest.TestCase):
    def test_file_names(self):
        d = date(2026, 9, 17)
        self.assertEqual(db_backup.daily_filename(d), "dbfile_backup_day_20260917.db")
        self.assertEqual(db_backup.weekly_filename(d), "dbfile_backup_week_20260917.db")
        self.assertEqual(db_backup.monthly_filename(d), "dbfile_backup_month_20260917.db")
        self.assertEqual(db_backup.manual_filename(datetime(2026, 9, 17, 15, 30)),
                         "dbfile_backup_manual_20260917_1530.db")

    def test_parse_ignores_other_files(self):
        names = ["dbfile_backup_day_20260917.db", "dbfile_backup_day_2026091.db",
                 "dbfile_backup_manual_20260917_1530.db", "dbfile_backup_day_20261399.db"]
        self.assertEqual(db_backup.parse_daily_dates(names), [date(2026, 9, 17)])

    def test_due_rules(self):
        today = date(2026, 9, 17)   # 週四
        self.assertFalse(db_backup.is_daily_due([today], today))
        self.assertTrue(db_backup.is_daily_due([date(2026, 9, 16)], today))
        self.assertFalse(db_backup.is_weekly_due([date(2026, 9, 14)], today))  # 同週一
        self.assertTrue(db_backup.is_weekly_due([date(2026, 9, 13)], today))   # 上週日
        self.assertFalse(db_backup.is_monthly_due([date(2026, 9, 1)], today))
        self.assertTrue(db_backup.is_monthly_due([date(2026, 8, 31)], today))

    def test_prune_keeps_the_newest(self):
        dates = [date(2026, 9, d) for d in (5, 1, 3, 2, 4)]
        self.assertEqual(db_backup.prune_targets(dates, 3), [date(2026, 9, 1), date(2026, 9, 2)])
        self.assertEqual(db_backup.prune_targets(dates, 5), [])


class TestAutoBackup(_TempDbCase):
    def test_first_open_makes_day_week_month(self):
        db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17, 8, 0))
        self.assertEqual(self.backups(), [
            "dbfile_backup_day_20260917.db",
            "dbfile_backup_month_20260917.db",
            "dbfile_backup_week_20260917.db",
        ])

    def test_second_open_same_day_adds_nothing(self):
        db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17, 8, 0))
        db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17, 17, 0))
        self.assertEqual(len(self.backups()), 3)

    def test_daily_backups_are_pruned_to_seven(self):
        for day in range(1, 11):
            db_backup.run_auto_backup(self.db, now=datetime(2026, 9, day))
        daily = db_backup.parse_daily_dates(self.backups())
        self.assertEqual(len(daily), db_backup.DAILY_KEEP)
        self.assertEqual(min(daily), date(2026, 9, 4))

    def test_backup_is_a_readable_copy(self):
        db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17))
        copy = os.path.join(db_backup.backup_dir(self.db), "dbfile_backup_day_20260917.db")
        conn = sqlite3.connect(copy)   # ⚠️ with 只管交易不會關連線，Windows 上檔案刪不掉
        try:
            names = {r[0] for r in conn.execute("SELECT key FROM App_Settings")}
        finally:
            conn.close()
        self.assertIn("unit_name", names)

    def test_extra_dir_gets_its_own_copy(self):
        extra = str(self.dir / "offsite")
        db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17), extra_dirs=[extra])
        self.assertEqual(len(self.backups(extra)), 3)

    def test_broken_extra_dir_does_not_stop_main_backup(self):
        blocker = self.dir / "not_a_folder"
        blocker.write_text("x")
        extra = str(blocker)
        with mock.patch("logging.error"):
            db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17), extra_dirs=[extra])
        self.assertEqual(len(self.backups()), 3)
        self.assertIsNotNone(db_backup.last_backup_error(extra))

    def test_failed_write_leaves_no_temp_file(self):
        dest = os.path.join(str(self.dir), "out.db")
        with mock.patch("os.replace", side_effect=PermissionError("locked")), \
             mock.patch("logging.error"):
            self.assertFalse(db_backup.do_backup(self.db, dest))
        self.assertFalse(os.path.exists(dest + ".tmp"))
        self.assertFalse(os.path.exists(dest))

    def test_main_reads_the_offsite_setting(self):
        extra = str(self.dir / "offsite")
        with opened(self.db) as conn:
            set_setting(conn, KEY_BACKUP_SECOND_DIR, extra)
        main.run_auto_backup(self.db)
        self.assertEqual(len(self.backups(extra)), 3)

    def test_latest_backup_date(self):
        self.assertIsNone(db_backup.latest_backup_date(str(self.dir / "missing")))
        db_backup.run_auto_backup(self.db, now=datetime(2026, 9, 17))
        self.assertEqual(db_backup.latest_backup_date(db_backup.backup_dir(self.db)),
                         date(2026, 9, 17))


class TestManualBackup(_TempDbCase):
    def test_manual_backup_is_not_pruned(self):
        dest = db_backup.manual_backup_path(self.db, datetime(2026, 9, 1, 9, 0))
        db_backup.manual_backup(self.db, dest)
        for day in range(1, 11):
            db_backup.run_auto_backup(self.db, now=datetime(2026, 9, day))
        self.assertIn("dbfile_backup_manual_20260901_0900.db", self.backups())


class TestIntegrity(_TempDbCase):
    def test_healthy_database_passes(self):
        self.assertTrue(main.database_is_healthy(self.db))

    def test_missing_database_is_not_corrupt(self):
        self.assertTrue(db_backup.quick_check(str(self.dir / "none.db")))

    def test_garbage_file_is_corrupt(self):
        bad = self.dir / "bad.db"
        bad.write_bytes(b"not a sqlite database" * 100)
        with mock.patch("logging.error"):
            self.assertFalse(db_backup.quick_check(str(bad)))

    def test_locked_database_is_let_through(self):
        with mock.patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")), \
             mock.patch("logging.error"):
            self.assertTrue(db_backup.quick_check(self.db))

    def test_deep_check_runs_once_a_week(self):
        now = datetime(2026, 9, 17)
        with mock.patch.object(db_backup, "_integrity", return_value=True) as check:
            db_backup.deep_check_if_due(self.db, now=now)
            db_backup.run_auto_backup(self.db, now=now)
            db_backup.deep_check_if_due(self.db, now=now)
        self.assertEqual(check.call_count, 1)


class TestVacuum(_TempDbCase):
    def test_vacuum_keeps_the_data(self):
        with opened(self.db) as conn:
            before = conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0]
        sizes = db_backup.vacuum(self.db)
        self.assertEqual(len(sizes), 2)
        with opened(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM Member").fetchone()[0], before)


class TestErrorReasons(unittest.TestCase):
    def test_reason_by_error_code_not_text(self):
        exc = OSError("任何語系的文字")
        exc.winerror = 53
        self.assertIn("網路路徑", db_backup.reason_for(exc))
        self.assertIn("權限", db_backup.reason_for(PermissionError()))
        self.assertEqual(db_backup.reason_for(ValueError()), "無法存取")


if __name__ == "__main__":
    unittest.main()
