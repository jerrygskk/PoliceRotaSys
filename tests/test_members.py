# -*- coding: utf-8 -*-
"""人員名單資料存取（lib/members.py），一律在暫存資料庫操作。"""
import os
import tempfile
import unittest

from lib import db_schema, db_seed, members
from lib.db_utils import connect


class _TempDb(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = connect(self.db)
        db_schema.create_all(self.conn)

    def tearDown(self):
        self.conn.close()
        os.remove(self.db)


class TestMembers(_TempDb):
    def test_add_goes_to_front(self):
        a = members.add_member(self.conn, "甲員", female=False)
        b = members.add_member(self.conn, "乙員", female=True)
        rows = members.list_members(self.conn)
        self.assertEqual([r[0] for r in rows], [b, a])
        self.assertEqual(rows[0], (b, "乙員", True, True))

    def test_update_name_female_active(self):
        mid = members.add_member(self.conn, "甲員", female=False)
        members.update_member(self.conn, mid, "丙員", female=True, active=False)
        self.assertEqual(members.list_members(self.conn), [(mid, "丙員", False, True)])

    def test_save_order(self):
        ids = [members.add_member(self.conn, n, female=False) for n in ("甲員", "乙員", "丙員")]
        members.save_order(self.conn, ids)          # 依新增順序（甲乙丙）
        self.assertEqual([r[1] for r in members.list_members(self.conn)],
                         ["甲員", "乙員", "丙員"])

    def test_seed_template_listed(self):
        db_seed.seed_all(self.conn)
        rows = members.list_members(self.conn)
        self.assertEqual(len(rows), len(db_seed.SEED_MEMBERS))
        self.assertEqual(rows[0][1], db_seed.SEED_MEMBERS[0])


class TestPositionParsers(unittest.TestCase):
    def test_add_position(self):
        self.assertEqual(members.parse_add_position("", 3), (True, None))
        self.assertEqual(members.parse_add_position("1", 3), (True, 0))
        self.assertEqual(members.parse_add_position("4", 3), (True, 3))
        self.assertEqual(members.parse_add_position("5", 3), (False, None))
        self.assertEqual(members.parse_add_position("0", 3), (False, None))
        self.assertEqual(members.parse_add_position("a", 3), (False, None))

    def test_seq_move_target(self):
        self.assertEqual(members.parse_seq_move_target("3", 3), 2)
        self.assertIsNone(members.parse_seq_move_target("4", 3))
        self.assertIsNone(members.parse_seq_move_target("", 3))


if __name__ == "__main__":
    unittest.main()
