# 從 PoliceDocSys 搬遷清單

姊妹專案 `PoliceDocSys` 已累積大量與公文業務無關的通用資產，本專案直接繼承。

⚠️ **搬遷不是 `cp -r`。** 每支檔案都要先確認有沒有偷偷 import 公文專屬的東西
（常數、schema、案類定義），砍掉相依之後才放進來。逐檔確認，不要整包倒。

## 一、直接搬 code

| 來源 | 為什麼要搬 |
|---|---|
| `lib/theme.py` | 全域樣式公版。**第一天就要有**，否則又會各處寫死色碼 |
| `ui_utils/ui_common.py` | `BTN_CONFIRM`／`BTN_CANCEL`／`BTN_DANGER`、`msgInfo`／`confirmBox` |
| `ui_utils/table.py` | `setupPreviewTable`／`autoResizeTable`。LAY-4b/4c/7/8/15 的血都在裡面 |
| `ui_utils/widgets.py` | `NullableDateEdit`、`attachComboHint`、`setupFilterCombo` |
| `ui_utils/date_guard.py` | `installDateEditInputGuard`。QTW-13／QTW-14 兩條雷的解藥 |
| `lib/print_canvas.py` | QPdfWriter 繪圖層——**A3 PDF 輸出的地基** |
| `lib/db_utils.py`、`lib/db_backup.py` | SQLite 連線慣例、備份 |
| `lib/window_geometry.py`、`lib/app_lock.py` | 視窗位置記憶、單一實例 |
| `lib/version.py` ＋ `tools/bump_version.py` | 進版機制 |
| `ui_utils/settings_panels.py` | `_SettingsPanel`／`_save_row` 設定面板公版；`PrintTitlePanel` 可直接改用 |

## 二、搬測試基礎建設（比 code 更重要）

```
conftest.py   pytest.ini
tests/__init__.py   tests/date_guard_shim.py   ← 少了會卡在日期防呆確認框
tests/test_no_pii.py                           ← 已移植（見下）
tests/test_environment_contract.py             ← 釘住 Python／套件版本與封閉相依清單
tests/test_dialog_disabled_style.py            ← QSS-8 的回歸網
tests/test_table_col_widths.py                 ← LAY-15 的回歸網
```

**列印驗收網（暫緩，2026-09-17 維護者裁示）**：PoliceDocSys 三層裡，Qt 對 matplotlib
比對與「產品不含 matplotlib」兩層是為換繪圖引擎而做，本專案一開始就是 Qt，**不搬**。
只有「基準圖雜湊比對」適用，規劃如下，**等 PDF 版面上機定案後再做**
（版面還在頻繁調整時，每改一次就要看圖重建基準，成本大於效益）：

- 固定虛構資料案例（31／28 天、人多觸發縮小、人少欄變寬、代號上方／下方、反向排序、女警、長名字）
- 直接呼叫 `pdf_writer.paint_sheet` 畫成圖算雜湊，不比 PDF 檔（內含建立時間，每次都不同）
- 比對前先查環境（標楷體／Tahoma 字型檔、Qt 版本、顯示縮放），不符就停，不當成程式回歸
- 有差異時新舊圖並排輸出到未入庫資料夾；雜湊清單入庫、圖檔不入庫
- 基準初建須維護者逐張目視核准（雜湊一致只證明前後沒變，不證明正確）
- 工具手動執行，不進自動測試（換機器雜湊全滅）
- **Excel 不納入**：要靠本機 Excel 轉 PDF，版本一更新就不穩；繼續靠現有欄寬／字級／合併格測試
- 故意改版面時比對一定報差異，看過並排圖確認後重建基準即可；它的價值是抓「沒打算改卻跟著變」的地方

## 三、搬規則（最值錢的部分）

本專案的 `AGENTS.md` 與（待建的）`PITFALLS.md` 應**從 PoliceDocSys 裁剪而來，
不要重寫**。

`PITFALLS.md` 的 UI／QSS／QTW／LAY／TAB 五組幾乎整包可用——全是 PySide6 通病，
與公文業務無關。特別是：

- **QSS-8** 彈窗別自帶區域 QSS（踩了六個彈窗才學會）
- **QTW-13／QTW-14** 日期框被滾輪／點擊靜默改掉
- **LAY-4b／4c／7／8／15** 欄寬與離線量測失準
- **QTW-5／QTW-6 ＋ LAY-8** 的共同教訓：125% 縮放下的視覺問題容器量不出來，只能上機定案
- **CFG-1** 開機讀一次就快取的設定，存檔後要有人重新套用（見 DEVELOPER §7）
- **QTW-7／8／9／11／12** 可打字 combo ＋ completer 那一整族（配對彈窗改用補強過的公版 `makeFilterCombo`，另加兩條規矩，見 DEVELOPER §4）

