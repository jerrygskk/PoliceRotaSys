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

- **LAY-5**: **欄寬／列高寫死，人一調動版面就爛** → 派出所人員會調動，欄數
  每個月都可能不同。寫死的話人多了超出頁寬、被 fitToPage 縮到看不清楚，人少
  了右邊留一大片空白（28 天的月份同理，下面會空 3 天的高度）。正解：**把可
  列印寬高依權重分給各欄各列**，並夾在可讀性上下限之間；欄數多到連下限都排
  不下時才交給 fitToPage。容量以 `xlsx_writer.max_columns_per_page()` 查得，
  目前約 58 欄。回歸測試 `tests/test_export.py::TestAdaptiveWidth`。
- **LAY-7**: **跨欄註記只按行高算字級，長行右邊被切掉** → 「晚班:(1-5、16)」
  的收尾括號就這樣不見過。字級要依**最長那一行**的實際字寬縮
  （`fontMetrics().horizontalAdvance`），不是只看行高。
- **LAY-8**: **xlsx 想在一格裡放多種顏色的文字**（註記已改純文字黑字，本專案目前
  用不到，留作通則）→ 一個儲存格只能有一種
  `Font`，做不到。要多色必須走 RichText（`openpyxl.cell.rich_text.CellRichText`
  ＋ `TextBlock`／`InlineFont`）。
- **LAY-6**: **窄欄裡的多字標題被切掉** → 「快打勤務」四個字橫排塞在資料欄
  寬裡必定切字；「日期」「星期」同理。欄標題**只要超過一個字就直書**。

- **LAY-9**: **姓名列高度寫死，長標題與多行註記被靜默切掉** → 「同仁專案臨檢」
  六個字直書、跨欄註記四行，都放不進寫死的 62pt。⚠️ **Excel 放不下就是切掉，
  不會有任何警告**，只有印出來才看得到。正解：依實際內容算——取「最長直書標題
  所需高度」與「註記行數所需高度」兩者較大者（`xlsx_writer.name_row_height`）。
- **LAY-10**: **欄寬夾到上下限後沒把差額還給其他欄** → 窄欄被夾寬時總寬會超出
  頁寬（40 人時多出 3.6pt），整張表被 fitToPage 白白縮小一次。正解是**反覆重
  分配**：每輪把已夾住的欄固定下來，剩餘寬度再按權重分給還沒夾住的欄。
- **LAY-11**: **兩個 renderer 各自定義欄寬權重** → Excel 印出來會跟 PDF 不一樣
  寬，而「兩邊長一樣」正是當初抽出版面模型的理由。權重一律放
  `lib/layout_model.column_weight`，renderer 只能引用。

- **LAY-12**: **邊界留太多，欄寬白白讓掉** → openpyxl 的 `page_margins` 預設
  左右各 **0.75 吋（19mm）**，A3 橫式兩邊加起來吃掉 38mm，換算成欄寬等於少掉
  一個多人的空間。明設 5mm（一般雷射印表機的安全下限）；PDF 的
  `setPageMargins` 同步。

- **LAY-13**: **PDF 最外圈的框線整條不見** → 框線畫在 `x=0`／`y=0`，有一半落在
  頁面外被裁掉；標題欄在最左邊，所以整欄看起來沒有格線。正解：框線給明確寬度
  （`BORDER_PX`）並把整張表**往內縮半個線寬**再畫。
  ⚠️ 預設的 cosmetic pen（寬度 0）更容易中招，因為它的實際寬度由裝置決定。

#### XLS：openpyxl

- **XLS-1**: **`page_setup.paperSize` 拿常數比對得到 `8 != '8'` 的假失敗**
  → `ws.PAPERSIZE_A3` 是**字串** `'8'`，但存檔再讀回來是 **int** `8`。
  兩邊都轉 `int` 再比。
- **XLS-2**: **設了 `fitToWidth`／`fitToHeight`，Excel 卻不照做**
  → 只設 `page_setup` 不夠，還要 `ws.sheet_properties.pageSetUpPr.fitToPage = True`，
  否則 Excel 直接忽略縮放設定（`export/xlsx_writer.py:_setup_page`）。
- **XLS-5**: **合併儲存格只有一邊有框線** → Excel **不會**替合併範圍補框線。
  框線只設在左上角那一格時，合併後只畫得出那一格的邊，其餘三邊是空的——標題欄
  合併整欄，於是整欄看不到格線。正解：合併**之前**先替範圍內每一格都設 border
  （`export/xlsx_writer.py:_border_range`）。
