#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Delete local and remote branches with interactive console multi-select UI.

Usage:
    python delete_branches.py [--branches a,b,c] [--branches-file file]
                              [--remote origin] [--separator ","] [--dry-run]
                              [--remote-only]

If neither --branches nor --branches-file is given, an interactive
multi-select UI is launched. The UI lets the user pick a base branch
(release/main/master) and then multi-select local branches to delete.

With --remote-only, the interactive UI lists remote branches instead of
local branches, and only deletes from the remote.

A deletion log is written to delete-branches.log next to this script.
Each line records the timestamp, branch name, and the commit id at the
tip of the branch just before deletion.
"""

import argparse
import io
import os
import subprocess
import sys
import shutil

# ---------- ANSI color helpers ----------
ESC = "\x1b["
RESET = ESC + "0m"
BOLD = ESC + "1m"
FG_CYAN = ESC + "36m"
FG_GREEN = ESC + "32m"
FG_YELLOW = ESC + "33m"
FG_RED = ESC + "31m"
FG_DARKGRAY = ESC + "90m"
FG_WHITE = ESC + "97m"
BG_HIGHLIGHT = ESC + "48;5;24m"


def colorize(s, codes):
    return f"{codes}{s}{RESET}"


def write(s):
    sys.stdout.write(s)
    sys.stdout.flush()


def clear_lines(n):
    for _ in range(n):
        write("\x1b[2K\r\n")
    write("\r\x1b[" + str(n) + "A")


# ---------- Keyboard input (cross-platform) ----------
IS_WINDOWS = os.name == "nt"

# Force UTF-8 for stdin/stdout/stderr on Windows to avoid GBK decode errors
if IS_WINDOWS:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass


class Key:
    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    ENTER = "ENTER"
    ESCAPE = "ESCAPE"
    SPACE = "SPACE"
    HOME = "HOME"
    END = "END"
    PAGE_UP = "PAGE_UP"
    PAGE_DOWN = "PAGE_DOWN"
    CHAR = "CHAR"


def read_key():
    """Read a single key press. Returns (kind, char) tuple."""
    if IS_WINDOWS:
        import msvcrt
        ch = msvcrt.getch()
        if ch == b"\x03":
            raise KeyboardInterrupt
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            code = ch2
            mapping = {
                b"H": Key.UP,
                b"P": Key.DOWN,
                b"K": Key.LEFT,
                b"M": Key.RIGHT,
                b"G": Key.HOME,
                b"O": Key.END,
                b"I": Key.PAGE_UP,
                b"Q": Key.PAGE_DOWN,
            }
            kind = mapping.get(code, None)
            return (kind, None) if kind else (Key.CHAR, "")
        if ch in (b"\r", b"\n"):
            return (Key.ENTER, None)
        if ch == b"\x1b":
            return (Key.ESCAPE, None)
        if ch == b" ":
            return (Key.SPACE, None)
        try:
            return (Key.CHAR, ch.decode("utf-8", errors="ignore"))
        except Exception:
            return (Key.CHAR, "")
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                # Could be ESC alone or escape sequence
                import select
                if not select.select([fd], [], [], 0.05)[0]:
                    return (Key.ESCAPE, None)
                ch2 = os.read(fd, 1)
                if ch2 == b"[":
                    ch3 = os.read(fd, 1)
                    mapping = {
                        "A": Key.UP, "B": Key.DOWN, "C": Key.RIGHT, "D": Key.LEFT,
                        "H": Key.HOME, "F": Key.END,
                    }
                    if ch3 in mapping:
                        return (mapping[ch3], None)
                    if ch3 == "5":
                        os.read(fd, 1)  # consume ~
                        return (Key.PAGE_UP, None)
                    if ch3 == "6":
                        os.read(fd, 1)  # consume ~
                        return (Key.PAGE_DOWN, None)
                return (Key.ESCAPE, None)
            if ch in (b"\r", b"\n"):
                return (Key.ENTER, None)
            if ch == b" ":
                return (Key.SPACE, None)
            try:
                return (Key.CHAR, ch.decode("utf-8", errors="ignore"))
            except Exception:
                return (Key.CHAR, "")
        finally:
            termios.tcsetattr(fd, termios.TCSAFLUSH, old)


# ---------- Git helpers ----------
def run_git(args, check=True, capture=True):
    """Run a git command. Returns (returncode, stdout)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return result.returncode, (result.stdout or "")
    except FileNotFoundError:
        print(colorize("[错误] 未找到 git 命令。", FG_RED))
        sys.exit(1)


