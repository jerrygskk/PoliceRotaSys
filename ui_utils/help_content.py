"""四個主分頁的程式內使用指引與 HTML renderer。"""
from html import escape

from lib.theme import (
    HELP_ACCENT_COLOR,
    HELP_BTN_DANGER_COLOR,
    HELP_BTN_NORMAL_COLOR,
    HELP_BTN_PRIMARY_COLOR,
    HELP_MUTED_TEXT_COLOR,
    HELP_RULE_COLOR,
    HELP_WARNING_BACKGROUND_COLOR,
    HELP_WARNING_TEXT_COLOR,
    TEXT_COLOR,
)


HELP_TITLES: dict[int, str] = {
    0: "產生月表",
    1: "輪番設定",
    2: "人員設定",
    3: "功能維護",
}


HELP_PAGES: dict[int, tuple[tuple[str, object], ...]] = {
    # 四頁都照同一個骨架：①這頁做什麼 ②還沒有資料時怎麼開始 ③設好之後接到哪一頁。
    # ⚠️ 全程圍繞「輪番設定訂規則 → 人員設定建名單 → 產生月表組合」這條主線，
    #    細節分節寫短段，提示一律用 note（單一規格，不換顏色）。
    0: (
        ("paragraph", "本分頁把輪番規則與人員名單組合成當月的勤休預定表，"
                      "產生後可以直接預覽，且匯出 Excel 與 PDF。"),

        ("title", "第一次產生月表"),
        ("steps", (
            "先到「輪番設定」確認輪番規則，再到「人員設定」確認名單。",
            "回到本分頁選擇年月，按「自訂起始」。",
            "在配對視窗選擇一份模板，為每個番號指定人員，再按「確定」。",
            "看過預覽確認無誤，再按「匯出」。",
        )),
        ("note", "第一次產生月表只能使用「自訂起始」。因為沒有上個月的月表，「接續上月」無法使用。"),

        ("title", "之後每個月"),
        ("columns", (
            ("接續上月", "番號沒有變動時使用。沿用上個月的規則、名單與最後一天的狀態，接著推算到本月底，不必重新配對。"),
            ("自訂起始", "番號有變動時使用。重新選擇模板，並重新安排 1 日的起始欄位。"),
        )),
        ("paragraph", "兩種方式由承辦人決定，程式不會自行判斷。"),

        ("title", "重做與刪除"),
        ("paragraph", "已經產生過的月份仍然可以重新產生，確認後新的結果會取代原有月表；"
                      "不需要的月表可以按「刪除月表」移除。屬於過去月份時，程式會多一次提醒。"),
        ("note", "覆蓋與刪除都無法復原。重要的月表請先到「功能維護」按「立即備份」保留一份備份。"),

        ("title", "匯出"),
        ("paragraph", "按「匯出」會一次產生 Excel 與 PDF，預設存到桌面；也可以只在這一次另外選擇資料夾。"),
        ("paragraph", "需要重印舊的月份時，選回該月份再按一次「匯出」即可。"),
        ("muted", "重新匯出時讀取的是該月儲存的快照；之後修改模板、更改姓名或將人員改為離職，都不會影響已經產生的月表。"),
    ),
    1: (
        ("paragraph", "本分頁設定輪番規則：月表上有哪些群組、番號如何排列、哪幾格是輪休。"
                      "一整套規則會存成一份模板，可以同時儲存多份方案。"),

        ("title", "還沒有模板時"),
        ("steps", (
            "左側內建一份範例模板，可以直接選取修改；要另外建立一份請按「新增」。",
            "在群組表按「新增」建立群組，填寫名稱、模式與番號範圍。",
            "儲存後在下方的欄位區點選哪幾格是輪休；需要自訂代碼時，雙擊該欄位輸入。",
            "所有群組都填好之後按「檢查規則」，確認群組之間沒有重複的番號。",
        )),

        ("title", "三種群組模式"),
        ("columns", (
            ("輪番", "每天往後推一格；點一下欄位可以切換為輪休。"),
            ("固定番", "番號不隨日期前進；代號可以選擇印在姓名上方或下方，不提供輪休設定。"),
            ("空白欄", "只列印欄位與格線供手寫，不配對人員，也不計入番號。"),
        )),

        ("title", "番號範圍怎麼填"),
        ("paragraph", "使用列印頁數的寫法一次填完，例如 1-20、21-25、A-F；也可以用逗號分段，例如 1-5,8-12。"
                      "按下儲存時，程式會把範圍展開成一格一格的欄位。"),
        ("note", "修改模式或番號範圍後再儲存，這一組原有的輪休與自訂代碼會全部清空，請重新逐格確認。"),

        ("title", "設定完成之後"),
        ("paragraph", "模板只儲存規則，不包含人員。接著到「人員設定」維護名單，"
                      "再到「產生月表」以「自訂起始」把人員配到各個欄位。"),
        ("muted", "模板隨時可以修改或刪除，已經用過的也一樣：每份月表都儲存自己的快照，不會受到影響。"),
    ),
    2: (
        ("paragraph", "本分頁維護可以排班的人員名單，以及名單的顯示順序。"
                      "配對月表時可以選擇的人員，就是這裡標記為在職的人。"),

        ("title", "還沒有名單時"),
        ("steps", (
            "程式內建一份示範名單。選取一列按「修改」，改成實際同仁的姓名。",
            "人數不足時按「新增」補上。勾選女警標記後，月表會把該員姓名印成紅色。",
            "調整顯示順序後按「儲存排序」才會寫入；尚未儲存就關閉程式時，會先出現提醒。",
        )),
        ("paragraph", "順序可以拖拉列首的把手調整，也可以直接修改序號。"),

        ("title", "在職與離職"),
        ("columns", (
            ("在職", "會出現在配對視窗的可選名單中。"),
            ("離職", "不再出現在新月表的可選名單，在名單上以灰色顯示。"),
        )),
        ("note", "程式不提供刪除人員。同仁離開現職時，請將狀態改為離職，"
                 "過去的月表才查得到當時的姓名。"),

        ("title", "設定完成之後"),
        ("paragraph", "到「產生月表」按「自訂起始」後，這份名單會顯示在配對視窗右側，"
                      "點選姓名即可填入左側的欄位。"),
        ("muted", "這裡的順序只影響名單與配對下拉選單的顯示，不是輪番的番號；"
                  "誰站哪一格，是產生月表時才決定的。"),
    ),
    3: (
        ("paragraph", "本分頁是程式本身的維護項目：月表要列印的單位名稱、資料庫備份，"
                      "以及刪除月表後的空間回收。請從左側選單切換項目。"),

        ("title", "第一次使用請先完成這兩項"),
        ("steps", (
            "在「月表標題」填入單位名稱並按「儲存」，這個名稱會列印在月表最左邊的標題欄。",
            "在「資料庫備份」可以指定一個異地備份位置（另一顆硬碟或網路磁碟），留空表示不啟用。",
        )),

        ("title", "備份怎麼運作"),
        ("paragraph", "每天第一次開啟程式會自動備份到程式旁的 backups 資料夾，"
                      "保留近期的每日、每週與每月備份。已設定異地位置時，會一併備份一份到該位置。"),
        ("paragraph", "按「立即備份」另存的備份不參與自動輪替，也不會被自動刪除。"),
        ("note", "程式不提供還原按鈕。需要還原時請先關閉程式，將要使用的備份檔複製到程式旁，"
                 "更名為 dbfile.db 覆蓋原本的檔案；覆蓋之前，請先把現有檔案另存一份留底。"),

        ("title", "壓縮資料庫"),
        ("paragraph", "刪除月表後，資料庫檔案不會立刻變小。按「壓縮資料庫」可以回收未使用的空間，"
                      "完成後會顯示壓縮前後的大小。"),

        ("title", "換電腦或搬移資料夾"),
        ("paragraph", "請先關閉程式，再把執行檔、同一個資料夾裡的 dbfile.db 與 backups 一起複製到新位置。"
                      "完成後回到本分頁，確認異地備份位置仍然可以連線。"),
        ("muted", "修改單位名稱之後，月表需要重新產生或重新匯出，才會換成新的名稱。"),
    ),
}