- **XLS-4**: **欄寬換算每欄多加 5px，整張表比算的窄 16%** → 常見公式寫成
  `pixels = width × MDW + 5`，那是 Excel **UI 顯示**「8.43 (64 像素)」時的算法；
  **實際版面佔的寬度是 `width × MDW`**，那 5px 在 Excel 把「可見字元數」換算成
  儲存值時就已經算進去了。48 欄各多算 5px ＝ 多算 240px ≈ 64mm：程式以為排滿
  410mm，Excel 只排了 346mm，預覽列印左右各留一大片白。
  ⚠️ **分辨法**：看預覽列印裡表格佔頁面的比例——**水平與垂直比例不同**就不是
  縮放問題（縮放會等比例），而是某個方向的換算錯了。本例水平 84%、垂直 98%。
  回歸測試直接驗毫米（`test_a_full_sheet_really_spans_the_printable_width_in_mm`），
  只驗「有沒有填滿計算值」會一起錯過去。
- **XLS-3**: **`fitToPage` 明明放得下也會縮一級，左右白掉一大片** → 「調整成
  1 頁寬 1 頁高」算頁面分割時比實際保守。現場實測：表格自然尺寸 410 × 287mm、
  可列印區也是 410 × 287mm，**關掉 fitToPage 用 100% 印出來是紮紮實實的 1/1**，
  開著卻仍然縮小、上下貼滿而左右留白。正解：**放得下就固定
  `scale = 100` 並關掉 fitToPage**，欄數真的超出容量時才讓它接手
  （`fits_in_one_page()`）。
  ⚠️ 這類問題**容器驗不出來**——openpyxl 只負責寫檔，Excel 怎麼排版看不到，
  只能請維護者開「版面設定」回報縮放比例與頁數。

- **XLS-6**: **Excel 打不開 openpyxl 寫的檔（COM `Workbooks.Open` 失敗）** →
  CellRichText 裡有一段**只含換行**的 TextBlock，存檔時被當空白吃成空字串，Excel 判定毀損。
  換行併進前後的文字段。⚠️ 用 COM 轉 PDF 驗證時要先刪舊 PDF，否則轉檔失敗會看到舊圖。

#### QT：Qt 與 PDF 輸出

- **QT-1**: **`import PySide6.QtGui` 在容器裡 `ImportError: libEGL.so.1`**
  → PySide6 的 wheel 不含系統圖形函式庫。離線環境需
  `apt-get install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1`，
  並設 `QT_QPA_PLATFORM=offscreen`。⚠️ 與程式無關，不要往 code 裡查。
- **QT-2**: **`QPdfWriter` 匯出時沒有 `QApplication` 會當掉**
  → 匯出 PDF 不需要完整的 `QApplication`，但**需要 `QGuiApplication`** 才能量字。
  `export/pdf_writer.py` 自己確保有一個，呼叫端不必先開。
- **QT-3**: **下拉／輸入框一取得焦點就切字（月份「10」變「1C」）**
  → 公版樣式焦點時外框 1px → 2px，內距沒跟著減，文字區每邊少 1px；寬度由
  `sizeHint` 算得剛好的元件就被吃掉尾字。PoliceDocSys 陳報頁踩過同一件事。
  正解在全域公版 `lib/theme.py`：**`:focus` 外框加粗幾 px，內距就減幾 px**
  （彈窗內另有一組內距，`QDialog QComboBox:focus` 等要一起補）。寬度剛好的
  下拉再給 `setMinimumWidth` 留餘裕——125% 下 `sizeHint` 本來就不準。
- **QT-4**: **套了樣式表的 `QTableWidget`，`item.setBackground()` 畫面上看不到**
  → 表格公版 `TABLE_SS` 有 `QTableWidget::item` 規則，Qt 改走樣式表繪製後就不畫
  模型的 BackgroundRole；資料確實設進去了（讀得回來），只是沒畫。要標色的表格
  掛一個先 `fillRect` 底色再畫文字的 delegate（`pairing_dialog._BackgroundDelegate`）。
  ⚠️ 單元測試讀 `item.background()` 會通過，**只有截圖看得出來**。

- **QT-5**: **用 `tightBoundingRect` 量字來放大，中文字偏小又偏下** → 標楷體的中文字
  `QFontMetricsF.tightBoundingRect` 回傳的是**整個字框**，不是筆畫：「休」量到 200
  實際筆畫 165，「一」實際只有 28 高也量成整框；數字卻量得準。拿它算字級與置中，
  中文字放大不夠、還往下偏（實測踩過）。正解：把字實際畫到灰階點陣、掃描墨跡取範圍
  （`pdf_writer._ink_rect`，有快取）。
  ⚠️ 只看數字格會以為量對了，要看「休」與星期那欄才看得出來。
