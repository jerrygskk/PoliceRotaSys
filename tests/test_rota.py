"""lib/rota.py 的單元測試。

⚠️ 一律用虛構姓名（public repo，見 tests/test_no_pii.py）。

最重要的一支是 TestAgainstPaperForm：拿現行紙本（115 年 10 月）的實際排列
當基準，確認演算法推出來的結果與紙本逐格相同。改動演算法時那支若變紅，
就是真的改壞了，不要去改測試。
"""
import unittest

from lib.rota import (
    CJK_STEMS,
    Group,
    GroupError,
    RangeError,
    build_slots,
    chain_seeds,
    detect_kind,
    expand_range,
    make_group,
    month_days,
    rota_month,
    slot_on_day,
    slots_identical,
    validate_expr,
    validate_groups,
)

# 現行紙本的大輪番：20 格，休在 6、7、13、14、19、20
PAPER_REST = {6, 7, 13, 14, 19, 20}


def paper_group():
    return make_group("大輪番", "rotate", "1-20", PAPER_REST)


class TestDetectKind(unittest.TestCase):
    def test_digits_are_numeric(self):
        self.assertEqual(detect_kind("1-20"), "num")

    def test_letters_are_alpha(self):
        self.assertEqual(detect_kind("A-F"), "alpha")

    def test_stems_are_cjk(self):
        self.assertEqual(detect_kind("甲-丁"), "cjk")

    def test_mixed_kinds_rejected(self):
        with self.assertRaisesRegex(RangeError, "混用"):
            detect_kind("1-A")

    def test_empty_rejected(self):
        with self.assertRaisesRegex(RangeError, "不可為空"):
            detect_kind("")


class TestExpandRange(unittest.TestCase):
    def test_simple_numeric_range_pads_by_widest_value(self):
        self.assertEqual(expand_range("1-20")[:3], ("01", "02", "03"))
        self.assertEqual(expand_range("1-20")[-1], "20")

    def test_single_digit_range_is_not_padded(self):
        self.assertEqual(expand_range("1-5"), ("1", "2", "3", "4", "5"))

    def test_three_digit_maximum_pads_to_three(self):
        self.assertEqual(expand_range("1-100")[0], "001")

    def test_comma_segments_are_supported(self):
        self.assertEqual(expand_range("1-3,8-9"), ("1", "2", "3", "8", "9"))

    def test_bare_single_value_segment(self):
        self.assertEqual(expand_range("1-2,5"), ("1", "2", "5"))

    def test_alpha_range(self):
        self.assertEqual(expand_range("A-F"), ("A", "B", "C", "D", "E", "F"))

    def test_cjk_stem_range(self):
        self.assertEqual(expand_range("甲-丁"), ("甲", "乙", "丙", "丁"))

    def test_reversed_range_rejected(self):
        with self.assertRaisesRegex(RangeError, "起迄相反"):
            expand_range("20-1")

    def test_self_overlapping_segments_rejected(self):
        with self.assertRaisesRegex(RangeError, "兩次"):
            expand_range("1-10,5-8")

    def test_stray_comma_rejected(self):
        with self.assertRaisesRegex(RangeError, "空的段落"):
            expand_range("1-5,")

    def test_multi_character_alpha_rejected(self):
        with self.assertRaisesRegex(RangeError, "單一字元"):
            expand_range("AA-AF")

    def test_malformed_dash_rejected(self):
        with self.assertRaisesRegex(RangeError, "合法"):
            expand_range("1-2-3")

    def test_whitespace_around_tokens_is_tolerated(self):
        self.assertEqual(expand_range(" 1 - 3 "), ("1", "2", "3"))


class TestBuildSlots(unittest.TestCase):
    def test_rest_positions_are_marked(self):
        slots = build_slots(expand_range("1-20"), PAPER_REST)
        self.assertEqual(len(slots), 20)
        self.assertTrue(slots[5].is_rest)   # 第 6 格
        self.assertTrue(slots[19].is_rest)  # 第 20 格
        self.assertFalse(slots[0].is_rest)

    def test_seq_is_one_based(self):
        slots = build_slots(expand_range("1-3"))
        self.assertEqual([s.seq for s in slots], [1, 2, 3])

    def test_rest_out_of_range_rejected(self):
        with self.assertRaisesRegex(RangeError, "超出範圍"):
            build_slots(expand_range("1-5"), {9})

    def test_fixed_group_rejects_rest_positions(self):
        with self.assertRaisesRegex(ValueError, "沒有輪休"):
            make_group("固定番", "fixed", "21-25", {1})


class TestValidateGroups(unittest.TestCase):
    def test_paper_groups_pass(self):
        validate_groups([
            paper_group(),
            make_group("固定番", "fixed", "21-25"),
            make_group("幹部", "fixed", "A-F"),
        ])

    def test_codes_colliding_across_groups_rejected(self):
        with self.assertRaisesRegex(GroupError, "18"):
            validate_groups([
                paper_group(),
                make_group("固定番", "fixed", "18-25"),
            ])

    def test_rotate_group_that_is_all_rest_rejected(self):
        group = make_group("全休", "rotate", "1-3", {1, 2, 3})
        with self.assertRaisesRegex(GroupError, "沒有人會上班"):
            validate_groups([group])

    def test_empty_group_rejected(self):
        with self.assertRaisesRegex(GroupError, "空的"):
            validate_groups([Group(name="空組", mode="rotate", slots=())])


class TestValidateExpr(unittest.TestCase):
    def test_valid_expression_passes_silently(self):
        self.assertIsNone(validate_expr("1-20"))

    def test_invalid_expression_raises(self):
        with self.assertRaises(RangeError):
            validate_expr("20-1")