# PDF 快速指引的唯一內容母本；產生器只負責排版，不另存一份操作文案。
QUICKSTART_PAGES: tuple[dict[str, object], ...] = (
    {
        "title": "首次設定",
        "subtitle": "依序完成名單、模板與第一個月的起始番號。",
        "cards": (
            {
                "title": "1  人員設定",
                "purpose": "用途：建立每月配對時可選的人員名單。",
                "steps": (
                    "到「人員設定」新增或修改人員，確認姓名、女警標記與在職狀態。",
                    "拖拉列首把手或修改序號調整順序，完成後按「儲存排序」。",
                ),
                "tip": "提示：離開現職的人員請改為「離職」；舊月表仍會保留當時的姓名。",
            },
            {
                "title": "2  輪番模板",
                "purpose": "用途：儲存群組、番號、輪休與固定番等排班規則。",
                "steps": (
                    "到「輪番設定」選擇或新增模板，再建立各群組。",
                    "輸入番號範圍，逐格確認輪休與自訂代碼，最後執行「檢查規則」。",
                ),
                "tip": "提示：修改群組模式或番號範圍後，原有輪休與自訂代碼會清空，請重新確認。",
            },
            {
                "title": "3  自訂起始",
                "purpose": "用途：第一次產生月表，或更換模板、重新安排 1 日番號。",
                "steps": (
                    "回到「產生月表」選擇年月，按「自訂起始」。",
                    "在配對視窗選擇模板，替每個需要排人的欄位指定人員。",
                    "配對完成後按「確定」，檢查月表預覽再執行匯出。",
                ),
                "tip": "提示：人員不固定隸屬模板或群組，每次自訂起始都可依當月需求重新配對。",
            },
        ),
    },
    {
        "title": "日常操作與資料安全",
        "subtitle": "每月接續、輸出與備份都從既有月表快照進行。",
        "cards": (
            {
                "title": "1  接續上月",
                "purpose": "用途：規則與名單不變時，沿用上月狀態產生新月份。",
                "steps": (
                    "在「產生月表」選擇新月份，先確認上月月表已存在。",
                    "按「接續上月」，確認後檢查新月的預覽內容。",
                ),
                "tip": "提示：找不到上月月表時，請改用「自訂起始」；程式不會自行替你選擇。",
            },
            {
                "title": "2  匯出與重印",
                "purpose": "用途：同時建立 A3 橫式 Excel 與 PDF，或重建舊月份檔案。",
                "steps": (
                    "選擇已產生的月份並核對預覽，按「匯出」。",
                    "選擇桌面或本次使用的資料夾；遇到同名檔案時確認是否覆蓋。",
                ),
                "tip": "提示：重新匯出會讀取該月儲存的快照，不受後續改名或修改模板影響。",
            },
            {
                "title": "3  覆蓋與刪除月表",
                "purpose": "用途：修正產生錯誤的月份，或移除不再需要的月表。",
                "steps": (
                    "要重做時，選回月份並再次使用「接續上月」或「自訂起始」。",
                    "要移除時按「刪除月表」，並仔細確認年月與提示內容。",
                ),
                "tip": "提示：覆蓋與刪除都無法復原；重要資料請先用「立即備份」保留一份。",
            },
            {
                "title": "4  備份與常見問題",
                "purpose": "用途：保護人員、模板與歷次月表，並快速找到完整操作說明。",
                "steps": (
                    "每天第一次開啟程式會自動備份；也可到「功能維護」執行立即備份。",
                    "移機前先關閉程式，再一起複製執行檔、dbfile.db 與 backups 資料夾。",
                ),
                "tip": "提示：操作有疑問時，點各分頁右上角的「？」閱讀該頁完整說明。",
            },
        ),
    },
)


