# ui_utils/__init__.py
# 統一對外介面：外部永遠只寫 `from ui_utils import xxx`
# 不論內部如何拆分，這裡都不需要改動外部呼叫端

from .ui_common import (
    msgInfo, msgWarning, msgCritical, confirmBox, loadUi,
    BTN_CONFIRM, BTN_DANGER, BTN_CANCEL,
)
from .widgets import (
    setupFilterCombo, setupDateEditToToday, setupDateEditCalendarOnly,
    installDateEditWheelGuard, installDateEditInputGuard,
    setupNullableDateEdit, NullableDateEdit,
    normalizeDateText, classifyNullableDate,
    refreshFilterCombo, runWithBusy, preserveScroll, attachComboHint,
    RowHoverFilter, RowHoverDelegate, LinkCursorFilter, TwoLineElideLabel,
)
from .table import (
    setupPreviewTable,
    autoResizeTable,
    applyNoElide,
    makeDeleteBtn,
    refreshDeleteBtns,
    setDocIdLinkCell,
    applyLinkStyle,
    LINK_COLOR,
    FIXED_COL_WIDTHS,
)

__all__ = [
    "msgInfo", "msgWarning", "msgCritical", "confirmBox", "loadUi",
    "BTN_CONFIRM", "BTN_DANGER", "BTN_CANCEL",
    "setupFilterCombo", "refreshFilterCombo", "attachComboHint",
    "setupDateEditToToday", "setupDateEditCalendarOnly",
    "installDateEditWheelGuard", "installDateEditInputGuard",
    "setupNullableDateEdit", "NullableDateEdit",
    "normalizeDateText", "classifyNullableDate",
    "runWithBusy", "preserveScroll",
    "RowHoverFilter", "RowHoverDelegate", "LinkCursorFilter", "TwoLineElideLabel",
    "setupPreviewTable", "autoResizeTable", "applyNoElide",
    "makeDeleteBtn", "refreshDeleteBtns", "setDocIdLinkCell", "applyLinkStyle",
    "LINK_COLOR", "FIXED_COL_WIDTHS",
]