class TestSlotOnDay(unittest.TestCase):
    def test_rotate_advances_one_slot_per_day(self):
        group = paper_group()
        self.assertEqual(slot_on_day(group, 1, 1).seq, 1)
        self.assertEqual(slot_on_day(group, 1, 2).seq, 2)

    def test_rotate_wraps_past_the_last_slot(self):
        group = paper_group()
        self.assertEqual(slot_on_day(group, 20, 2).seq, 1)

    def test_fixed_never_advances(self):
        group = make_group("固定番", "fixed", "21-25")
        self.assertEqual(slot_on_day(group, 3, 1).code, "23")
        self.assertEqual(slot_on_day(group, 3, 31).code, "23")

    def test_seed_out_of_range_rejected(self):
        with self.assertRaisesRegex(ValueError, "超出範圍"):
            slot_on_day(paper_group(), 21, 1)

    def test_day_zero_rejected(self):
        with self.assertRaisesRegex(ValueError, "從 1 起算"):
            slot_on_day(paper_group(), 1, 0)


class TestMonthDays(unittest.TestCase):
    def test_october_has_31_days(self):
        self.assertEqual(month_days(2026, 10), 31)

    def test_leap_february(self):
        self.assertEqual(month_days(2024, 2), 29)
        self.assertEqual(month_days(2025, 2), 28)


class TestAgainstPaperForm(unittest.TestCase):
    """對照現行紙本（115 年 10 月）的實際排列。

    第一位同仁 10/1 站在第 12 格，往後推得到的整列必須與紙本逐格相同。
    紙本上休一律印 00。
    """

    # 逐格抄自紙本第一列（1 日～17 日）
    PAPER_ROW = [
        "12", "00", "00", "15", "16", "17", "18", "00", "00",
        "01", "02", "03", "04", "05", "00", "00", "08",
    ]

    def test_first_row_matches_paper(self):
        group = paper_group()
        got = []
        for day in range(1, len(self.PAPER_ROW) + 1):
            slot = slot_on_day(group, 12, day)
            got.append("00" if slot.is_rest else slot.code)
        self.assertEqual(got, self.PAPER_ROW)

    def test_codes_13_14_19_20_never_appear_because_they_are_rest(self):
        group = paper_group()
        printed = {
            ("00" if slot.is_rest else slot.code)
            for day in range(1, 32)
            for slot in [slot_on_day(group, 12, day)]
        }
        self.assertTrue({"13", "14", "19", "20"}.isdisjoint(printed))

    def test_each_member_is_offset_by_one_day_from_the_previous(self):
        """紙本的對角線：第 i+1 位在第 d 天 == 第 i 位在第 d+1 天。"""
        group = paper_group()
        for day in range(1, 31):
            self.assertEqual(
                slot_on_day(group, 13, day).seq,
                slot_on_day(group, 12, day + 1).seq,
            )

    def test_every_member_rests_six_days_per_cycle(self):
        group = paper_group()
        for seed in range(1, 21):
            rests = sum(
                1 for day in range(1, 21) if slot_on_day(group, seed, day).is_rest
            )
            self.assertEqual(rests, 6, f"起始格位 {seed} 的休假天數不對")


class TestRotaMonth(unittest.TestCase):
    def test_returns_one_entry_per_day_for_each_member(self):
        result = rota_month(paper_group(), {"王小明": 12, "李小華": 13}, 2026, 10)
        self.assertEqual(set(result), {"王小明", "李小華"})
        self.assertEqual(len(result["王小明"]), 31)

    def test_february_is_shorter(self):
        result = rota_month(paper_group(), {"王小明": 1}, 2025, 2)
        self.assertEqual(len(result["王小明"]), 28)


class TestChainSeeds(unittest.TestCase):
    def test_chaining_is_continuous_across_the_month_boundary(self):
        """10/31 的下一格必須就是 11/1——番號不可亂跳。"""
        group = paper_group()
        october = {"王小明": 12}
        november = chain_seeds(group, october, month_days(2026, 10))
        last_day = slot_on_day(group, october["王小明"], 31)
        first_day = slot_on_day(group, november["王小明"], 1)
        self.assertEqual(first_day.seq, last_day.seq % group.cycle_len + 1)

    def test_fixed_group_seeds_are_unchanged(self):
        group = make_group("固定番", "fixed", "21-25")
        self.assertEqual(chain_seeds(group, {"王小明": 3}, 31), {"王小明": 3})

    def test_chaining_a_full_cycle_returns_to_the_same_slot(self):
        group = paper_group()
        self.assertEqual(chain_seeds(group, {"王小明": 7}, 20), {"王小明": 7})


class TestSlotsIdentical(unittest.TestCase):
    def test_same_definition_is_identical(self):
        self.assertTrue(slots_identical(paper_group(), paper_group()))

    def test_moving_a_rest_day_is_not_identical_even_with_same_length(self):
        """⚠️ 格數一樣不代表可以沿用配對——休的位置移了就不行。"""
        moved = make_group("大輪番", "rotate", "1-20", {5, 6, 13, 14, 19, 20})
        self.assertEqual(paper_group().cycle_len, moved.cycle_len)
        self.assertFalse(slots_identical(paper_group(), moved))

    def test_different_length_is_not_identical(self):
        longer = make_group("大輪番", "rotate", "1-22", PAPER_REST)
        self.assertFalse(slots_identical(paper_group(), longer))


class TestNoRealNamesInStems(unittest.TestCase):
    def test_stem_table_is_the_ten_heavenly_stems(self):
        self.assertEqual(len(CJK_STEMS), 10)
        self.assertEqual(CJK_STEMS[0], "甲")


if __name__ == "__main__":
    unittest.main()
