# 交接：PoliceRotaSys（給本機新對話）

> 產生於 2026-09-15（最後更新同日），由雲端容器的對話寫給接手的本機對話。
> ⚠️ 這份是**當下的交接快照**，會過期。做完 GUI 那一輪請更新或刪掉它，
> 不要讓它跟 `DEVELOPER.md` 打架——**兩邊不一致時以 `DEVELOPER.md` 為準**。

## 0. 先讀這三份，再動手

| 檔案 | 內容 |
|---|---|
| `CLAUDE.md` | 業務規則、協作偏好、**已否決的設計清單** |
| `DEVELOPER.md` | 架構、演算法、資料庫、畫面結構、列印版面、已排除的需求 |
| `PITFALLS.md` | 踩雷速查表（本專案自己踩的 20 條） |

⚠️ **`PITFALLS.md` 只記本專案踩到的。** Qt 相關的雷絕大多數還在姊妹專案
`PoliceDocSys` 的 `PITFALLS.md`（UI／QSS／QTW／LAY／TAB 五組幾乎整包適用）。
動 GUI 之前務必先讀那一份，搬遷對照見 `MIGRATION.md`。

## 1. 這是什麼

警察勤務輪番表產生器。依單位的輪番規則產生每月每位同仁的番號，輸出
**A3 橫式**的 Excel 與 PDF。使用者是派出所承辦人員。

- Python 3.12 + PySide6 + SQLite
- ⚠️ **runtime 相依是封閉清單：`PySide6` 與 `openpyxl`**，要加東西先問維護者
- PDF 走 Qt 的 `QPdfWriter`，**不引入 reportlab**
- ⚠️ **這是 public repo**：真實姓名／單位名一律不得入庫

## 2. 本機要裝什麼

### 直譯器

用 PoliceDocSys 那支**正式 gate 的系統 Python**：

```
C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe
```

⚠️ **不要用 Codex runtime 那支**（`.cache\codex-runtimes\...`），它沒有 pytest
與 PySide6，跑不了測試。

### 套件

```powershell
git clone https://github.com/jerrygskk/PoliceRotaSys
cd PoliceRotaSys
python -m pip install -r requirements-dev.txt
```

裝進去的東西：

| 套件 | 版本 | 用途 |
|---|---|---|
| `PySide6` | 6.11.1 | **產品 runtime**：GUI 與 PDF 輸出（`QPdfWriter`） |
| `openpyxl` | 3.1.5 | **產品 runtime**：xlsx 輸出 |
| `pytest` | 9.1.1 | 測試 |
| `pytest-qt` | 4.5.0 | 之後寫 GUI pilot 要用 |
| `pyinstaller` | **未釘** | `--onefile` 打包 |

⚠️ **前兩個是封閉清單**（`requirements.txt`）。要往裡面加東西一律先問維護者，
分界由 `tests/test_environment_contract.py` 守著。

### ⚠️ 第一件事：把 `pyinstaller` 的版本釘上來

`pyinstaller` **刻意沒有版本號**。理由是這輪踩過的雷（`PITFALLS.md` ENV-1）：

> 版本號原本是從雲端容器抓的，而容器**不是正式 gate 的環境**；後來容器重置，
> 連那些套件都不在了。`pyinstaller==6.16.0` 那個數字更是憑空編的。
> PoliceDocSys 也踩過同一件事——`pypdf`／`reportlab` 兩行來自另一支沒有
> pytest 的直譯器，而這種不一致**靠人工看不出來**。

所以：本機裝好之後，用實際版本把它釘上去再 commit。**不要從別處抄一個數字填**。

```powershell
python -m pip show pyinstaller     # 看實際版本
```

其餘四個 pin（`PySide6==6.11.1`、`openpyxl==3.1.5`、`pytest==9.1.1`、
`pytest-qt==4.5.0`）已對齊 PoliceDocSys 的 gate 環境，但**第一次在本機跑測試時
請確認沒紅**——`TestPinnedVersions` 會把不一致直接指出來。

### 不用另外裝的

- **標楷體**：Windows 內建（`DFKai-SB`），PDF 就是用它。
  ⚠️ 雲端容器**沒有**這支字型，所以我那邊算的字寬不準——版面最終要上機定案。
- **Qt 系統函式庫**：只有 Linux／無 GUI 環境才要（`libegl1` 那一串，見
  `PITFALLS.md` QT-1），Windows 不必。
- **Excel**：測試不需要，但**版面驗收一定要**（縮放比例、頁數只有 Excel 看得到）。

### 跑測試

```powershell
python -m unittest discover -s tests -t .
python -m unittest tests.test_no_pii        # push 前必跑
```

⚠️ `-t .` 不可省，否則 `tests` 被當頂層目錄、`tests/__init__.py` 不會載入。

⚠️ 個資防呆預設會 **skip**。要啟用：
`copy tests\pii_denylist.local.txt.example tests\pii_denylist.local.txt`，
把要防的真名填進去（該檔已 gitignore，刻意不入庫）。

## 3. 已完成（221 項測試通過，全在 `main` 上）

