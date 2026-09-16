"""lib/plan.py：月表的建立、接續、組版。⚠️ 姓名一律虛構。

兩個重點：

  TestChaining     接續上月的番號不可亂跳
  TestSnapshot     月表產生後與設定區脫勾——改模板、改名字、刪人都不影響它
"""
import tempfile
import unittest
from pathlib import Path

from lib import db_schema, db_seed, db_utils, plan, template
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
        self.tpl = self.conn.execute(
            "SELECT template_id FROM Rota_Template"
        ).fetchone()[0]
        rows = self.conn.execute(
            "SELECT group_id, name FROM T_Group WHERE template_id = ? "
            "ORDER BY sort_order", (self.tpl,)
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

    def make_plan(self, year=2026, month=10, seeds=None):
        return plan.create_plan(
            self.conn, year, month, self.tpl,
            seeds if seeds is not None else self.rotate_seeds(),
        )

    def rotate_of(self, year, month):
        """某月快照裡大輪番那一組的起始格位，依姓名。"""
        snapshot = plan.load_snapshot(self.conn, year, month)
        group = next(g for g in snapshot["groups"] if g["name"] == "大輪番")
        return {m["name"]: m["slot_seq"] for m in group["members"]}


class TestCreatePlan(_PlanTestCase):
    def test_plan_and_members_are_written(self):
        self.make_plan()
        self.assertEqual(len(self.rotate_of(2026, 10)), 20)

    def test_duplicate_month_is_refused(self):
        self.make_plan()
        with self.assertRaisesRegex(plan.PlanError, "已經有月表"):
            self.make_plan()

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
        """一個人都沒配的群組過不了完整性檢查。"""
        without = self.full_seeds()
        without.pop(self.gid["幹部"])
        with self.assertRaisesRegex(plan.PlanError, "幹部"):
            self.make_plan(seeds=without)

    def test_the_error_names_the_missing_slots(self):
        short = self.full_seeds()
        short[self.gid["固定番"]].pop(self.members[22])
        with self.assertRaisesRegex(plan.PlanError, "第 3 格"):
            self.make_plan(seeds=short)

    def test_group_from_another_template_is_refused(self):
        other = template.copy_template(self.conn, self.tpl, "另一份")
        other_gid = template.group_rows(self.conn, other)[0]["group_id"]
        bad = self.full_seeds()
        bad[other_gid] = {self.members[0]: 1}
        with self.assertRaisesRegex(plan.PlanError, "不屬於這份模板"):
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
        reason = plan.chain_blocked_reason(self.conn, 2026, 10)
        self.assertIn("沒有月表可以接續", reason)

    def test_chaining_works_once_last_month_exists(self):
        self.make_plan(2026, 10)
        self.assertTrue(plan.can_chain(self.conn, 2026, 11))

    def test_chained_seeds_are_continuous_across_the_boundary(self):
        """⚠️ 10/31 的下一格必須就是 11/1——番號不可亂跳。"""
        self.make_plan(2026, 10)
        group = {g.name: g for g in template.load_groups(self.conn, self.tpl)}["大輪番"]
        before = self.rotate_of(2026, 10)
        plan.create_chained_plan(self.conn, 2026, 11)
        after = self.rotate_of(2026, 11)
        for name, seq in before.items():
            last = slot_on_day(group, seq, 31)
            first = slot_on_day(group, after[name], 1)
            self.assertEqual(first.seq, last.seq % group.cycle_len + 1)

    def test_january_chains_from_december(self):
        self.make_plan(2026, 12)
        self.assertTrue(plan.can_chain(self.conn, 2027, 1))

    def test_chaining_carries_last_months_rules_not_the_current_template(self):
        """⚠️ 接續＝沿用上月那份快照。中途改了模板也不影響已接續的月份。"""
        self.make_plan(2026, 10)
        gid = self.gid["大輪番"]
        template.update_group(self.conn, gid, "大輪番", "rotate", "1-22", True, "")
        plan.create_chained_plan(self.conn, 2026, 11)
        snapshot = plan.load_snapshot(self.conn, 2026, 11)
        group = next(g for g in snapshot["groups"] if g["name"] == "大輪番")
        self.assertEqual(len(group["slots"]), 20)

    def test_chained_seeds_raise_when_blocked(self):
        with self.assertRaises(plan.PlanError):
            plan.chained_snapshot(self.conn, 2026, 10)

    def test_fixed_group_seeds_survive_chaining_unchanged(self):
        self.make_plan(2026, 10)
        before = plan.load_snapshot(self.conn, 2026, 10)
        plan.create_chained_plan(self.conn, 2026, 11)
        after = plan.load_snapshot(self.conn, 2026, 11)

        def fixed(snapshot):
            group = next(g for g in snapshot["groups"] if g["name"] == "固定番")
            return [(m["name"], m["slot_seq"]) for m in group["members"]]

        self.assertEqual(fixed(after), fixed(before))

    def test_origin_records_how_the_month_was_made(self):
        self.make_plan(2026, 10)
        plan.create_chained_plan(self.conn, 2026, 11)
        self.assertEqual(
            plan.get_plan(self.conn, 2026, 10)["origin"], plan.ORIGIN_CUSTOM
        )
        self.assertEqual(
            plan.get_plan(self.conn, 2026, 11)["origin"], plan.ORIGIN_CHAIN
        )

    def test_a_full_chain_of_months_stays_continuous(self):
        """連產三個月，每次接續，番號不得亂跳。"""
        self.make_plan(2026, 10)
        for year, month in ((2026, 11), (2026, 12)):
            plan.create_chained_plan(self.conn, year, month)
        group = {g.name: g for g in template.load_groups(self.conn, self.tpl)}["大輪番"]
        name = db_seed.SEED_MEMBERS[0]
        dec = self.rotate_of(2026, 12)[name]
        # 10/1 起算到 12/1 共經過 31 + 30 = 61 天
        self.assertEqual(dec, (1 - 1 + 61) % group.cycle_len + 1)


class TestSnapshotIsDetached(_PlanTestCase):
    """⚠️ 這一類是「脫勾」成不成立的判準——改設定不得讓已產生的月表變樣。"""

    def setUp(self):
        super().setUp()
        self.make_plan(2026, 10)
        self.before = plan.build_sheet_for(self.conn, 2026, 10, UNIT)

    def _unchanged(self):
        self.assertEqual(plan.build_sheet_for(self.conn, 2026, 10, UNIT), self.before)

    def test_editing_the_template_does_not_change_an_existing_month(self):
        gid = self.gid["大輪番"]
        template.toggle_rest(self.conn, gid, 1)
        template.set_code_override(self.conn, gid, 2, "甲")
        template.update_group(self.conn, gid, "改名了", "rotate", "1-22", True, "")
        self._unchanged()

    def test_deleting_the_whole_template_does_not_change_an_existing_month(self):
        template.delete_template(self.conn, self.tpl)
        self._unchanged()

    def test_renaming_or_deleting_a_member_does_not_change_an_existing_month(self):
        self.conn.execute(
            "UPDATE Member SET name = '改過的' WHERE member_id = ?", (self.members[0],)
        )
        self.conn.execute("DELETE FROM Member WHERE member_id = ?", (self.members[1],))
        self.conn.commit()
        self._unchanged()

    def test_the_snapshot_stores_names_not_member_ids(self):
        snapshot = plan.load_snapshot(self.conn, 2026, 10)
        group = next(g for g in snapshot["groups"] if g["name"] == "大輪番")
        self.assertEqual(group["members"][0]["name"], db_seed.SEED_MEMBERS[0])
        self.assertNotIn("member_id", group["members"][0])


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
            ["大輪番", "固定番", "同仁專案臨檢", "劃假", "幹部", "快打勤務"],
        )

    def test_blank_groups_need_no_pairing_and_render_empty(self):
        """⚠️ 空白欄不配人，格子全空供手寫。"""
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        block = block_named(sheet, "劃假")
        # 有註記的區塊：小標題移到代碼列，姓名列讓給跨欄的註記合併格。
        self.assertEqual([c.code for c in block.columns], ["早", "中", "晚"])
        # ⚠️ 註記一律純文字、黑字，不帶顏色（維護者裁示 2026-09-16）
        self.assertEqual(block.note[0], "晚班:(1-5、16)")
        self.assertTrue(all(isinstance(line, str) for line in block.note))
        for column in block.columns:
            self.assertTrue(all(cell.text == "" for cell in column.cells))

    def test_a_blank_block_without_a_note_keeps_its_header(self):
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        block = block_named(sheet, "同仁專案臨檢")
        self.assertEqual(block.columns[0].header, "同仁專案臨檢")
        self.assertEqual(block.note, ())

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

    def test_female_officers_get_a_red_name(self):
        """⚠️ 女警的姓名在 xlsx 與 pdf 都印紅色（維護者要求）。"""
        from lib.layout_model import BLACK, RED

        # ⚠️ 種子模板本來就標了幾位女警，先全部清掉再指定，否則量到的是種子。
        self.conn.execute("UPDATE Member SET female = 0")
        self.conn.execute(
            "UPDATE Member SET female = 1 WHERE member_id = ?", (self.members[0],)
        )
        self.conn.commit()
        self.make_plan()
        sheet = plan.build_sheet_for(self.conn, 2026, 10, UNIT)
        columns = block_named(sheet, "大輪番").columns
        self.assertEqual(columns[0].header_color, RED)
        self.assertEqual(columns[1].header_color, BLACK)

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
            ["12", "休", "休", "15", "16", "17", "18", "休", "休", "01"],
        )


if __name__ == "__main__":
    unittest.main()
