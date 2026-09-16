"""資料庫備份：開機自動 GFS 輪替、手動備份、損毀偵測、壓縮（自 PoliceDocSys 搬入）。

單機程式平時零備份，檔案毀損、誤刪一旦發生即無救。開機時在 `dbfile.db` 旁的
`backups/` 做三層帶日期的備份，各自輪替修剪：

- 每日：`dbfile_backup_day_YYYYMMDD.db`，每天第一次開啟時建一份，保留 `DAILY_KEEP` 份
- 每週：`dbfile_backup_week_YYYYMMDD.db`，每 ISO 週第一次開啟時建一份，保留 `WEEKLY_KEEP` 份
- 每月：`dbfile_backup_month_YYYYMMDD.db`，每月第一次開啟時建一份，保留 `MONTHLY_KEEP` 份

有設定異地備份位置（`App_Settings.backup_second_dir`）時，該處照同一套規則另備一份。
手動備份檔名帶時分（`dbfile_backup_manual_YYYYMMDD_HHMM.db`），不計入輪替、不會被刪。

備份用 sqlite3 backup API（一致性快照），先寫 `.tmp` 再 `os.replace` 原子換上
（中途失敗不會毀掉既有好檔）。**自動備份失敗一律靜默、寫 error.log，絕不擋開程式。**

⚠️ 本專案不做還原（DEVELOPER §3）：要還原時把備份檔蓋回 `dbfile.db`。
PoliceDocSys 的還原、救援視窗、筆數預覽都沒有搬。
"""
import logging
import os
import re
import sqlite3
from datetime import datetime

BACKUP_DIR_NAME = "backups"
DAILY_PREFIX = "dbfile_backup_day_"
WEEKLY_PREFIX = "dbfile_backup_week_"
MONTHLY_PREFIX = "dbfile_backup_month_"
MANUAL_PREFIX = "dbfile_backup_manual_"
DAILY_KEEP = 7     # 最近一週逐日
WEEKLY_KEEP = 4    # 約一個月
MONTHLY_KEEP = 12  # 約一年

_DAILY_RE = re.compile(r"^dbfile_backup_day_(\d{8})\.db$")
_WEEKLY_RE = re.compile(r"^dbfile_backup_week_(\d{8})\.db$")
_MONTHLY_RE = re.compile(r"^dbfile_backup_month_(\d{8})\.db$")


# ── 路徑 / 檔名 ─────────────────────────────────────────────────
def backup_dir(db_path):
    """備份子夾：與 dbfile.db 同資料夾下的 backups/。"""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), BACKUP_DIR_NAME)


def daily_filename(d):
    return f"{DAILY_PREFIX}{d.strftime('%Y%m%d')}.db"


def weekly_filename(d):
    return f"{WEEKLY_PREFIX}{d.strftime('%Y%m%d')}.db"


def monthly_filename(d):
    return f"{MONTHLY_PREFIX}{d.strftime('%Y%m%d')}.db"


def manual_filename(dt):
    return f"{MANUAL_PREFIX}{dt.strftime('%Y%m%d_%H%M')}.db"


# ── 純邏輯（可單測）────────────────────────────────────────────
def _parse_dates(regex, filenames):
    out = []
    for name in filenames:
        m = regex.match(name)
        if not m:
            continue
        try:
            out.append(datetime.strptime(m.group(1), "%Y%m%d").date())
        except ValueError:
            pass
    return out


def parse_daily_dates(filenames):
    return _parse_dates(_DAILY_RE, filenames)


def parse_weekly_dates(filenames):
    return _parse_dates(_WEEKLY_RE, filenames)


def parse_monthly_dates(filenames):
    return _parse_dates(_MONTHLY_RE, filenames)


def is_daily_due(existing_dates, today):
    """今天尚未備份過。"""
    return today not in existing_dates


def is_weekly_due(existing_dates, today):
    """既有週檔中沒有任何一份落在 today 的同一 ISO 週。"""
    wk = today.isocalendar()[:2]
    return not any(d.isocalendar()[:2] == wk for d in existing_dates)


def is_monthly_due(existing_dates, today):
    """既有月檔中沒有任何一份落在 today 的同一（年, 月）。"""
    ym = (today.year, today.month)
    return not any((d.year, d.month) == ym for d in existing_dates)


