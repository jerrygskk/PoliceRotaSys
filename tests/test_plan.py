"""lib/plan.py：月計畫的建立、接續、組版。⚠️ 姓名一律虛構。

最要緊的是 TestChaining——維護者定下的兩條產生原則全在這裡：
番號沒動就接上月底，番號動了就從 1 日重來；規則換版強制走重設。
"""
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, plan, ruleset
from lib.rota import slot_on_day

UNIT = "○○分局○○派出所"


def block_named(sheet, name):
    """⚠️ 用名稱找區塊，不要寫死索引——加一個區塊就全錯。"""
    for block in sheet.blocks:
        if block.name == name:
            return block
    raise AssertionError(f"找不到區塊「{name}」")


class _PlanTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="rota-plan-")
        self.conn = db_utils.connect(str(Path(self._temp.name) / "t.db"))
        db_schema.create_all(self.conn)
        db_seed.seed_all(self.conn)
        self.ruleset_id = self.conn.execute(
            "SELECT ruleset_id FROM Ruleset"
        ).fetchone()[0]
        self.version = self.conn.execute(
            "SELECT version_id FROM Ruleset_Version WHERE status = '草稿'"
        ).fetchone()[0]
        ruleset.activate(self.conn, self.version)
        rows = self.conn.execute(
            "SELECT group_id, name FROM RV_Group WHERE version_id = ? "
            "ORDER BY sort_order", (self.version,)
        ).fetchall()
        self.gid = {r["name"]: r["group_id"] for r in rows}
        self.members = [
            r[0] for r in self.conn.execute(
                "SELECT member_id FROM Member ORDER BY sort_order"
            )
        ]

    def tearDown(self):
        self.conn.close()
        self._temp.cleanup()

    def full_seeds(self, rotate_start=1):
        """配滿三組——create_plan 現在要求每一格都有人。"""
        return {
            self.gid["大輪番"]: {
                self.members[i]: (rotate_start - 1 + i) % 20 + 1
                for i in range(20)
            },
            self.gid["固定番"]: {self.members[20 + i]: i + 1 for i in range(8)},
            self.gid["幹部"]: {self.members[28 + i]: i + 1 for i in range(6)},
        }

    # 舊名保留，內容改為配滿。
    rotate_seeds = full_seeds

    def make_plan(self, year=2026, month=10, origin=plan.ORIGIN_RESET, seeds=None):
        return plan.create_plan(
            self.conn, year, month, self.version, origin,
            seeds if seeds is not None else self.rotate_seeds(),
        )


class TestCreatePlan(_PlanTestCase):
    def test_plan_and_seeds_are_written(self):
        plan_id = self.make_plan()
        self.assertEqual(
            len(plan.load_seeds(self.conn, plan_id)[self.gid["大輪番"]]), 20
        )

    def test_duplicate_month_is_refused(self):
        self.make_plan()
        with self.assertRaisesRegex(plan.PlanError, "已經有月表"):
            self.make_plan()

    def test_unknown_origin_is_refused(self):
        with self.assertRaisesRegex(plan.PlanError, "未知的來源"):
            self.make_plan(origin="whatever")

    def test_empty_seeds_are_refused(self):
        with self.assertRaisesRegex(plan.PlanError, "沒有任何配對"):
            self.make_plan(seeds={})

    def test_slot_outside_the_cycle_is_refused(self):
        """⚠️ 指到不存在的格位，月表上看不出來，所以要在寫入前擋。"""
        bad = self.full_seeds()
        bad[self.gid["大輪番"]][self.members[0]] = 99
        with self.assertRaisesRegex(plan.PlanError, "超出範圍"):
            self.make_plan(seeds=bad)

    def test_a_group_with_a_gap_is_refused(self):
        """⚠️ 漏一格，印出來那一欄就是空的，承辦人不知道是誰的錯。"""
        short = self.full_seeds()
        short[self.gid["大輪番"]].pop(self.members[0])
        with self.assertRaisesRegex(plan.PlanError, "還有格位沒配人"):
            self.make_plan(seeds=short)

    def test_a_group_with_nobody_at_all_is_refused(self):
        """一個人都沒配的番組過不了完整性檢查。"""
        without = self.full_seeds()
        without.pop(self.gid["幹部"])
        with self.assertRaisesRegex(plan.PlanError, "幹部"):
            self.make_plan(seeds=without)

    def test_the_error_names_the_missing_slots(self):
        short = self.full_seeds()
        short[self.gid["固定番"]].pop(self.members[22])
        with self.assertRaisesRegex(plan.PlanError, "第 3 格"):
            self.make_plan(seeds=short)

    def test_group_from_another_version_is_refused(self):
        other = ruleset.copy_to_draft(self.conn, self.version, "另一版")
        other_gid = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? LIMIT 1", (other,)
        ).fetchone()[0]
        bad = self.full_seeds()
        bad[other_gid] = {self.members[0]: 1}
        with self.assertRaisesRegex(plan.PlanError, "不屬於這一版"):
            self.make_plan(seeds=bad)

    def test_delete_then_recreate(self):
        self.make_plan()
        plan.delete_plan(self.conn, 2026, 10)
        self.assertIsNone(plan.get_plan(self.conn, 2026, 10))
        self.make_plan()

    def test_deleting_a_missing_plan_is_a_no_op(self):
        plan.delete_plan(self.conn, 2030, 1)