### 要改寫的兩條

| PoliceDocSys 的規則 | 本專案改成 |
|---|---|
| runtime 相依只有 `PySide6` | `PySide6` ＋ `openpyxl`，一樣要有 `test_environment_contract` 守著 |
| `AppProfile` 完整版／獨立版差異 | 本專案沒有雙 exe，但「差異集中在一處、現場調的做成設定」的原則保留 |

## 四、不搬

`tabs/`、`archive_text.py`、`doc_convert.py`、`ticket_*`／`reward_*`、
`app_profile.py`、`row_perm.py`——全是公文業務。

權限那套（`auth_manager.py`、`row_perm.py`）看需求決定：若本工具只有承辦人
一人使用，可先不做。

## 五、進度

**已完成（皆為自行撰寫，非搬遷）**

- [x] `lib/rota.py` 排班演算法
- [x] `lib/layout_model.py` 版面模型
- [x] `lib/db_schema.py`／`db_utils.py`／`db_seed.py` 資料層
- [x] `lib/template.py` 輪番模板（原 `ruleset.py` 草稿↔啟用狀態機已拿掉，改模板＋月表快照）
- [x] `lib/plan.py` 月表（建立、接續、覆蓋、快照、組版）
- [x] `export/xlsx_writer.py`／`pdf_writer.py` 兩個 renderer
- [x] `PITFALLS.md` 起頭

**已移植**

- [x] `tests/test_no_pii.py`（裁剪版：移除 `gen_shell_db`／`seed_screenshot_data`
      等公文專屬檢查，保留 tracked 三來源掃描與 outgoing commit 掃描）
- [x] `tests/test_environment_contract.py`（改寫：封閉清單改為 PySide6 ＋ openpyxl）

**已移植（續）**

- [x] `lib/theme.py` 全域樣式公版（純字串模組、無 Qt import，容器可安全搬）
- [x] `res/buttons/` 的 `arrow.svg`／`chk_check.svg`／`chk_check_disabled.svg` 與
      `res/resources.qrc`（勾選框的打勾圖，女警欄位要用）

**已移植（ui_utils 公版）**

- [x] `ui_utils/ui_common.py`／`table.py`／`widgets.py`／`date_guard.py`（照抄；
      移除收件人輸入元件、公文欄位的固定欄寬表；之後另拿掉沒人用的 `loadUi`，
      它會把 OpenGL 整串拉進打包，見 PITFALLS PKG-2）
- [x] `ui_utils/settings_panels.py`（只留 `_SettingsPanel`／`_save_row` 共用外框，
      各公文設定面板不搬）
- [x] `res/resources_rc.py`（由 `pyside6-rcc res/resources.qrc -o res/resources_rc.py` 產生）
- [x] `conftest.py`（只留日期防呆 fixture）、`tests/date_guard_shim.py`（unittest 由
      `tests/__init__.py` 安裝）
- [x] `tests/test_dialog_disabled_style.py`（移除依賴公文彈窗與資料庫的案例，保留公版層檢查）、
      `tests/test_table_col_widths.py`（照抄）、`tests/test_ui_utils_smoke.py`（新增）

**GUI 與打包（在維護者的機器上進行）**

- [x] `main.py` 最小主程式＋人員分頁（比照 PoliceDocSys 人員管理搬入）
- [x] 輪番設定分頁（群組表與人員分頁共用 `ui_utils/sort_table.py` 排序表格公版）
- [x] 產生月表分頁、配對彈窗、預覽（`tabs/tab_generate.py`、`ui_utils/pairing_dialog.py`、`ui_utils/sheet_preview.py`）
- [x] 維護分頁（`tabs/tab_maintenance.py`）：月表標題、資料庫備份、壓縮；`lib/db_backup.py` 自 PoliceDocSys 搬入
      開機損毀檢查＋GFS 自動備份＋異地位置，拿掉還原／救援視窗／筆數預覽。匯出資料夾設定改為預設桌面、不記住
- [ ] 列印驗收網（只做基準圖雜湊比對，暫緩到 PDF 版面定案，規劃見第二節）
- [x] `lib/version.py` ＋ `tools/bump_version.py`（產品名改為本專案、拿掉獨立版與 README 版號同步；起始 0.1.0）
- [x] PyInstaller 打包（spec 入庫＋`tools/pyi_prune.py` 瘦身，DEVELOPER §10）
