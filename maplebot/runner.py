"""统一入口（`run.py` 的实现）。

负责四件事，脚本本身不用再管：

1. **找脚本**：按名字在 `haikuScripts/`、`marcoRecorder/`、`auto-maple/` 里查（支持模糊提示）；
2. **找窗口**：自动识别 `MapleStory` / `Haiku v236 (x64)` / `Haiku v224`，命中就写
   `config.window_override`，覆盖脚本里写死的窗口标题；
3. **起会话**：装好 stop key（默认 `l`）与按键记账，然后 `runpy` 执行目标脚本；
4. **收尾**：无论正常结束、stop key、Ctrl+C 还是异常，都松开所有按下的键。

用法见 `run.py --help`；实现上刻意保持「不改变脚本内部行为」——脚本仍是
`while True` + `lib.xxx()` 的老写法。
"""

import argparse
import ast
import difflib
import importlib.util
import os
import pathlib
import runpy
import sys
import threading
import time

from . import config, stop

#: 仓库根目录
ROOT = pathlib.Path(__file__).resolve().parent.parent

#: `--script NAME` 的搜索顺序
SEARCH_DIRS = ("haikuScripts", "marcoRecorder", "auto-maple")

#: 自动探测窗口标题的候选（前者为通用服，后两者是仓库里出现过的私服标题）
CANDIDATE_WINDOW_TITLES = ("MapleStory", "Haiku v236 (x64)", "Haiku v224")

#: 这些文件名视为「库」，在 --list 里单独归类
LIBRARY_STEMS = {
    "capture",
    "config",
    "utils",
    "commandBuilderLib",
    "returnToPoint",
    "detection",
    "botCheckSolver",
    "windowFocusLib",
    "common_used_funcs",
    "commands",
    "commands_",
}

#: 这些目录下的文件视为「库」，不当作可运行脚本
LIBRARY_DIRS = {"src", "catms", "khali", "input"}

#: 已知坏文件（语法错误是历史遗留，不参与 --check 的失败判定）
KNOWN_BROKEN = {"auto-maple/src/rune.py"}

KIND_ORDER = ("生成器", "路线", "工具", "调试", "库")

#: 脚本里出现这些字样就认为它会用到截屏（需要先找窗口）
CAPTURE_HINTS = ("Return(", "Capture(", "returnToPoint", "from capture", "import capture", "catms")


# ---------------------------------------------------------------- 文件发现
def iter_source_files():
    """仓库里所有 .py（排除 venv）。"""
    for path in sorted(ROOT.rglob("*.py")):
        if "venv" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def iter_scripts(base_dir=None):
    """可执行脚本（排除库文件与 catms/khali/input/src 里的实现）。"""
    bases = [pathlib.Path(base_dir).resolve()] if base_dir else [ROOT / d for d in SEARCH_DIRS]
    for base in bases:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if any(part in LIBRARY_DIRS for part in path.relative_to(base).parts[:-1]):
                continue
            if path.stem in LIBRARY_STEMS:
                continue
            yield path


def resolve_script(name, base_dir=None):
    """把 `--script` 的名字解析成绝对路径；失败抛 SystemExit 并给近似建议。"""
    candidate = pathlib.Path(name).expanduser()
    if candidate.suffix == ".py" or candidate.is_absolute():
        path = candidate if candidate.is_absolute() else (pathlib.Path.cwd() / candidate)
        if path.is_file():
            return path.resolve()
        raise SystemExit(f"[run] 文件不存在：{path}")

    bases = [pathlib.Path(base_dir).resolve()] if base_dir else [ROOT / d for d in SEARCH_DIRS]
    for base in bases:
        path = base / f"{name}.py"
        if path.is_file():
            return path.resolve()
        path = base / name / "__main__.py"
        if path.is_file():
            return path.resolve()

    available = sorted({p.stem for p in iter_scripts(base_dir)})
    close = difflib.get_close_matches(name, available, n=3)
    hint = f"；相近的还有：{', '.join(close)}" if close else ""
    raise SystemExit(f"[run] 找不到脚本 {name!r}{hint}（用 --list 查看全部）")


def _read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def uses_capture(path):
    """脚本会不会用到截屏。用不到就不必等窗口（比如 marcoRecorder 的生成器）。"""
    text = _read(path)
    return any(hint in text for hint in CAPTURE_HINTS)


def classify(path):
    """返回 (类别, 备注列表)。"""
    rel = path.relative_to(ROOT)
    text = _read(path)
    notes = []
    if "Return(" in text:
        notes.append("视觉闭环")
    if "khali" in text:
        notes.append("khali")
    if "pynput" in text:
        notes.append("自带 stop key")
    if "catms" in text:
        notes.append("OCR")

    if rel.parts[0] == "marcoRecorder":
        return "生成器", ["输出 .mcr"]
    if rel.parts[0] == "auto-maple" and "src" in rel.parts:
        return "库", ["auto-maple 内部"]
    if path.stem in LIBRARY_STEMS or any(part in LIBRARY_DIRS for part in rel.parts[:-1]):
        return "库", notes
    if rel.as_posix() == "auto-maple/main.py":
        return "调试", ["只跑 capture + displayer"]
    if path.stem.startswith("fallout4") or path.stem in {"clicker", "playground"}:
        return "调试", ["狂按键盘/草稿"]
    return "路线", notes