class TestChaining(_PlanTestCase):
    def test_no_previous_month_blocks_chaining(self):
        reason = plan.chain_blocked_reason(self.conn, 2026, 10, self.version)
        self.assertIn("沒有月表可以接續", reason)

    def test_chaining_works_when_nothing_changed(self):
        self.make_plan(2026, 10)
        self.assertTrue(plan.can_chain(self.conn, 2026, 11, self.version))

    def test_chained_seeds_are_continuous_across_the_boundary(self):
        """⚠️ 10/31 的下一格必須就是 11/1——番號不可亂跳。"""
        self.make_plan(2026, 10)
        groups = {g.name: g for g in ruleset.load_groups(self.conn, self.version)}
        group = groups["大輪番"]
        before = plan.load_seeds(self.conn, plan.get_plan(self.conn, 2026, 10)["plan_id"])
        after = plan.chained_seeds(self.conn, 2026, 11, self.version)
        for member, seq in before[self.gid["大輪番"]].items():
            last = slot_on_day(group, seq, 31)
            first = slot_on_day(group, after[self.gid["大輪番"]][member], 1)
            self.assertEqual(first.seq, last.seq % group.cycle_len + 1)

    def test_january_chains_from_december(self):
        self.make_plan(2026, 12)
        self.assertTrue(plan.can_chain(self.conn, 2027, 1, self.version))

    def test_changing_the_version_blocks_chaining(self):
        """規則換版走重設——這是規則二的正常結果，不是例外處理。"""
        self.make_plan(2026, 10)
        second = ruleset.copy_to_draft(self.conn, self.version, "第二版")
        ruleset.activate(self.conn, second)
        reason = plan.chain_blocked_reason(self.conn, 2026, 11, second)
        self.assertIn("規則已換版", reason)

    def test_moving_a_rest_day_blocks_chaining_even_with_the_same_length(self):
        """格數一樣但休移了位，一樣不能接續。

        ⚠️ 擋下來的是「換了版」而不是「槽位不同」——規則版本啟用後凍結，
        所以同一版的槽位必然相同，換版才可能不同。兩者在這裡是同一件事。
        """
        self.make_plan(2026, 10)
        second = ruleset.copy_to_draft(self.conn, self.version, "休移位")
        gid = self.conn.execute(
            "SELECT group_id FROM RV_Group WHERE version_id = ? AND name = '大輪番'",
            (second,),
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE RV_Slot SET is_rest = 1 WHERE group_id = ? AND seq = 5", (gid,)
        )
        self.conn.execute(
            "UPDATE RV_Slot SET is_rest = 0 WHERE group_id = ? AND seq = 7", (gid,)
        )
        self.conn.commit()
        ruleset.activate(self.conn, second)
        reason = plan.chain_blocked_reason(self.conn, 2026, 11, second)
        self.assertIn("規則已換版", reason)

    def test_chained_seeds_raise_when_blocked(self):
        with self.assertRaises(plan.PlanError):
            plan.chained_seeds(self.conn, 2026, 10, self.version)

    def test_fixed_group_seeds_survive_chaining_unchanged(self):
        seeds = self.full_seeds()
        self.make_plan(2026, 10, seeds=seeds)
        after = plan.chained_seeds(self.conn, 2026, 11, self.version)
        self.assertEqual(after[self.gid["固定番"]], seeds[self.gid["固定番"]])

    def test_a_full_chain_of_months_stays_continuous(self):
        """連產三個月，每次接續，番號不得亂跳。"""
        self.make_plan(2026, 10)
        for year, month in ((2026, 11), (2026, 12)):
            seeds = plan.chained_seeds(self.conn, year, month, self.version)
            plan.create_plan(
                self.conn, year, month, self.version, plan.ORIGIN_CHAIN, seeds
            )
        groups = {g.name: g for g in ruleset.load_groups(self.conn, self.version)}
        group = groups["大輪番"]
        member = self.members[0]
        dec = plan.load_seeds(
            self.conn, plan.get_plan(self.conn, 2026, 12)["plan_id"]
        )[self.gid["大輪番"]][member]
        # 10/1 起算到 12/1 共經過 31 + 30 = 61 天
        expected = (1 - 1 + 61) % group.cycle_len + 1
        self.assertEqual(dec, expected)