# ── HTML 渲染 ────────────────────────────────────────────────
# ⚠️ QTextBrowser 只吃很少的 CSS：**不支援 border-radius、flex，`<div>` 的邊框與
# 外距也常被忽略**，`margin-bottom` 更是幾乎不生效。所以版面一律用「表格格子＋
# bgcolor」排，段落間距用小字級空段落撐開，字級每一處明寫（不寫就會套 Qt 的
# 標題放大倍率，`<h1>`／`<h2>` 會大到不成比例）。這套寫法沿用 PoliceDocSys 的
# 說明視窗，改版前先確認實際畫面，不要換回一般網頁的寫法。
_BODY_PT = "13pt"
_GAP = '<p style="margin:0; font-size:5pt; line-height:5pt;">&#160;</p>'

# 內文寫到「按鈕名稱」時畫成行內按鈕（比照 PoliceDocSys 的說明視窗）。
# ⚠️ 公文系統是把每顆鈕預烤成 SVG 再嵌圖，本專案改用行內色塊：不必多帶圖檔進 exe，
#    也不必每次改按鈕文字就重新產圖。名稱是這張表的唯一來源，按鈕改名要一起改。
_BUTTON_ROLES: dict[str, str] = {
    "接續上月": "normal", "自訂起始": "primary", "匯出": "normal", "刪除月表": "danger",
    "檢查規則": "normal", "儲存排序": "primary", "儲存": "primary", "恢復預設": "normal",
    "新增": "primary", "修改": "normal", "確定": "primary", "立即備份": "normal",
    "壓縮資料庫": "primary",
}
_BUTTON_COLORS = {
    "primary": HELP_BTN_PRIMARY_COLOR,
    "normal": HELP_BTN_NORMAL_COLOR,
    "danger": HELP_BTN_DANGER_COLOR,
}


def _with_buttons(escaped: str) -> str:
    """把內文裡以「」框起來的按鈕名稱換成行內按鈕；其他「」原樣保留。"""
    for name, role in _BUTTON_ROLES.items():
        chip = (f'<span style="background-color:{_BUTTON_COLORS[role]}; color:{TEXT_COLOR}; '
                f'font-weight:600;">&#160;{name}&#160;</span>')
        escaped = escaped.replace(f"「{name}」", chip)
    return escaped