def list_scripts():
    rows = []
    for path in iter_scripts():
        kind, notes = classify(path)
        rows.append((kind, path.relative_to(ROOT).as_posix(), notes))
    rows.sort(key=lambda r: (KIND_ORDER.index(r[0]) if r[0] in KIND_ORDER else 99, r[1]))
    return rows


# ---------------------------------------------------------------- 静态检查
def check_sources():
    files = list(iter_source_files())
    failures = []
    for path in files:
        try:
            ast.parse(_read(path), filename=str(path))
        except SyntaxError as exc:
            failures.append((path, exc))

    known, unknown = [], []
    for path, exc in failures:
        rel = path.relative_to(ROOT).as_posix()
        (known if rel in KNOWN_BROKEN else unknown).append((rel, exc, path))

    print(f"[check] 解析 {len(files)} 个 .py，语法失败 {len(failures)}（已知 {len(known)}）")
    for rel, exc, _ in known:
        print(f"  [已知] {rel}:{exc.lineno}: {exc.msg}")
    for rel, exc, _ in unknown:
        print(f"  [错误] {rel}:{exc.lineno}: {exc.msg}")
    if unknown:
        print("[check] 失败：存在未预期的语法错误")
        return 1
    print("[check] 通过")
    return 0


def script_imports(path):
    """目标脚本的顶层 import 名（只看绝对导入）。"""
    names = []
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module.split(".")[0])
    return sorted(set(names))


def resolve_import(name, script_dir):
    """判断一个 import 名从 SCRIPT_DIR 出发能否解析到，返回 (状态, 说明)。"""
    if name in sys.stdlib_module_names:
        return "stdlib", ""
    local_file = script_dir / f"{name}.py"
    local_pkg = script_dir / name
    if local_file.is_file():
        return "本地", local_file.name
    if local_pkg.is_dir():
        return "本地", f"{name}/"
    root_file = ROOT / f"{name}.py"
    if root_file.is_file():
        return "本地", str(root_file.relative_to(ROOT))
    root_pkg = ROOT / name
    if root_pkg.is_dir():
        return "本地", f"{name}/"
    try:
        spec = importlib.util.find_spec(name)
    except Exception:
        spec = None
    if spec is not None:
        return "已安装", ""
    return "缺失", ""


# ---------------------------------------------------------------- 窗口
def find_game_window(timeout=0.0, titles=None, poll=0.5):
    """在候选标题里找可截屏的窗口，返回命中的标题或 None。"""
    from . import win32

    titles = [t for t in (titles or CANDIDATE_WINDOW_TITLES) if t]
    deadline = time.monotonic() + max(0.0, timeout)
    announced = False
    while True:
        for title in titles:
            if win32.find_ready_window(title):
                return title
        if time.monotonic() >= deadline:
            return None
        if not announced:
            print(f"[run] 等待游戏窗口：{', '.join(titles)}（最多 {timeout:g}s，Ctrl+C 取消）")
            announced = True
        time.sleep(poll)


# ---------------------------------------------------------------- 执行
def dry_run(script_path, window=None, wait=0.0, stop_key=stop.STOP_KEY, stop_enabled=True):
    script_path = pathlib.Path(script_path).resolve()
    script_dir = script_path.parent
    print("[dry-run] 解析结果")
    print(f"  脚本      : {script_path}")
    print(f"  工作目录  : {script_dir}")
    print(f"  Python    : {sys.executable}")
    if uses_capture(script_path):
        print(f"  窗口标题  : {window or '（未指定，运行时自动识别 ' + ' / '.join(CANDIDATE_WINDOW_TITLES) + '）'}")
        print(f"  等待窗口  : {wait:g}s")
    else:
        print("  窗口标题  : 该脚本不使用截屏，跳过")
    print(f"  急停键    : {stop_key!r}" + ("" if stop_enabled else "（已关闭）"))
    print("  import 检查：")
    for name in script_imports(script_path):
        state, detail = resolve_import(name, script_dir)
        mark = "ok " if state in {"stdlib", "本地", "已安装"} else "!! "
        print(f"    {mark}{name:<22}{state} {detail}")
    return 0


