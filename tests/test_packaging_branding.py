import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "PoliceRotaSys.spec"


def _call(name: str) -> ast.Call:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    return next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == name
    )


def _keyword(call_name: str, keyword: str):
    call = _call(call_name)
    value = next(item.value for item in call.keywords if item.arg == keyword)
    return ast.literal_eval(value)


def test_spec_bundles_external_branding_assets():
    datas = _keyword("Analysis", "datas")
    assert ("res/buttons/police_badge.svg", "res/buttons") in datas
    assert ("res/buttons/banner.png", "res/buttons") in datas


def test_spec_uses_windows_executable_icon():
    assert _keyword("EXE", "icon") == ["res\\buttons\\police_badge.ico"]