def prune_targets(dates, keep):
    """該刪除的日期：保留最近 keep 份，其餘較舊者刪。"""
    if keep is None or len(dates) <= keep:
        return []
    return sorted(dates)[:-keep]


# ── 錯誤白話 ───────────────────────────────────────────────────
# key＝Windows 錯誤碼（OSError.winerror）。
# ⚠️ 一律以錯誤碼判斷，不要比對錯誤訊息字串——不同語系 Windows 文字不同。
_WINERR_REASONS = {
    50: "網路位置不接受這項操作（常見於備份路徑只填到分享名稱、後面沒有再帶子資料夾）",
    51: "無法連線到網路上的這台電腦",
    53: "找不到這個網路路徑",
    55: "網路資料夾已不存在或未分享",
    64: "與這台電腦的連線已中斷",
    67: "網路名稱不正確或該分享已移除",
    1231: "無法連上網路，可能網路線鬆脫或電腦不在單位網路內",
}


def _is_disk_full(exc):
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return True
    low = str(exc or "").lower()
    return "database or disk is full" in low or "no space left" in low


def reason_for(exc):
    """把例外對應成一句原因短語；對照不到回「無法存取」。"""
    winerr = getattr(exc, "winerror", None)
    errno_ = getattr(exc, "errno", None)
    if winerr in _WINERR_REASONS:
        return _WINERR_REASONS[winerr]
    if _is_disk_full(exc):
        return "磁碟空間不足"
    if isinstance(exc, PermissionError) or errno_ == 13 or winerr == 5:
        return "沒有寫入權限，或檔案正被其他程式開啟"
    if isinstance(exc, NotADirectoryError):
        return "這個路徑是檔案、不是資料夾"
    if isinstance(exc, FileNotFoundError) or errno_ == 2 or winerr == 3:
        return "找不到這個資料夾"
    if isinstance(exc, sqlite3.DatabaseError):
        return "資料庫檔案讀取失敗，可能損毀或正被鎖定"
    return "無法存取"


def describe_dir_error(exc, path, is_extra=False):
    """備份資料夾存取失敗的白話說明（寫 error.log 第一行用）。"""
    where = "異地備份位置" if is_extra else "備份資料夾"
    tail = ("本次已略過異地備份，主備份不受影響。" if is_extra
            else "本次未能建立備份，請聯繫維護人員並提供 error.log。")
    return f"{where}無法使用：{path}（{reason_for(exc)}）。{tail}"


def brief_dir_error(path, is_extra=False):
    """給畫面顯示的短句（原因留在 error.log）。"""
    if is_extra:
        return f"異地備份位置無法使用：{path}。本次已略過異地備份。"
    return f"備份資料夾無法使用：{path}。本次未能建立備份。"


# 本次啟動的備份失敗紀錄 {備份資料夾: 短句}，只供維護分頁顯示，不重試。
_LAST_ERRORS = {}


def last_backup_error(bdir):
    return _LAST_ERRORS.get((bdir or "").strip())


# ── I/O ────────────────────────────────────────────────────────
def write_backup(db_path, dest):
    """以 sqlite3 backup API 做一致性快照；先寫 .tmp 再原子 replace。失敗會拋出。"""
    tmp = dest + ".tmp"
    try:
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(tmp, dest)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def do_backup(db_path, dest):
    """自動備份用：成功回 True、失敗回 False 並記 error.log，不拋例外。"""
    try:
        write_backup(db_path, dest)
        return True
    except Exception as exc:
        logging.error("備份檔寫入失敗：%s（%s）。", dest, reason_for(exc), exc_info=True)
        return False


def _prune(bdir, prefix, dates, keep):
    for d in prune_targets(dates, keep):
        try:
            os.remove(os.path.join(bdir, f"{prefix}{d.strftime('%Y%m%d')}.db"))
        except OSError:
            pass


def ensure_dir(bdir):
    """確保資料夾存在。

    ⚠️ 不可只寫 `os.makedirs(bdir, exist_ok=True)`：Windows 對 UNC 分享根目錄
    （`\\\\server\\share`）回的是 WinError 50，**即使資料夾存在也照樣拋**，
    異地備份會每次開機都靜默失敗（PoliceDocSys 踩過）。故先判斷已存在就放行。
    """
    if os.path.isdir(bdir):
        return
    os.makedirs(bdir, exist_ok=True)


