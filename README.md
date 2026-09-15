# PoliceRotaSys

警察勤務輪番表產生器。依單位的輪番規則，產生每月每位同仁的番號，
輸出 **A3 橫式**的 Excel 與 PDF。

> ⚠️ **開發中，尚未有可執行的 GUI。** 核心邏輯（排班推算、規則版本、月計畫、
> xlsx 與 pdf 輸出）已完成並有 178 項測試；畫面的部分還沒開始。
> 設計文件見 `CLAUDE.md`（業務規則與協作規範）與 `DEVELOPER.md`（架構與資料庫）。

## 這支程式在做什麼

一個群組有一條**槽位序列**，每位同仁錯開一格，每天往後推一格，
跑完最後一格回到第一格。例如 20 格的序列：

```
格位: 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20
代碼: 01 02 03 04 05 休 休 08 09 10 11 12 休 休 15 16 17 18 休 休
```

槽位格數、哪幾格是休、代碼怎麼取（`01`／`A`／`甲`），全部是**設定**，
不是寫死的程式邏輯——不同單位改設定即可。

## 特色

- **多組輪番**：一個單位可以有數個群組，各有各的循環
- **固定番**：不隨日期前進的群組，與輪番群組共用同一套機制
- **代碼自訂**：預設可自動產生，也可逐格覆寫
- **規則版本凍結**：規則一經發版即不可修改，舊月份的表永遠重現得出來

## 開發

- Python 3.12 + PySide6 + SQLite
- runtime 相依為封閉清單：`PySide6`、`openpyxl`

```bash
python -m pip install -r requirements-dev.txt

# 全套件（⚠️ `-t .` 不可省）
python -m unittest discover -s tests -t .

# push 前必跑
python -m unittest tests.test_no_pii
```

⚠️ Linux／無 GUI 環境跑 PDF 測試要多兩件事，Windows 不必：設
`QT_QPA_PLATFORM=offscreen`，並安裝 Qt 的系統函式庫（`libegl1` 等，
PySide6 的 wheel 不含）。見 `PITFALLS.md` QT-1。

接手開發請先讀 `CLAUDE.md`、`DEVELOPER.md`、`PITFALLS.md`。

## 相關

姊妹專案 [PoliceDocSys](https://github.com/jerrygskk/PoliceDocSys)（公文管理系統）。
本專案的 UI 公版、測試基礎建設與踩雷知識多自該專案移植，對照見 `MIGRATION.md`。
