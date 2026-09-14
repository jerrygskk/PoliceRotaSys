"""個資防呆：push 前確認 git 追蹤內容未命中本機已知 denylist。

自 PoliceDocSys 移植，移除公文專屬檢查（gen_shell_db／seed_screenshot_data），
保留掃描核心。⚠️ 本專案是 public repo，這支測試比在私有庫更關鍵。

設計重點：
  - 目前狀態的掃描清單只來自 index 與 HEAD tree，不含 untracked／ignored。
    tracked path 分別讀安全工作樹、index、HEAD；工作樹 path 的 target 與各層
    parent 必須都留在 repo 內，不跟隨外部 symlink／junction，但仍掃
    index／HEAD blob。
  - 逐一掃描 ``@{upstream}..HEAD`` 每個尚未推送 commit 的完整 tree；沒有
    upstream 時明確失敗，避免掃全歷史或靜默假綠。
  - 比對清單 tests/pii_denylist.local.txt 為本機檔（已 gitignore，不入庫，
    才不會把真名又帶進 repo）；清單不存在或有效項目為空時明確 skip。
  - 命中即 fail，並列出檔名與名字，提醒「替換後才能 push」。

通過只代表未命中本機已知 denylist，不得宣稱候選姓名已證明不對應真人。

執行：專案根目錄下 `python -m unittest tests.test_no_pii`
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DENYLIST = os.path.join(_ROOT, "tests", "pii_denylist.local.txt")
# 其餘追蹤檔一律嘗試 UTF-8 解碼，只有已知二進位格式明確排除。
_BINARY_EXT = (".png", ".ico", ".db", ".xlsx", ".pdf")


def _git_at(root, *args):
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        capture_output=True,
    )
    if result.returncode:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git {' '.join(args)} 失敗：{stderr}")
    return result.stdout


def _is_within_repo(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_worktree_blob(root, relative):
    """只讀取解析後每一層都留在 repo 內的工作樹 path。"""
    repo = Path(root).resolve(strict=True)
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None

    path = repo.joinpath(*relative_path.parts)
    if not os.path.lexists(path):
        return None

    current = repo
    for part in relative_path.parts:
        current /= part
        try:
            # resolve 同時展開 symlink 與 Windows junction/reparse point。
            resolved = current.resolve(strict=True)
        except (FileNotFoundError, RuntimeError):
            return None
        if not _is_within_repo(resolved, repo):
            return None

    # git 對 final symlink 追蹤的是連結文字，不讀取其 target bytes。
    if path.is_symlink():
        return os.readlink(path).encode("utf-8")
    return path.read_bytes()


def _git_blob(root, object_spec):
    result = subprocess.run(
        ["git", "-C", os.fspath(root), "show", object_spec],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _git_paths(root, *args):
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        capture_output=True,
    )
    if result.returncode:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git {' '.join(args)} 失敗：{stderr}")
    return [raw.decode("utf-8") for raw in result.stdout.split(b"\x00") if raw]


def _is_known_binary(relative):
    return relative.lower().endswith(_BINARY_EXT)


def _has_head(root):
    result = subprocess.run(
        ["git", "-C", os.fspath(root), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git rev-parse HEAD 失敗：{stderr}")
    return result.returncode == 0


def _text_hits(relative, blob, deny):
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return [f"{relative}：{name}" for name in deny if name in text]


def _stable_unique(items):
    return list(dict.fromkeys(items))


def _scan_tracked_text(root, deny):
    """分別掃描安全工作樹、index、HEAD 的所有可解碼追蹤檔。"""
    tracked = set(_git_paths(root, "ls-files", "-z"))
    if _has_head(root):
        tracked.update(
            _git_paths(root, "ls-tree", "-r", "--name-only", "-z", "HEAD")
        )
    hits = []
    for relative in sorted(tracked):
        if _is_known_binary(relative):
            continue
        blobs = (
            _safe_worktree_blob(root, relative),
            _git_blob(root, f":{relative}"),
            _git_blob(root, f"HEAD:{relative}"),
        )
        for blob in blobs:
            if blob is not None:
                hits.extend(_text_hits(relative, blob, deny))
    return _stable_unique(hits)


def _resolve_upstream(root):
    result = subprocess.run(
        [
            "git", "-C", os.fspath(root), "rev-parse",
            "--abbrev-ref", "--symbolic-full-name", "@{upstream}",
        ],
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(
            "目前分支找不到 upstream；請指定比較基準後再執行 PII gate"
        )
    return result.stdout.decode("utf-8").strip()


def _scan_outgoing_text(root, deny):
    """掃描 upstream..HEAD 每個 commit 的完整 tree，不回溯既有歷史。"""
    upstream = _resolve_upstream(root)
    commits = _git_at(root, "rev-list", "--reverse", f"{upstream}..HEAD")
    hits = []
    for commit in commits.decode("ascii").splitlines():
        paths = _git_paths(root, "ls-tree", "-r", "--name-only", "-z", commit)
        for relative in paths:
            if _is_known_binary(relative):
                continue
            blob = _git_blob(root, f"{commit}:{relative}")
            if blob is None:
                raise RuntimeError(f"無法讀取 commit {commit} 的 {relative}")
            hits.extend(_text_hits(relative, blob, deny))
    return _stable_unique(hits)


def _scan_repository_text(root, deny):
    return _stable_unique(
        _scan_tracked_text(root, deny) + _scan_outgoing_text(root, deny)
    )


def _load_denylist():
    if not os.path.exists(_DENYLIST):
        return []
    names = []
    with open(_DENYLIST, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                names.append(s)
    return names


class _IsolatedRepoTestCase(unittest.TestCase):
    """在暫存 git repo 上驗證掃描邊界，不碰本專案工作樹。"""

    DENIED = "禁止姓名"
    OTHER_DENIED = "另一禁名"

    def setUp(self):
        temp_root = Path(_ROOT) / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(
            prefix="pii-test-", dir=temp_root
        )
        self.repo = Path(self._temp.name)
        self._git("init")
        self._git("config", "user.email", "pii-test@example.invalid")
        self._git("config", "user.name", "PII Test")

    def tearDown(self):
        self._temp.cleanup()

    def _git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )

    def _commit_file(self, relative: str, content: str):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._git("add", relative)
        self._git("commit", "-m", "test fixture")
        return path


class TestTrackedWorktreeScanning(_IsolatedRepoTestCase):
    """tracked 工作樹／index／HEAD 三來源的掃描邊界。"""

    def _scan(self):
        return _scan_tracked_text(self.repo, [self.DENIED])

    def test_tracked_unstaged_modification_is_scanned(self):
        path = self._commit_file("tracked.txt", "乾淨內容")
        path.write_text(self.DENIED, encoding="utf-8")
        self.assertEqual(self._scan(), [f"tracked.txt：{self.DENIED}"])

    def test_staged_new_file_is_scanned(self):
        self._commit_file("baseline.txt", "乾淨內容")
        staged = self.repo / "staged.txt"
        staged.write_text(self.DENIED, encoding="utf-8")
        self._git("add", "staged.txt")
        self.assertEqual(self._scan(), [f"staged.txt：{self.DENIED}"])

    def test_staged_new_file_deleted_from_worktree_is_scanned_from_index(self):
        self._commit_file("baseline.txt", "乾淨內容")
        staged = self.repo / "staged-deleted.txt"
        staged.write_text(self.DENIED, encoding="utf-8")
        self._git("add", "staged-deleted.txt")
        staged.unlink()
        self.assertEqual(self._scan(), [f"staged-deleted.txt：{self.DENIED}"])

    def test_staged_denied_content_is_scanned_when_worktree_is_clean(self):
        path = self._commit_file("tracked.txt", "乾淨內容")
        path.write_text(self.DENIED, encoding="utf-8")
        self._git("add", "tracked.txt")
        path.write_text("工作樹已清乾淨", encoding="utf-8")
        self.assertEqual(self._scan(), [f"tracked.txt：{self.DENIED}"])

    def test_head_denied_content_is_scanned_when_index_and_worktree_are_clean(self):
        path = self._commit_file("tracked.txt", self.DENIED)
        path.write_text("index 與工作樹都乾淨", encoding="utf-8")
        self._git("add", "tracked.txt")
        self.assertEqual(self._scan(), [f"tracked.txt：{self.DENIED}"])

    def test_deleted_worktree_file_falls_back_to_head(self):
        path = self._commit_file("deleted.txt", self.DENIED)
        path.unlink()
        self.assertEqual(self._scan(), [f"deleted.txt：{self.DENIED}"])

    def test_untracked_ignored_file_is_not_scanned(self):
        self._commit_file(".gitignore", "ignored.txt\n")
        (self.repo / "ignored.txt").write_text(self.DENIED, encoding="utf-8")
        self.assertEqual(self._scan(), [])

    def test_tracked_text_with_non_whitelisted_extensions_is_scanned(self):
        self._commit_file("baseline.txt", "乾淨內容")
        for relative in ("release.spec", "run.bat", "icon.svg"):
            path = self.repo / relative
            path.write_text(self.DENIED, encoding="utf-8")
            self._git("add", relative)
        self.assertEqual(
            self._scan(),
            [
                f"icon.svg：{self.DENIED}",
                f"release.spec：{self.DENIED}",
                f"run.bat：{self.DENIED}",
            ],
        )

    def test_same_path_and_name_across_sources_is_reported_once_stably(self):
        for relative in ("b.txt", "a.txt"):
            path = self.repo / relative
            path.write_text(f"{self.OTHER_DENIED} {self.DENIED}", encoding="utf-8")
            self._git("add", relative)
        self._git("commit", "-m", "test fixture")
        self.assertEqual(
            _scan_tracked_text(self.repo, [self.OTHER_DENIED, self.DENIED]),
            [
                f"a.txt：{self.OTHER_DENIED}",
                f"a.txt：{self.DENIED}",
                f"b.txt：{self.OTHER_DENIED}",
                f"b.txt：{self.DENIED}",
            ],
        )

    def test_parent_symlink_outside_repo_is_not_followed(self):
        clean = self.repo / "clean-blob.txt"
        clean.write_text("乾淨 index 內容", encoding="utf-8")
        object_id = self._git("hash-object", "-w", "clean-blob.txt").stdout.strip()
        clean.unlink()
        self._git(
            "update-index", "--add", "--cacheinfo",
            f"100644,{object_id},linked/secret.txt",
        )
        temp_root = Path(_ROOT) / ".tmp"
        with tempfile.TemporaryDirectory(
            prefix="pii-external-", dir=temp_root
        ) as outside_dir:
            outside = Path(outside_dir)
            (outside / "secret.txt").write_text(self.DENIED, encoding="utf-8")
            try:
                os.symlink(outside, self.repo / "linked", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"目前環境不可建立目錄 symlink：{exc}")
            self.assertEqual(self._scan(), [])

    def test_external_symlink_is_not_followed_but_denied_index_blob_is_scanned(self):
        index_source = self.repo / "index-source.txt"
        index_source.write_text(self.DENIED, encoding="utf-8")
        object_id = self._git("hash-object", "-w", "index-source.txt").stdout.strip()
        index_source.unlink()
        self._git(
            "update-index", "--add", "--cacheinfo",
            f"100644,{object_id},linked/secret.txt",
        )
        temp_root = Path(_ROOT) / ".tmp"
        with tempfile.TemporaryDirectory(
            prefix="pii-external-clean-", dir=temp_root
        ) as outside_dir:
            outside = Path(outside_dir)
            (outside / "secret.txt").write_text("外部乾淨內容", encoding="utf-8")
            try:
                os.symlink(outside, self.repo / "linked", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"目前環境不可建立目錄 symlink：{exc}")
            self.assertEqual(self._scan(), [f"linked/secret.txt：{self.DENIED}"])


class TestOutgoingCommitScanning(_IsolatedRepoTestCase):
    """只掃描尚未推送的每個 commit tree。"""

    def _set_local_upstream(self):
        self._git("branch", "upstream-base")
        self._git("branch", "--set-upstream-to=upstream-base")

    def _scan(self):
        return _scan_outgoing_text(self.repo, [self.DENIED])

    def test_deleted_in_later_commit_still_hits_earlier_outgoing_commit(self):
        path = self._commit_file("baseline.txt", "乾淨內容")
        self._set_local_upstream()
        path.write_text(self.DENIED, encoding="utf-8")
        self._git("add", "baseline.txt")
        self._git("commit", "-m", "outgoing A")
        path.unlink()
        self._git("add", "baseline.txt")
        self._git("commit", "-m", "outgoing B deletes file")
        self.assertEqual(self._scan(), [f"baseline.txt：{self.DENIED}"])

    def test_history_before_upstream_is_not_scanned(self):
        path = self._commit_file("legacy.txt", self.DENIED)
        path.write_text("已於 upstream 前清除", encoding="utf-8")
        self._git("add", "legacy.txt")
        self._git("commit", "-m", "clean baseline")
        self._set_local_upstream()
        self.assertEqual(self._scan(), [])

    def test_missing_upstream_fails_and_requests_comparison_base(self):
        self._commit_file("baseline.txt", "乾淨內容")
        with self.assertRaisesRegex(
            RuntimeError, r"upstream.*指定比較基準|指定比較基準.*upstream"
        ):
            self._scan()


class TestNoPII(unittest.TestCase):
    def setUp(self):
        self.deny = _load_denylist()
        if not self.deny:
            self.skipTest(
                f"{os.path.relpath(_DENYLIST, _ROOT)} 不存在或無有效項目，"
                "跳過個資掃描"
            )

    def test_tracked_text_files_clean(self):
        """目前三來源與所有尚未推送 commit 均不得含 denylist 真名。"""
        hits = _scan_repository_text(_ROOT, self.deny)
        self.assertEqual(
            hits, [],
            "git 追蹤檔含真實人名，替換後才能 push：\n  " + "\n  ".join(hits))


if __name__ == "__main__":
    unittest.main()