```
lib/rota.py           排班演算法        ★ 零相依
lib/layout_model.py   版面模型          ★ 零相依
lib/db_schema.py      結構唯一來源（含所有 trigger）
lib/db_utils.py       連線慣例、App_Settings
lib/db_seed.py        種子資料（假名模板 + 一份草稿）
lib/ruleset.py        草稿↔啟用狀態機
lib/plan.py           月計畫：建立、接續、組版
lib/theme.py          全域樣式公版（自 PoliceDocSys 搬入）
export/xlsx_writer.py A3 橫式 xlsx（openpyxl）
export/pdf_writer.py  A3 橫式 pdf（QPdfWriter）
res/buttons/*.svg     勾選框打勾圖 + 下拉箭頭（自 PoliceDocSys 搬入）
```

★ 這兩支零 Qt、零資料庫相依，是刻意的——最容易算錯的部分不必上機就驗得到。

端對端跑過：建規則 → 啟用 → 配對 → 產 10 月 → 接續產 11 月 → 出 xlsx 與 pdf，
跨月連續性正確（10/31 是 `11`、11/1 是 `12`）。

## 4. 未完成——⚠️ 這些正是要你在本機做的

- [ ] `ui_utils/*` 公版元件（自 `PoliceDocSys` 搬，清單見 `MIGRATION.md`）
- [ ] `main.py` 與 `tabs/` 四個分頁：**產生月表／輪番設定／人員／維護**
- [ ] 配對彈窗（規格見 `DEVELOPER.md` §4）
- [ ] 列印三層驗收網（`tools/print_baseline.py` 那一套）
- [ ] `lib/version.py` ＋ `tools/bump_version.py`
- [ ] PyInstaller `--onefile` 打包

**建議順序**：`ui_utils` → 人員分頁（最單純，可驗證 theme 與勾選框）→
輪番設定 → 產生月表＋配對彈窗 → 維護 → 打包。

## 5. 維護者在這輪對話裁示的事（版面數字都在這）

### 業務規則

- 槽位序列 20 格，休在 **6、7、13、14、19、20**；一人一欄、一天一列
- **番號沒動就接上月底；番號動了就從 1 日照使用者輸入重來**
- **規則換版強制走重設**，程式要鎖住「接續上月」選項並說明原因
- 草稿最多 3 份（所長要挑方案）、**啟用時才配版號**、啟用後不可逆
- 「最新版」**用算的**，不存 `is_latest` 欄位

### 版面（照現行紙本）

```
標題 │ 日期 星期 │ 大輪番20 │ 日期 星期 │ 固定番8 │ 日期 星期 │
     同仁專案臨檢 │ 早 中 晚 │ 幹部6 │ 快打勤務 │ 日期 星期
```

- 標題在**最左邊一整欄直書**，不是橫置頁首
- 欄標題**只要超過一個字就直書**（姓名、日期、星期、快打勤務都是）
- 欄寬權重：輪番 **1.1**、固定番 **1.2**、劃假（早中晚）**1.4**、幹部 **1.2**、
  日期／星期 **1.0**
  - ⚠️ 同仁專案臨檢與快打勤務**維護者沒指名，暫用 1.2**，待確認
- 邊界四邊 5mm、**水平＋垂直置中**、**不設凍結窗格**
- 休與週六日印紅、**女警姓名印紅（番號不變色）**

### 已否決，不要再提案

常設名單（`group_member`）、配對獨立成分頁、把錨點綁在人身上、永久起算日、
同一人跨兩個番組、權限系統、班別註記由程式算、舊資料匯入。理由見
`CLAUDE.md` 與 `DEVELOPER.md` §9。

## 6. 協作偏好（維護者明講過的）

- ⚠️ **不懂就問，不要自己亂做**。他說過兩次「你跑太快了」「我覺得你要開始亂做了」
- 一次只推進一個決策，規則沒釘死之前不要設計下一層
- 他給的原則就照做，不要自行「優化」成更聰明的版本
- 現場要調的東西**一律做成設定**，不要寫死判斷式

## 7. 容器做不到、本機才做得到的事（這輪的血淚）

雲端這邊**沒有 Excel、沒有 GUI、沒有標楷體**，所以以下只能靠上機：

- Excel 實際的縮放比例與頁數（這輪「明明放得下卻被縮一級」是靠維護者回報
  「1/1」才定案的，見 `PITFALLS.md` XLS-3）
- 125% 縮放下的切字、欄寬、裁切
- 真實字型下的字寬（容器用替代字型，算出來不準）

⚠️ **你在本機有這些，請善用**：改完版面直接開檔案看、截圖比對紙本，
不要像我一樣來回猜三輪。

## 8. 一個仍未解的疑問

`DEVELOPER.md` §6 的待決清單已清空，但有一項小的還懸著：

> 「同仁專案臨檢」與「快打勤務」兩個區塊的欄寬權重，維護者只指定了輪番
> 1.1 / 固定番 1.2 / 劃假 1.4 / 幹部 1.2，這兩個沒指名，目前暫用 1.2。

開工前順手問一下就好。