def local_branch_exists(name):
    rc, _ = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
    return rc == 0


def remote_branch_exists(remote, name):
    rc, _ = run_git(["ls-remote", "--exit-code", remote, f"refs/heads/{name}"])
    return rc == 0


def list_local_branches():
    rc, out = run_git(["branch", "--format=%(refname:short)"])
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def current_branch():
    rc, out = run_git(["branch", "--show-current"])
    if rc != 0:
        return ""
    return out.strip()


def list_merged_branches(base):
    rc, out = run_git(["branch", "--merged", base, "--format=%(refname:short)"])
    if rc != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def get_branch_commit(branch):
    """Return the short commit id at the tip of a local branch."""
    rc, out = run_git(["rev-parse", "--short", f"refs/heads/{branch}"])
    if rc == 0:
        return out.strip()
    return ""


def get_remote_branch_commit(remote, branch):
    """Return the short commit id at the tip of a remote branch."""
    rc, out = run_git(["ls-remote", remote, f"refs/heads/{branch}"])
    if rc != 0 or not out:
        return ""
    line = out.splitlines()[0].strip()
    parts = line.split()
    if parts:
        return parts[0][:7]
    return ""


def remote_tracking_branch_exists(remote, name):
    """Check if a remote-tracking branch exists locally (after fetch)."""
    rc, _ = run_git(["show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{name}"])
    return rc == 0


def list_remote_branches(remote):
    """List all branch names on the given remote via ls-remote."""
    rc, out = run_git(["ls-remote", "--heads", remote])
    if rc != 0:
        return []
    branches = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            branches.append(parts[1][len("refs/heads/"):])
    return branches


def get_remote_base_candidates(remote):
    """Return list of release/main/master branches that exist on the remote."""
    result = []
    for name in ("release", "main", "master"):
        if remote_tracking_branch_exists(remote, name):
            result.append(name)
    return result


def list_merged_remote_branches(remote, base_ref):
    """Return set of remote branch names merged into base_ref."""
    rc, out = run_git(["branch", "-r", "--merged", base_ref, "--format=%(refname:short)"])
    if rc != 0:
        return set()
    prefix = f"{remote}/"
    merged = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            merged.add(line[len(prefix):])
    return merged


def get_branch_last_commit(ref):
    """Return (date, author, short_hash) for the last commit of a ref."""
    rc, out = run_git(["show", "-s", "--format=%ad\t%an\t%h", "--date=short", ref])
    if rc != 0 or not out:
        return "", "", ""
    parts = out.strip().split("\t")
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def commit_and_push_log(remote):
    """Commit and push the deletion log to the remote."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_basename = os.path.basename(LOG_FILE)

    print(colorize("正在提交并推送日志...", FG_CYAN))

    rc, _ = run_git(["-C", script_dir, "add", "--", log_basename], check=False)
    if rc != 0:
        print(colorize("[警告] 添加日志文件失败，跳过提交", FG_YELLOW))
        return

    rc, _ = run_git(["-C", script_dir, "diff", "--cached", "--quiet"])
    if rc == 0:
        print(colorize("日志无变化，跳过提交", FG_DARKGRAY))
        return

    rc, _ = run_git(["-C", script_dir, "commit", "-m", "chore: 更新分支删除日志"], check=False)
    if rc != 0:
        print(colorize("[警告] 提交日志失败", FG_YELLOW))
        return

    rc, _ = run_git(["-C", script_dir, "push", remote], check=False)
    if rc == 0:
        print(colorize("日志已提交并推送", FG_GREEN))
    else:
        print(colorize("[警告] 推送日志失败", FG_YELLOW))


# ---------- Logging ----------
def _sanitize_filename_part(s):
    """Replace characters illegal in filenames (Windows + Linux) with '-'."""
    import re
    return re.sub(r'[\\/:*?"<>|]', "-", s).strip(". ")


def _get_log_file():
    import platform
    username = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    hostname = platform.node() or "unknown"
    name = f"delete-branches-{_sanitize_filename_part(username)}-{_sanitize_filename_part(hostname)}.log"
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


LOG_FILE = _get_log_file()


def log_deletion(branch, kind, commit_id, remote_name):
    """Append a deletion record to the log file."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cwd = os.getcwd()
    if kind == "local":
        line = f"[{timestamp}] [{cwd}] 删除本地分支: {branch}  commit: {commit_id}\n"
    else:
        line = f"[{timestamp}] [{cwd}] 删除远程分支: {remote_name}/{branch}  commit: {commit_id}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(colorize(f"[警告] 写入日志失败: {e}", FG_YELLOW))


