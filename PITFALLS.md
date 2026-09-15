# 踩雷速查表（Pitfalls）

依主題分組；每條為「**症狀** → 解法（必要時括註原因）」。寫過的雷再踩會被點名。

⚠️ 本專案剛起步，多數條目仍在姊妹專案 `PoliceDocSys` 的 `PITFALLS.md`。
動 Qt 相關的東西之前**先去讀那一份**——UI／QSS／QTW／LAY／TAB 五組幾乎整包
適用（搬遷對照見 `MIGRATION.md`）。下面只記本專案自己踩到的。

#### GIT：版控

- **GIT-1**: **新增的 `lib/*.py` 沒進 commit，`git add -A` 與 commit 都不報錯**
  → GitHub 的 Python `.gitignore` 範本有一行 `lib/`（那是給 virtualenv 用的），
  把本專案的產品程式目錄整個擋掉。三件事湊在一起讓它很難發現：`add -A` 遇到
  被 ignore 的檔案是**靜默跳過**、commit 不報錯、而測試讀的是工作目錄的檔案
  所以**照樣全綠**。已移除該行並在 `.gitignore` 留註解。
  ⚠️ 新增頂層目錄時順手 `git check-ignore -v <路徑>` 確認一下。

#### XLS：openpyxl

- **XLS-1**: **`page_setup.paperSize` 拿常數比對得到 `8 != '8'` 的假失敗**
  → `ws.PAPERSIZE_A3` 是**字串** `'8'`，但存檔再讀回來是 **int** `8`。
  兩邊都轉 `int` 再比。
- **XLS-2**: **設了 `fitToWidth`／`fitToHeight`，Excel 卻不照做**
  → 只設 `page_setup` 不夠，還要 `ws.sheet_properties.pageSetUpPr.fitToPage = True`，
  否則 Excel 直接忽略縮放設定（`export/xlsx_writer.py:_setup_page`）。

#### QT：Qt 與 PDF 輸出

- **QT-1**: **`import PySide6.QtGui` 在容器裡 `ImportError: libEGL.so.1`**
  → PySide6 的 wheel 不含系統圖形函式庫。離線環境需
  `apt-get install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1`，
  並設 `QT_QPA_PLATFORM=offscreen`。⚠️ 與程式無關，不要往 code 裡查。
- **QT-2**: **`QPdfWriter` 匯出時沒有 `QApplication` 會當掉**
  → 匯出 PDF 不需要完整的 `QApplication`，但**需要 `QGuiApplication`** 才能量字。
  `export/pdf_writer.py` 自己確保有一個，呼叫端不必先開。

#### TST：測試

- **TST-1**: **用純文字搜尋檢查「有沒有用到某套件」，被自己的註解抓到**
  → `test_environment_contract` 第一版拿 `assertNotIn("reportlab", 原始碼)` 檢查，
  結果 `pdf_writer` 註解裡寫著「用 QPdfWriter 而不是 reportlab」而爆掉。
  這類檢查一律**解析 import**（`ast`），不要搜字串。
- **TST-2**: **`openpyxl` 的 `ws[2]` 索引與欄號差 2**
  → `ws[2]` 回傳整列、從 A 欄起算，而日期格從 C 欄開始，所以第 n 天是
  `row[n + 1]`。寫死索引前先想清楚起點。
