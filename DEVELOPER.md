# PoliceRotaSys 技術文件

> 本檔為設計初稿，依 2026-09-14 與維護者的規則討論寫成。
> 實作尚未開始；任何與本檔不符的實作，以本檔為準或回頭修本檔，不要讓兩者分歧。

## §1 架構

```
SQLite（規則版本 + 月計畫）
    ↓
排班演算法（純函式，零相依）
    ↓
版面模型（純資料：幾列幾欄、每格文字與顏色）
    ↓                    ↓
openpyxl → .xlsx      QPdfWriter → .pdf
```

**「版面模型」是刻意設計的中間層。** 兩個輸出共用同一份版面定義，Excel 印出來
和 PDF 才會長一樣。也因為它是純資料，可以在無 GUI 環境對它寫測試——這是唯一
能讓「A3 版面對不對」被自動驗證的做法，否則只能靠人上機用眼睛看。

## §2 排班演算法

```
第 i 人在第 d 天的格位 = ((seed_i - 1 + (d - 1)) mod cycle_len) + 1
顯示代碼 = 該格位在 rv_slot 的 code（is_rest 則印 rest_code 並標紅）
```

固定番組（`mode='fixed'`）去掉 `(d - 1)` 那一項，格位永遠不動。

### 為什麼存「格位」而不是「番號」

`month_seed` 存 `slot_seq`（第幾格），不是番號。

**因為休沒有番號。** 若存番號，就存不了「他 1 日是休在第 6 格還是第 7 格」，
而這兩者的後續完全不同：第 6 格明天還是休，第 7 格明天上 `08`。
存格位沒這問題；番號是查 `rv_slot` 得到的**顯示結果**。

## §3 資料庫

分成兩區，**分界是整個設計的重點**。

### 設定區（承辦人日常維護，可隨時改）

```sql
member(id, name, active)
```

### 規則版本區（建立即凍結，永不修改）

```sql
ruleset(id, name)                        -- '龍興所輪番規則'
ruleset_version(id, ruleset_id, version_no, created_at, note)

rv_group(
  id, version_id, name,
  mode,          -- 'rotate' 輪番 / 'fixed' 固定
  cycle_len,     -- 循環格數，例 20
  code_style,    -- 'num2' / 'alpha' / 'cjk' / 'literal'
  rest_code      -- 休要印什麼，例 '00'
)

rv_slot(
  version_id, group_id, seq,
  is_rest,       -- 輪休規則
  code_override  -- 不照 code_style 時才填
)
```

`code_style` 產生預設代碼，`code_override` 逐格蓋掉它。所以換成甲乙丙的單位
只要改一個欄位，不必重打 20 格；遇到不規則的區塊（如 21～28、A～F）才逐格指定。

⚠️ **畫面上被覆寫過的格子要有視覺記號**（例如底色不同），讓人一眼看出
「這格是手動指定的，不是預設算出來的」。不然半年後看到怪代號會以為程式壞了。

### 事實區（產出後只新增、不修改）

```sql
month_plan(
  id, year, month,
  ruleset_version_id,   -- 這個月用哪一版規則
  origin,               -- 'chain' 接上月 / 'reset' 使用者重設
  created_at
)

month_seed(plan_id, group_id, member_id, row_no, slot_seq)
```

**整月 558 格的結果不落地，只存 1 日那一排。** 落地就有兩份真相，改一邊忘一邊。

回頭重印任何一個月，都是拿該月的 `ruleset_version_id` 去讀規則，結果必然與
當初一致——規則改過幾次都不影響。

### 不可修改怎麼保證

不靠程式自律，用 SQLite trigger 擋死：

```sql
CREATE TRIGGER rv_slot_immutable
BEFORE UPDATE ON rv_slot
BEGIN SELECT RAISE(ABORT, '規則版本不可修改'); END;
```

`ruleset_version` / `rv_group` / `rv_slot` 三張表全部禁 UPDATE、禁 DELETE。

### 容量

一年約 430 列、約 70 KB。用二十年約 1.5 MB。**不需要為容量做任何妥協。**

⚠️ **產出的 xlsx／pdf 絕對不要存進資料庫。** 一份 A3 月表 pdf 約 50～200 KB，
十年下來會有幾十 MB 的 BLOB，備份與複製都會變慢。檔案輸出到使用者指定的
資料夾，資料庫最多記一筆「何時產過、存到哪」的路徑字串。要重印就重算。

### 維護

「資料庫維護」放一顆 `VACUUM` 按鈕即可，回收刪除月計畫後的空間。

## §4 測試

- 單元測試在 `tests/`，檔名 `test_*.py`
- 純邏輯（排班推算、代碼產生、版面模型）在容器內即可驗證，**一律要有測試**
- GUI 與 A3 實際版面**必須上機**，容器無法開 GUI／截圖
- ⚠️ 125% 縮放下的視覺問題（切字、欄寬、裁切）**容器量不出來**，
  不要憑 `sizeHint`／`QFontMetrics` 的數字回報「修好了」
- push 前必跑 `python -m unittest tests.test_no_pii`

## §5 待決事項

以下尚未與維護者定案，**動工前要先問**：

1. 設定怎麼存進資料庫、初始資料怎麼導入（維護者表示「再想想」）
2. A3 橫式版面的實際尺寸、欄寬、字級、頁首格式
3. 番號對應班別的註記（早班／中班／晚班）是固定備註還是程式算出來
4. 同一個人可不可以同時在兩個番組
5. 要不要做權限（若只有承辦人一人使用，可先不做）
