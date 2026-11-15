"""检查 `self.<name>` 有没有定义过。

为什么单独写：ruff 只查模块级名字，查不到类方法里的 `self._foo`；pyright 对无类型注解
的代码误报太多。这个检查只看一件事——类里用到的每个 `self.xxx`，是否在本类（或同模块
的基类）里被定义或赋值过。零误报，正好覆盖"只有调用没有定义"这一类 bug。
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def defined_names(node, bases):
    names = set()
    for item in ast.walk(node):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(item.name)
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                        and target.value.id == "self":
                    names.add(target.attr)
                elif isinstance(target, ast.Name):
                    names.add(target.id)      # 类属性
        elif isinstance(item, ast.AnnAssign):
            target = item.target
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                    and target.value.id == "self":
                names.add(target.attr)
            elif isinstance(target, ast.Name):
                names.add(target.id)          # 类属性 / dataclass 字段
        elif isinstance(item, ast.AugAssign):
            target = item.target
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                    and target.value.id == "self":
                names.add(target.attr)
    for base in bases:
        names |= base
    return names


def base_names(klass):
    """同模块里能解析到的基类名（浅一层就够用）。"""
    out = set()
    for base in klass.bases:
        if isinstance(base, ast.Name):
            out.add(base.id)
    # 交给调用方替换成真正的名字集合
    return out


def check_file(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}

    # 先算每个类的自有名字，处理同模块继承
    own = {name: defined_names(node, set()) for name, node in classes.items()}

    def collect(name, seen=None):
        seen = seen or set()
        if name in seen or name not in classes:
            return set()
        seen.add(name)
        names = set(own[name])
        for base in classes[name].bases:
            if isinstance(base, ast.Name):
                names |= collect(base.id, seen)
        return names

    problems = []
    for name, node in classes.items():
        available = collect(name)
        for item in ast.walk(node):
            if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) \
                    and item.value.id == "self":
                attr = item.attr
                if attr.startswith("__"):
                    continue
                if attr in available:
                    continue
                if isinstance(item.ctx, ast.Store):
                    continue                       # 赋值处会进 available
                problems.append((name, attr, item.lineno))
    return problems


def main():
    bad = 0
    for path in sorted(ROOT.joinpath("maplebot").glob("*.py")):
        for cls, attr, line in check_file(path):
            print(f"{path.name}:{line}: {cls}.self.{attr} 没有定义")
            bad += 1
    if bad:
        print(f"\n未定义的 self 属性：{bad} 处")
        return 1
    print("check_undefined.py: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