def _run_gfs(db_path, bdir, today):
    ensure_dir(bdir)
    for prefix, parse, due, name, keep in (
        (DAILY_PREFIX, parse_daily_dates, is_daily_due, daily_filename, DAILY_KEEP),
        (WEEKLY_PREFIX, parse_weekly_dates, is_weekly_due, weekly_filename, WEEKLY_KEEP),
        (MONTHLY_PREFIX, parse_monthly_dates, is_monthly_due, monthly_filename, MONTHLY_KEEP),
    ):
        dates = parse(os.listdir(bdir))
        if due(dates, today) and do_backup(db_path, os.path.join(bdir, name(today))):
            dates.append(today)
        _prune(bdir, prefix, dates, keep)


def run_auto_backup(db_path, now=None, extra_dirs=None):
    """開機時呼叫：主備份（db 旁 backups/）＋可選異地位置，各自跑 GFS。

    每處各自 try：某處失敗（網路碟斷線、權限不足）不影響其他處，也不擋開程式。
    """
    today = (now or datetime.now()).date()
    dirs = [(backup_dir(db_path), False)]
    for d in (extra_dirs or []):
        if d and d.strip():
            dirs.append((d.strip(), True))
    for bdir, is_extra in dirs:
        try:
            _run_gfs(db_path, bdir, today)
            _LAST_ERRORS.pop(bdir, None)
        except Exception as exc:
            logging.error("%s", describe_dir_error(exc, bdir, is_extra), exc_info=True)
            _LAST_ERRORS[bdir] = brief_dir_error(bdir, is_extra)


def latest_backup_date(bdir):
    """該資料夾最新一份自動備份的日期；讀不到或沒有回 None。"""
    try:
        names = os.listdir(bdir)
    except OSError:
        return None
    dates = parse_daily_dates(names) + parse_weekly_dates(names) + parse_monthly_dates(names)
    return max(dates) if dates else None


def manual_backup_path(db_path, now=None):
    return os.path.join(backup_dir(db_path), manual_filename(now or datetime.now()))


def manual_backup(db_path, dest):
    """維護分頁「立即備份」：寫到 dest（由 manual_backup_path 取得）。失敗會拋出。"""
    ensure_dir(os.path.dirname(dest))
    write_backup(db_path, dest)


# ── 損毀偵測 ───────────────────────────────────────────────────
def _integrity(db_path, pragma, label):
    """回 True＝完好或無法判定（不擋開程式）；False＝明確損毀。

    ⚠️ OperationalError（鎖定／忙線）是 DatabaseError 的子類，要先攔下當「無法判定」，
    否則會把「資料庫忙線中」誤判成損毀。
    """
    if not os.path.exists(db_path):
        return True
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        try:
            rows = conn.execute(f"PRAGMA {pragma}").fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        logging.error("%s 無法執行（鎖定／忙線，非損毀判定）：%s", label, db_path, exc_info=True)
        return True
    except sqlite3.DatabaseError:
        logging.error("%s 開啟／執行失敗（疑似損毀）：%s", label, db_path, exc_info=True)
        return False
    except Exception:
        logging.error("%s 未預期例外（非損毀判定）：%s", label, db_path, exc_info=True)
        return True
    ok = len(rows) == 1 and rows[0][0] == "ok"
    if not ok:
        logging.error("%s 偵測到資料庫異常：%s / %s", label, db_path, rows)
    return ok


def quick_check(db_path):
    """每次開機：PRAGMA quick_check。"""
    return _integrity(db_path, "quick_check", "quick_check")


def deep_check_if_due(db_path, now=None):
    """每 ISO 週第一次開機多跑一次 PRAGMA integrity_check。

    到期與否看主備份資料夾本週有沒有週檔；週檔由同次開機稍後的自動備份建出，
    所以每週最多跑一次、不必另存狀態。資料夾不存在一律視為到期。
    """
    if not os.path.exists(db_path):
        return True
    today = (now or datetime.now()).date()
    try:
        due = is_weekly_due(parse_weekly_dates(os.listdir(backup_dir(db_path))), today)
    except OSError:
        due = True
    if not due:
        return True
    return _integrity(db_path, "integrity_check", "deep_check")


# ── 壓縮 ───────────────────────────────────────────────────────
def vacuum(db_path):
    """VACUUM 回收刪除月表後的空間；回傳（壓縮前, 壓縮後）位元組數。失敗會拋出。"""
    before = os.path.getsize(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    return before, os.path.getsize(db_path)