class TestBuildSheetFor(_PlanTestCase):
    def test_missing_plan_is_reported(self):
        with self.assertRaisesRegex(plan.PlanError, "還沒有月表"):
            plan.build_sheet_for(self.conn, 2026, 10, UNIT)

    def test_sheet_has_a_block_per_group(self):
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        names = [b.name for b in sheet.blocks if b.name]
        self.assertEqual(
            names,
            ["大輪番", "固定番", "同仁專案臨檢／請假", "幹部", "快打勤務"],
        )

    def test_blank_groups_need_no_pairing_and_render_empty(self):
        """⚠️ 空白欄不配人，格子全空供手寫。"""
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        block = block_named(sheet, "同仁專案臨檢／請假")
        self.assertEqual([c.header for c in block.columns], ["早", "中", "晚"])
        for column in block.columns:
            self.assertTrue(all(cell.text == "" for cell in column.cells))

    def test_header_placement_follows_the_group_setting(self):
        """幹部與快打勤務左邊不再放日期欄，照現行紙本。"""
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        kinds = [b.columns[0].kind for b in sheet.blocks]
        self.assertEqual(kinds[0], "title")
        self.assertEqual(kinds.count("date"), 4)

    def test_rotate_block_is_filled(self):
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        column = block_named(sheet, "大輪番").columns[0]
        self.assertTrue(any(cell.text for cell in column.cells))

    def test_fixed_block_is_blank_but_carries_the_code(self):
        """⚠️ 固定番區留白供手填，只印姓名與代碼。"""
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        column = block_named(sheet, "固定番").columns[0]
        self.assertEqual(column.code, "21")
        self.assertTrue(all(cell.text == "" for cell in column.cells))

    def test_member_names_come_from_the_member_table(self):
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        self.assertEqual(block_named(sheet, "大輪番").columns[0].header, db_seed.SEED_MEMBERS[0])

    def test_title_uses_the_unit_name_setting(self):
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        self.assertTrue(sheet.title.startswith(UNIT))

    def test_sheet_matches_the_paper_row_for_a_seed_of_12(self):
        self.make_plan(seeds=self.full_seeds(rotate_start=12))
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        column = block_named(sheet, "大輪番").columns[0]
        self.assertEqual(
            [c.text for c in column.cells[:10]],
            ["12", "00", "00", "15", "16", "17", "18", "00", "00", "01"],
        )


if __name__ == "__main__":
    unittest.main()