# ---------- UI: base branch single-select ----------
def select_base_branch(candidates):
    """Single-select UI for picking a base branch from candidates."""
    cursor = 0

    def render():
        lines = []
        lines.append(colorize("选择基准分支（用于检测合并状态）", BOLD + FG_CYAN)
                     + " " + colorize("[Enter]确认 [Esc]取消", FG_DARKGRAY))
        for i, name in enumerate(candidates):
            if i == cursor:
                lines.append(colorize(f"(*) {name}", BG_HIGHLIGHT + FG_WHITE + BOLD))
            else:
                lines.append(colorize(f"( ) {name}", FG_DARKGRAY))
        clear_lines(len(lines) + 1)
        for ln in lines:
            write(ln + "\n")
        # Reserve trailing line for cursor visibility
        write("\x1b[?25l")  # hide cursor

    try:
        while True:
            render()
            kind, ch = read_key()
            if kind == Key.UP and cursor > 0:
                cursor -= 1
            elif kind == Key.DOWN and cursor < len(candidates) - 1:
                cursor += 1
            elif kind == Key.ENTER:
                return candidates[cursor]
            elif kind == Key.ESCAPE:
                return ""
    finally:
        write("\x1b[?25h")  # show cursor
        write(RESET)


# ---------- UI: multi-select branches ----------
def select_branches(branches, merged_status, commit_infos=None):
    """Multi-select UI for branches. Returns list of selected branch names.

    commit_infos: optional list of (date, author, commit_id) tuples, one per
    branch. When provided, each is shown as a sub-line beneath the branch name.
    """
    n = len(branches)
    checked = [False] * n
    cursor = 0
    page_offset = 0
    page_size = max(shutil.get_terminal_size().lines - 6, 5)

    def render():
        visible_end = min(page_offset + page_size, n)
        total_lines = page_size + 2  # header + footer + branch lines

        lines = []
        header = (colorize("选择要删除的分支", BOLD + FG_CYAN)
                  + " " + colorize("[空格]切换 [A]全选 [Enter]确认 [Esc]取消", FG_DARKGRAY))
        lines.append(header)

        for i in range(page_offset, visible_end):
            name = branches[i]
            is_checked = checked[i]
            is_merged = merged_status[i]
            is_cursor = (i == cursor)

            check_mark = colorize("[x]", FG_GREEN) if is_checked else colorize("[ ]", FG_DARKGRAY)
            merge_tag = "" if is_merged else " " + colorize("[未合并]", FG_YELLOW)

            info_str = ""
            if commit_infos:
                date, author, _ = commit_infos[i]
                if date or author:
                    info_str = colorize(f"  ({author} {date})", FG_DARKGRAY)

            if is_cursor:
                line = f"{colorize(' ', BG_HIGHLIGHT + FG_WHITE + BOLD)} {check_mark} {name}{merge_tag}{RESET}{info_str}"
            else:
                line = f" {check_mark} {name}{merge_tag}{info_str}"
            lines.append(line)

        for _ in range(visible_end, page_offset + page_size):
            lines.append("")

        selected_count = sum(checked)
        footer = colorize(
            f"── 已选: {selected_count}/{n} ── ↑↓ 导航  Enter 确认  Esc 取消 ──",
            FG_DARKGRAY
        )
        lines.append(footer)

        clear_lines(total_lines + 1)
        for ln in lines:
            write(ln + "\n")
        write("\x1b[?25l")

    try:
        while True:
            render()
            kind, ch = read_key()

            if kind == Key.UP:
                if cursor > 0:
                    cursor -= 1
                    if cursor < page_offset:
                        page_offset = cursor
            elif kind == Key.DOWN:
                if cursor < n - 1:
                    cursor += 1
                    if cursor >= page_offset + page_size:
                        page_offset = cursor - page_size + 1
            elif kind == Key.SPACE:
                checked[cursor] = not checked[cursor]
            elif kind == Key.CHAR and ch and ch.lower() == "a":
                all_checked = all(checked)
                for i in range(n):
                    checked[i] = not all_checked
            elif kind == Key.ENTER:
                return [branches[i] for i in range(n) if checked[i]]
            elif kind == Key.ESCAPE:
                return []
            elif kind == Key.HOME:
                cursor = 0
                page_offset = 0
            elif kind == Key.END:
                cursor = n - 1
                page_offset = max(0, cursor - page_size + 1)
            elif kind == Key.PAGE_UP:
                cursor = max(0, cursor - page_size)
                page_offset = max(0, page_offset - page_size)
            elif kind == Key.PAGE_DOWN:
                cursor = min(n - 1, cursor + page_size)
                page_offset = max(0, min(n - page_size, page_offset + page_size))
    finally:
        write("\x1b[?25h")
        write(RESET)