def _text(raw: str) -> str:
    return _with_buttons(escape(raw))


def _section_title(text: str) -> str:
    """藍色短豎條＋標題，下方一條細分隔線。"""
    return (
        '<p style="margin:0; font-size:6pt; line-height:6pt;">&#160;</p>'
        '<table cellspacing="0" cellpadding="0"><tr>'
        f'<td bgcolor="{HELP_ACCENT_COLOR}" width="4" style="font-size:{_BODY_PT}; '
        'line-height:140%;">&#160;</td>'
        f'<td width="9" style="font-size:{_BODY_PT};">&#160;</td>'
        f'<td style="font-size:{_BODY_PT};"><b><font color="{TEXT_COLOR}">{text}</font></b></td>'
        '</tr></table>'
        '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td bgcolor="{HELP_RULE_COLOR}" style="font-size:1pt; line-height:1pt;">&#160;</td>'
        '</tr></table>'
        + _GAP
    )


def _callout(text: str, background: str, text_color: str, mark: str) -> str:
    """單格色塊（巢狀表格在 QTextBrowser 會多塞留白，所以只用一格）。"""
    return (
        '<table width="100%" cellspacing="0" cellpadding="10"><tr>'
        f'<td bgcolor="{background}" style="font-size:{_BODY_PT}; color:{text_color}; '
        f'line-height:142%;"><b>{mark}</b>&nbsp; {text}</td>'
        '</tr></table>' + _GAP
    )


def render_help_html(page_index: int) -> str:
    """把一頁結構化說明轉成只使用公版色彩 token 的 HTML。"""
    blocks = []
    for kind, value in HELP_PAGES[page_index]:
        if kind == "title":
            blocks.append(_section_title(_text(value)))
        elif kind == "paragraph":
            blocks.append(
                f'<p style="font-size:{_BODY_PT}; color:{TEXT_COLOR}; line-height:142%; '
                f'margin:0 2px 6px;">{_text(value)}</p>')
        elif kind == "steps":
            # 兩欄表格＝懸掛縮排：序號用實心方塊，續行對齊文字欄（`<ol>` 的縮排
            # 與行距在 QTextBrowser 下會散開）。
            rows = ""
            for number, item in enumerate(value, start=1):
                badge = (
                    '<table cellspacing="0" cellpadding="0"><tr>'
                    f'<td bgcolor="{HELP_ACCENT_COLOR}" width="20" height="20" align="center" '
                    'valign="middle" style="font-size:11pt; color:#ffffff; font-weight:600; '
                    f'line-height:100%;">{number}</td></tr></table>')
                rows += (f'<tr><td width="27" valign="top">{badge}</td>'
                         f'<td valign="top" style="font-size:{_BODY_PT}; color:{TEXT_COLOR}; '
                         f'line-height:142%;">{_text(item)}</td></tr>')
            blocks.append(f'<table width="100%" cellspacing="0" cellpadding="4">{rows}</table>' + _GAP)
        elif kind == "columns":
            # ⚠️ 一項一列往下排，不做左右兩欄：兩欄在視窗變窄時字會被擠成一行兩三個字，
            #    而且讀的人得左右來回跳（維護者裁示 2026-09-18）。
            rows = "".join(
                f'<tr><td valign="top" style="font-size:{_BODY_PT}; color:{TEXT_COLOR}; '
                f'font-weight:600; white-space:nowrap;">{_text(title)}　</td>'
                f'<td valign="top" style="font-size:{_BODY_PT}; color:{TEXT_COLOR}; '
                f'line-height:142%;">{_text(body)}</td></tr>'
                for title, body in value
            )
            blocks.append(
                f'<table width="100%" cellspacing="0" cellpadding="5">{rows}</table>' + _GAP)
        elif kind == "note":
            # ⚠️ 提示只有這一種規格（淡黃底＋ⓘ）。不要再分「資訊」「警告」兩種顏色：
            #    同一份說明裡顏色換來換去，讀的人分不出哪個比較重要（維護者裁示 2026-09-18）。
            blocks.append(_callout(_text(value), HELP_WARNING_BACKGROUND_COLOR,
                                   HELP_WARNING_TEXT_COLOR, "ⓘ"))
        elif kind == "muted":
            blocks.append(
                f'<p style="font-size:12pt; color:{HELP_MUTED_TEXT_COLOR}; line-height:145%; '
                f'margin:2px 2px 8px;">{_text(value)}</p>')
        else:
            raise ValueError(f"不支援的說明區塊：{kind}")
    return f'<div style="font-size:{_BODY_PT}; color:{TEXT_COLOR};">{"".join(blocks)}</div>'


HELP_HTML: dict[int, str] = {index: render_help_html(index) for index in HELP_TITLES}