- **QT-6**: **PDF 裡「日」「星」整個擠到格子左邊，程式量的位置卻是對的** → 標楷體
  （DFKai-SB）要靠字型微調指令才會把筆畫擺對；`drawText` 把字型子集嵌進 PDF，交給
  閱讀器畫，不跑微調的閱讀器（QtPdf 預覽、部分瀏覽器內建）就畫歪。正解：
  `QPainterPath.addText` 由 Qt 算好外框再 `fillPath`（`pdf_writer._draw_text`），
  任何閱讀器都一樣；代價是 PDF 文字不能選取搜尋。粗體要自己描邊補回。

#### ENV：環境與相依

- **ENV-1**: **`requirements` 的版本號抄自另一個環境，靠人工看不出來** →
  PoliceDocSys 踩過（`pypdf`／`reportlab` 兩行來自另一支沒有 pytest 的直譯器），
  本專案也踩過一次：版本號抄自雲端容器，而容器不是正式 gate 的環境，之後容器
  重置連那些套件都不在了。⚠️ **版本號必須是正式 gate 那支 Python 的實際快照**，
  而且**不知道版本就不要填**（`pyinstaller` 曾刻意不釘，直到本機裝好才依實裝版本釘上）。
  由 `tests/test_environment_contract.py::TestPinnedVersions` 自動把關：裝好的
  版本與 pin 不符即紅。
- **ENV-2**: **`importlib.metadata.version("PySide6")` 報 PackageNotFound，但
  `import PySide6` 明明成功** → PySide6 可由 `PySide6` 或 **`PySide6-Essentials`**
  提供，**發行名稱與 import 名稱不同**。查版本時兩個都要試，否則會誤判成沒裝
  而靜默跳過檢查。

#### PKG：打包

- **PKG-1**: **onefile exe 50MB，六成是用不到的 Qt 元件** → PySide6 的 PyInstaller hook
  照單全收：`opengl32sw.dll`（20MB）、QML／Quick、`Qt6Pdf`、`Qt6Network`、多餘圖片
  格式與語系檔。這些是以 **binary 身分**收進來的，`--exclude-module` 砍不掉，只能在
  spec 裡過濾 `a.binaries`／`a.datas`（`tools/pyi_prune.py`）。瘦身後約 27MB。
  ⚠️ 所以 spec 要入庫（DEVELOPER §10）。
- **PKG-2**: **沒人呼叫的 `loadUi` 讓 OpenGL 整串砍不掉** → `ui_utils` 從公文系統搬來時
  留著 `from PySide6.QtUiTools import QUiLoader`；UiTools 連結期硬性需要
  `Qt6OpenGLWidgets`／`Qt6OpenGL`，跟程式有沒有用 OpenGL 無關。本專案不用 `.ui` 檔，
  已拿掉。⚠️ 反過來說：日後若有人加回 QtUiTools，`pyi_prune` 砍 OpenGL 會讓打包版
  **開機就 `ImportError: DLL load failed`**，原始碼跑卻完全正常。
- **PKG-3**: **打包版多出 `libcrypto-3-x64.dll`／`libssl-3-x64.dll`** → 打包機 PATH 上有
  Git for Windows 時，PyInstaller 從 `C:\Program Files\Git\mingw64\bin` 撿到那份
  OpenSSL（公文系統 PKG-6 同一件事）。由 `pyi_prune` 依**來源路徑**濾掉；不要改成
  「build 前記得清 PATH」，靠人記得的做法換台機器就失效。

#### TST：測試

- **TST-1**: **用純文字搜尋檢查「有沒有用到某套件」，被自己的註解抓到**
  → `test_environment_contract` 第一版拿 `assertNotIn("reportlab", 原始碼)` 檢查，
  結果 `pdf_writer` 註解裡寫著「用 QPdfWriter 而不是 reportlab」而爆掉。
  這類檢查一律**解析 import**（`ast`），不要搜字串。
- **TST-2**: **`openpyxl` 的 `ws[2]` 索引與欄號差 2**
  → `ws[2]` 回傳整列、從 A 欄起算，而日期格從 C 欄開始，所以第 n 天是
  `row[n + 1]`。寫死索引前先想清楚起點。