def run(script_path, window=None, wait=0.0, stop_key=stop.STOP_KEY, stop_enabled=True, stop_after=None):
    script_path = pathlib.Path(script_path).resolve()
    script_dir = script_path.parent

    # 1) 窗口：显式 --window 优先，否则自动识别后覆盖脚本里的硬编码标题
    if not uses_capture(script_path):
        print("[run] 该脚本不使用截屏，跳过找窗口")
    else:
        titles = [window] if window else list(CANDIDATE_WINDOW_TITLES)
        found = find_game_window(timeout=wait, titles=titles)
        if window:
            config.window_override = window
            if found:
                print(f"[run] 找到窗口：{found!r}")
            else:
                print(f"[run] 警告：当前没找到窗口 {window!r}，仍继续（Capture 会自己重试）")
        elif found:
            config.window_override = found
            print(f"[run] 自动识别到窗口：{found!r}，已覆盖脚本里写死的标题")
        else:
            print("[run] 没识别到游戏窗口，按脚本里的默认标题继续（Capture 会重试标定）")

    print(f"[run] 脚本：{script_path.relative_to(ROOT).as_posix()}  目录：{script_dir}")
    if stop_enabled:
        print(f"[run] 运行中按 {stop_key!r} 随时停止（Ctrl+C 也可以）")

    # 2) 让脚本能用老的扁平 import（import commandBuilderLib / from capture import ...）
    os.chdir(script_dir)
    sys.path.insert(0, str(script_dir))

    timer = None
    if stop_after:
        timer = threading.Timer(stop_after, stop.request_stop, args=(f"--stop-after {stop_after:g}s",))
        timer.daemon = True
        timer.start()

    started = time.perf_counter()
    try:
        with stop.session(stop_key=stop_key, enabled=stop_enabled):
            runpy.run_path(str(script_path), run_name="__main__")
    except stop.StopScript:
        print(f"\n[run] 已停止：{stop.reason() or 'stop'}")
    except KeyboardInterrupt:
        stop.request_stop("Ctrl+C")
        print("\n[run] 已停止：Ctrl+C")
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(f"\n[run] 脚本以 SystemExit({exc.code}) 退出")
    finally:
        if timer is not None:
            timer.cancel()
        elapsed = time.perf_counter() - started
        print(f"[run] 结束，用时 {elapsed:.1f}s")
    return 0


# ---------------------------------------------------------------- CLI
EPILOG = """\
示例:
  python run.py --list
  python run.py --script s2_clp
  python run.py --script khali_library_1 --window "MapleStory" --wait 60
  python run.py --script cat_wash_cube
  python run.py --script adele-truth2          # 生成 marcoRecorder/*.mcr
  python run.py --script s2_clp --dry-run      # 只看解析结果和 import 检查
  python run.py --check                        # 全仓库语法自检
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="marcoRecorderScriptBuilder 统一入口：找脚本 → 找窗口 → 起会话 → 收尾松键。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", nargs="?", help="脚本名或路径（等价于 --script）")
    parser.add_argument("-s", "--script", dest="script", help="脚本名或路径，如 s2_clp")
    parser.add_argument("-l", "--list", action="store_true", help="列出所有可运行脚本")
    parser.add_argument("--check", action="store_true", help="全仓库语法自检（不运行）")
    parser.add_argument("--dir", help="只在指定目录里找脚本")
    parser.add_argument("-w", "--window", help="窗口标题（覆盖脚本里写死的值）")
    parser.add_argument("--wait", type=float, default=0.0, metavar="SEC", help="等待游戏窗口出现的时间，默认 0")
    parser.add_argument("--stop-key", default=stop.STOP_KEY, metavar="KEY", help=f"急停键，默认 {stop.STOP_KEY!r}")
    parser.add_argument("--no-stop-key", action="store_true", help="不装急停键（只靠脚本自己的停止逻辑 / Ctrl+C）")
    parser.add_argument("--dry-run", action="store_true", help="只打印解析结果与 import 检查")
    parser.add_argument("--stop-after", type=float, default=None, metavar="SEC", help="N 秒后自动停止（自测用）")
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    args = build_parser().parse_args(argv)

    if args.check:
        return check_sources()

    if args.list:
        rows = list_scripts()
        width = max((len(r[1]) for r in rows), default=10)
        current = None
        for kind, rel, notes in rows:
            if kind != current:
                current = kind
                print(f"\n== {kind} " + "=" * max(0, 40 - len(kind)))
            note = ("  # " + "，".join(notes)) if notes else ""
            print(f"  {rel:<{width}}{note}")
        print(f"\n共 {len(rows)} 个；运行：python run.py --script <名字>")
        return 0

    name = args.script or args.name
    if not name:
        build_parser().print_help()
        return 2

    script_path = resolve_script(name, base_dir=args.dir)
    stop_enabled = not args.no_stop_key

    if args.dry_run:
        return dry_run(script_path, window=args.window, wait=args.wait, stop_key=args.stop_key, stop_enabled=stop_enabled)

    return run(
        script_path,
        window=args.window,
        wait=args.wait,
        stop_key=args.stop_key,
        stop_enabled=stop_enabled,
        stop_after=args.stop_after,
    )