# ---------- Main flow ----------
def get_base_candidates():
    """Return list of release/main/master branches that exist locally."""
    result = []
    for name in ("release", "main", "master"):
        if local_branch_exists(name):
            result.append(name)
    return result


def split_branches(branches, separator):
    out = []
    for b in branches:
        if separator and separator in b:
            for p in b.split(separator):
                p = p.strip()
                if p:
                    out.append(p)
        else:
            out.append(b)
    return out


def confirm(prompt):
    """Read y/N confirmation."""
    try:
        ans = input(prompt).strip()
    except EOFError:
        return False
    return ans.lower() in ("y", "yes")


def delete_one_branch(branch, remote, dry_run, remote_only=False):
    print(colorize(f"=== 处理分支: {branch} ===", BOLD + FG_CYAN))

    if remote_only:
        r_exists = remote_branch_exists(remote, branch)
        if not r_exists:
            print(colorize(f"[检查] 远程分支不存在： {branch}", FG_YELLOW))
            print()
            return
        print(colorize(f"[检查] 远程分支存在： {remote}/{branch}", FG_YELLOW))

        if dry_run:
            print(colorize(f"[DryRun] git push {remote} --delete {branch}", FG_CYAN))
            print()
            return

        if not confirm(f"将要删除远程分支：{remote}/{branch}\n输入 'y' 确认，其他任意键跳过（默认：否）: "):
            print(colorize(f"已跳过： {branch}", FG_DARKGRAY))
            print()
            return

        remote_commit = get_remote_branch_commit(remote, branch)
        log_deletion(branch, "remote", remote_commit, remote)
        rc, _ = run_git(["push", remote, "--delete", branch], check=False)
        if rc == 0:
            print(colorize(f"已删除远程分支 {remote}/{branch}", FG_GREEN))
        else:
            print(colorize(f"删除远程分支失败：{remote}/{branch}", FG_RED))
        print()
        return

    local_exists = local_branch_exists(branch)
    if local_exists:
        print(colorize(f"[检查] 本地分支存在： {branch}", FG_YELLOW))
    else:
        print(colorize(f"[检查] 本地分支不存在： {branch}", FG_YELLOW))

    r_exists = remote_branch_exists(remote, branch)
    if r_exists:
        print(colorize(f"[检查] 远程分支存在： {remote}/{branch}", FG_YELLOW))
    else:
        print(colorize(f"[检查] 远程分支不存在： {branch}", FG_YELLOW))

    if not local_exists and not r_exists:
        print()
        return

    if dry_run:
        if local_exists:
            print(colorize(f"[DryRun] git branch -D {branch}", FG_CYAN))
        if r_exists:
            print(colorize(f"[DryRun] git push {remote} --delete {branch}", FG_CYAN))
        print()
        return

    targets = []
    if local_exists:
        targets.append(f"本地: {branch}")
    if r_exists:
        targets.append(f"远程: {remote}/{branch}")
    confirm_msg = "将要删除：\n" + "\n".join(targets) + "\n输入 'y' 确认，其他任意键跳过（默认：否）: "
    if not confirm(confirm_msg):
        print(colorize(f"已跳过： {branch}", FG_DARKGRAY))
        print()
        return

    if local_exists:
        local_commit = get_branch_commit(branch)
        log_deletion(branch, "local", local_commit, remote)
        rc, _ = run_git(["branch", "-D", branch], check=False)
        if rc == 0:
            print(colorize(f"已删除本地分支 {branch}", FG_GREEN))
        else:
            print(colorize(f"删除本地分支失败：{branch}", FG_RED))

    if r_exists:
        remote_commit = get_remote_branch_commit(remote, branch)
        log_deletion(branch, "remote", remote_commit, remote)
        rc, _ = run_git(["push", remote, "--delete", branch], check=False)
        if rc == 0:
            print(colorize(f"已删除远程分支 {remote}/{branch}", FG_GREEN))
        else:
            print(colorize(f"删除远程分支失败：{remote}/{branch}", FG_RED))

    print()


