# PoliceRotaSys

勤休預定表產生器。依單位的輪番規則，產生每月每位同仁的番號，
輸出 **A3 橫式**的 Excel 與 PDF。

> 目前為 **v0.1.0 beta（試用版）**，執行檔下載：
> [Releases](https://github.com/jerrygskk/PoliceRotaSys/releases)。
> 資料存在 exe 旁的 `dbfile.db`，換電腦或更新版本時要一起帶走。
> 更新版本時把新 exe 放在原本資料庫旁邊開啟即可，缺少的欄位會自動補上（建議先備份一份）。

## 這支程式在做什麼

一個群組有一條**槽位序列**，每位同仁錯開一格，每天往後推一格，
跑完最後一格回到第一格。例如 20 格的序列：

```
格位: 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20
代碼: 01 02 03 04 05 休 休 08 09 10 11 12 休 休 15 16 17 18 休 休
```

槽位格數、哪幾格是休、代碼怎麼取（`01`／`A`／`甲`），全部是**設定**，
不是寫死的程式邏輯——不同單位改設定即可。

## 功能

- **輪番設定**：多份輪番模板（方案）；群組、格位、輪休、自訂代碼；
  群組可設「左側顯示快速識別日期」「反向排序（右往左）」
- **人員設定**：名單、女警標記（印紅字）、在職／離職
- **產生月表**
  - **接續上月**：沿用上月規則與名單，番號從上月最後一天接著推
  - **自訂起始**：配對彈窗指定 1 日站位（可打字選人、點名單帶入）
  - 已產生的月份可重新產生覆蓋、可刪除；過去月份多一次提醒
  - 匯出 Excel 與 PDF（預設存到桌面，可另存到其他位置）；預覽支援滾輪縮放與拖曳
- **月表快照**：產生時把當月規則與名單拷一份存下，之後改模板、改名字、
  刪人，都不影響已產生的月表
- **功能維護**：月表標題（單位名稱）；資料庫備份（每天第一次開啟自動備份到程式旁的
  `backups` 資料夾，保留 7 天／4 週／12 個月，可加異地備份位置，也可立即備份）；壓縮資料庫
- 開啟時會先檢查資料庫是否損毀；損毀時程式會提示並關閉，請從 `backups` 取回最近的備份
  （改名為 `dbfile.db` 蓋回程式旁）

尚未完成：列印驗收網。

## 開發

- Python 3.12 + PySide6 + SQLite
- runtime 相依為封閉清單：`PySide6`、`openpyxl`

```bash
python -m pip install -r requirements-dev.txt

# 執行
python main.py

# 全套件（⚠️ `-t .` 不可省）
python -m unittest discover -s tests -t .

# push 前必跑
python -m unittest tests.test_no_pii

# 打包（onefile，spec 已入庫）
python -m PyInstaller --clean --noconfirm PoliceRotaSys.spec
```

⚠️ Linux／無 GUI 環境跑 PDF 測試要多兩件事，Windows 不必：設
`QT_QPA_PLATFORM=offscreen`，並安裝 Qt 的系統函式庫（`libegl1` 等，
PySide6 的 wheel 不含）。見 `PITFALLS.md` QT-1。

接手開發請先讀 `CLAUDE.md`、`DEVELOPER.md`、`PITFALLS.md`。

## 相關

姊妹專案 [PoliceDocSys](https://github.com/jerrygskk/PoliceDocSys)（公文管理系統）。
本專案的 UI 公版、測試基礎建設與踩雷知識多自該專案移植，對照見 `MIGRATION.md`。
