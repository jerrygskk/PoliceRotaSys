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

#### LAY：版面

- **LAY-1**: **整張表的軸向做反（日期當欄、姓名當列）** → 紙本是**旋轉 90°
  掃描**的，掃描件上看起來橫的東西在原始 Excel 裡是直的。正解：**X 軸是人名
  （一人一欄）、Y 軸是日期（一天一列）**，三個區塊左右並排、日期與星期欄在
  區塊之間重複。⚠️ 動版面前先確認軸向；回歸測試
  `tests/test_layout_model.py::TestAxisOrientation`。
- **LAY-3**: **Excel 印出來字太小、下面留一大片空白** → `fitToPage`
  **只會縮不會放**。第一版沒算版面尺寸，欄寬加總超過頁寬、列高加總只有頁高
  的七成，於是 Excel 依寬度把整張表縮小，字跟著變小、下半頁空著。正解是把
  **自然尺寸算到貼近可列印區**（`export/xlsx_writer.py` 開頭有換算式：
  `pt = (7 × 欄寬 + 5) × 0.75`），fitToPage 只當人數超量時的安全網。
  ⚠️ 也要明設 `page_margins`——openpyxl 預設左右各 0.75 吋，比想像中大很多。
- **LAY-4**: **PDF 字級寫死點數，換一支字型就爆版** → 格子大小會隨人數變、
  字寬會隨字型變，字級不跟著走必然出事。一律**由格子幾何算出字級**並用
  `setPixelSize`（裝置單位），不要用 `setPointSize`——`QPdfWriter` 是 300dpi
  的繪圖裝置，用像素才算得準塞不塞得下。姓名直書另依字數縮（三個字放得下
  不代表四個字放得下）。
  ⚠️ 字型要給**一整串 fallback**（`QFont.setFamilies`），只寫「標楷體」一支
  時，沒有那支字型的機器上 Qt 會**靜默**換成系統預設，字寬全走鐘。
- **LAY-2**: **姓名直書畫成「橫書躺著」** → 不要用 `painter.rotate()` 把整串字
  轉 90°，紙本上的姓名是**正的字一個個疊下來**。PDF 走
  `pdf_writer._draw_vertical`（逐字畫）；xlsx 用 `textRotation=255`（Excel 的
  直排值，不是 90）。

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