def main():
    parser = argparse.ArgumentParser(
        description="删除本地/远程分支（默认进入交互式多选）。"
    )
    parser.add_argument(
        "--branches", nargs="*", default=None,
        help="要删除的分支名列表（可重复或用分隔符分隔）"
    )
    parser.add_argument(
        "--branches-file", default=None,
        help="包含分支名的文件（每行一个）"
    )
    parser.add_argument("--remote", default="origin", help="远程名（默认 origin）")
    parser.add_argument("--separator", default=",", help="分支名分隔符（默认 ,）")
    parser.add_argument("--dry-run", action="store_true", help="仅显示将要执行的命令")
    parser.add_argument(
        "--remote-only", action="store_true",
        help="仅列出/删除远程分支（交互式模式下列出远程分支供选择）"
    )
    args = parser.parse_args()

    if not sys.stdin.isatty():
        print(colorize("[错误] 需要交互式终端支持。", FG_RED))
        sys.exit(1)

    branches_list = []

    if not args.branches and not args.branches_file:
        # Interactive mode
        if not args.remote_only:
            print(colorize(
                "Tips: 使用 -RemoteOnly 可列出远程分支进行删除  eg. Delete-Branches -RemoteOnly",
                FG_DARKGRAY,
            ))
            print()
        print(colorize("正在 fetch 远程仓库...", FG_CYAN))
        rc, _ = run_git(["fetch", args.remote], check=False)
        if rc == 0:
            print(colorize("fetch 完成", FG_GREEN))
        else:
            print(colorize("fetch 失败，将使用本地数据继续", FG_YELLOW))
        print()

        if args.remote_only:
            candidates = get_remote_base_candidates(args.remote)
            if not candidates:
                print(colorize(
                    f"[错误] 远程 {args.remote} 未找到 release / main / master 中的任何分支，"
                    f"无法确定基准分支。",
                    FG_RED,
                ))
                sys.exit(1)

            print()
            base = select_base_branch(candidates)
            print()
            if not base:
                print(colorize("[取消] 未选择基准分支。", FG_DARKGRAY))
                sys.exit(0)
            print(f"已选择基准分支：{colorize(args.remote + '/' + base, FG_CYAN)}")

            base_ref = f"{args.remote}/{base}"
            merged_set = list_merged_remote_branches(args.remote, base_ref)

            all_remote = list_remote_branches(args.remote)
            if not all_remote:
                print(colorize("[错误] 无法获取远程分支列表。", FG_RED))
                sys.exit(1)

            current = current_branch()
            all_branches = []
            merged_status = []
            for b in all_remote:
                if b and b != base and b != current and b != "HEAD":
                    all_branches.append(b)
                    merged_status.append(b in merged_set)

            if not all_branches:
                print(colorize("[提示] 没有可删除的远程分支。", FG_YELLOW))
                sys.exit(0)

            merged_count = sum(merged_status)
            unmerged_count = len(all_branches) - merged_count
            print(f"共 {len(all_branches)} 个可删除的远程分支（"
                  f"{colorize(f'已合并: {merged_count}', FG_GREEN)}，"
                  f"{colorize(f'未合并: {unmerged_count}', FG_YELLOW)}）")
            print()

            commit_infos = [get_branch_last_commit(f"{args.remote}/{b}") for b in all_branches]
            chosen = select_branches(all_branches, merged_status, commit_infos)
            print()

            if not chosen:
                print(colorize("[取消] 未选择任何分支。", FG_DARKGRAY))
                sys.exit(0)

            branches_list = chosen
        else:
            candidates = get_base_candidates()
            if not candidates:
                print(colorize(
                    "[错误] 本地未找到 release / main / master 中的任何分支，无法确定基准分支。",
                    FG_RED,
                ))
                sys.exit(1)

            print()
            base = select_base_branch(candidates)
            print()
            if not base:
                print(colorize("[取消] 未选择基准分支。", FG_DARKGRAY))
                sys.exit(0)
            print(f"已选择基准分支：{colorize(base, FG_CYAN)}")

            # 将远程基准分支同步到本地，确保合并检测基于最新代码
            print(colorize(f"正在同步基准分支 {base} 从 {args.remote}...", FG_CYAN))
            cur = current_branch()
            if base == cur:
                # 当前分支无法通过 fetch 快进，改用 merge --ff-only
                rc, _ = run_git(["merge", "--ff-only", f"{args.remote}/{base}"], check=False)
            else:
                rc, _ = run_git(["fetch", args.remote, f"{base}:{base}"], check=False)
            if rc == 0:
                print(colorize(f"基准分支 {base} 已同步", FG_GREEN))
            else:
                print(colorize(f"基准分支 {base} 同步失败，将使用本地版本继续", FG_YELLOW))
            print()

            merged_set = list_merged_branches(base)

            all_local = list_local_branches()
            if not all_local:
                print(colorize("[错误] 无法获取本地分支列表。", FG_RED))
                sys.exit(1)

            current = current_branch()
            all_branches = []
            merged_status = []
            for b in all_local:
                if b and b != current:
                    all_branches.append(b)
                    merged_status.append(b in merged_set)

            if not all_branches:
                print(colorize(
                    f"[提示] 没有可删除的本地分支（仅剩当前分支 '{current}'）。",
                    FG_YELLOW,
                ))
                sys.exit(0)

            merged_count = sum(merged_status)
            unmerged_count = len(all_branches) - merged_count
            print(f"共 {len(all_branches)} 个可删除分支（"
                  f"{colorize(f'已合并: {merged_count}', FG_GREEN)}，"
                  f"{colorize(f'未合并: {unmerged_count}', FG_YELLOW)}）")
            print()

            commit_infos = [get_branch_last_commit(b) for b in all_branches]
            chosen = select_branches(all_branches, merged_status, commit_infos)
            print()

            if not chosen:
                print(colorize("[取消] 未选择任何分支。", FG_DARKGRAY))
                sys.exit(0)

            branches_list = chosen
    else:
        if args.branches_file:
            if not os.path.isfile(args.branches_file):
                print(colorize(f"[错误] 未找到文件: {args.branches_file}", FG_RED))
                sys.exit(1)
            with open(args.branches_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        branches_list.append(line)

        if args.branches:
            branches_list.extend(split_branches(args.branches, args.separator))

        if not branches_list:
            print(colorize("[错误] 未提供任何分支。请使用 --branches 或 --branches-file。", FG_RED))
            sys.exit(1)

    for branch in branches_list:
        delete_one_branch(branch, args.remote, args.dry_run, remote_only=args.remote_only)

    if not args.dry_run and branches_list:
        print(colorize(f"被删除的分支记录已保存至：{LOG_FILE}", FG_DARKGRAY))
        print(colorize("可通过日志中的 commit ID 恢复被删除的分支，例如：", FG_DARKGRAY))
        print(colorize("  git branch <分支名> <commit-id>", FG_DARKGRAY))
        print()

        commit_and_push_log(args.remote)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # 确保终端状态恢复
        write("\x1b[?25h")  # show cursor
        write(RESET)
        print(f"\n{colorize('[退出] 用户中断操作。', FG_YELLOW)}")
        sys.exit(130)
