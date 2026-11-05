#!/usr/bin/env python3
"""校验导出产物：book.json 结构、脚注闭合、图片路径、Markdown 一致性。

用法: python check_output.py output/        # 目录内需有 book.json
     python check_output.py output/ --quiet  # 只报问题
退出码 1 表示存在错误。
"""

import argparse
import json
import re
import sys
from pathlib import Path

BLOCK_TYPES = {"para", "heading", "quote", "image", "list", "table", "hr"}
IMG_MD = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
FN_REF = re.compile(r"\[\^([^\]]+)\]")
FN_DEF = re.compile(r"^\[\^([^\]]+)\]:", re.M)

errors, warns = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warns.append(msg)


def walk_blocks(node):
    """产出该节点的 block（篇下各章由调用方单独遍历，避免重复统计）。"""
    for b in node.get("blocks", []):
        yield b
    for sec in node.get("sections", []):
        for b in sec.get("blocks", []):
            yield b


def check_json(path: Path, quiet: bool):
    doc = json.loads(path.read_text(encoding="utf-8"))
    units = doc.get("units") or []
    if not units:
        err("book.json: units 为空")

    stats = {"units": len(units), "chapters": 0, "sections": 0, "blocks": 0,
             "images": 0, "notes": len(doc.get("notes") or {}), "chars": 0}
    refs, defined_in_chapter = set(), set()

    for u in units:
        if not u.get("title"):
            err("book.json: 存在无 title 的 unit")
        if u.get("kind") == "part":
            stats["chapters"] += len(u.get("chapters") or [])
            if not u.get("chapters"):
                warn(f"book.json: 篇「{u['title']}」下没有章节")
        else:
            stats["chapters"] += 1
        for node in [u, *(u.get("chapters") or [])]:
            stats["sections"] += len(node.get("sections") or [])
            for n in node.get("notes") or []:
                defined_in_chapter.add(n.get("key"))
            for b in walk_blocks(node):
                stats["blocks"] += 1
                t = b.get("type")
                if t not in BLOCK_TYPES:
                    err(f"book.json: 未知 block 类型 {t!r}（{node.get('title')}）")
                    continue

                # 脚注引用可能出现在正文、图题、图注里
                for field in ("text", "caption", "note"):
                    for key in FN_REF.findall(b.get(field) or ""):
                        refs.add((node.get("title"), key))

                if t == "image":
                    stats["images"] += 1
                    src = b.get("src") or ""
                    if not src:
                        err(f"book.json: 图片缺少 src（{node.get('title')}）")
                    else:
                        img = path.parent / src
                        if not img.exists():
                            err(f"book.json: 图片不存在 {src}")
                        elif not (b.get("width") and b.get("height")):
                            warn(f"book.json: 图片缺少宽高，可能引起布局跳动 {src}")
                elif t == "heading":
                    if not b.get("text"):
                        err(f"book.json: 空标题（{node.get('title')}）")
                    if not isinstance(b.get("level"), int):
                        err(f"book.json: heading 缺少 level（{node.get('title')}）")
                elif not (b.get("text") or b.get("items") or b.get("rows")):
                    warn(f"book.json: 空 block {t}（{node.get('title')}）")
                stats["chars"] += len(re.sub(r"[^\u3400-\u9fff]", "", b.get("text") or ""))

    missing = sorted({k for _, k in refs} - set(doc.get("notes") or {}) - defined_in_chapter)
    if missing:
        err(f"book.json: {len(missing)} 个脚注引用没有定义：{missing[:6]}")

    unused = sorted(set(doc.get("notes") or {}) - {k for _, k in refs})
    if unused:
        warn(f"book.json: {len(unused)} 条脚注定义了但正文未引用（可能重复计数）")

    if not quiet:
        print("book.json:", " ".join(f"{k}={v}" for k, v in stats.items()))
    return stats


def check_markdown(root: Path, quiet: bool):
    ch_dir = root / "chapters"
    index = root / "index.md"
    files = sorted(ch_dir.glob("*.md")) if ch_dir.exists() else []
    if not files:
        err("未找到 chapters/*.md")
        return {}

    total = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        total += len(text)
        if not text.startswith("# "):
            warn(f"{f.name}: 首个标题不是 '# 章名'")
        for src in IMG_MD.findall(text):
            if not (f.parent / src).resolve().exists():
                err(f"{f.name}: 图片缺失 {src}")
        refs = set(FN_REF.findall(text))
        defs = set(FN_DEF.findall(text))
        lost = refs - defs
        if lost:
            err(f"{f.name}: {len(lost)} 个脚注引用无定义 {sorted(lost)[:4]}")
        orphan = defs - refs
        if orphan:
            warn(f"{f.name}: {len(orphan)} 条脚注定义未被引用")

    if index.exists():
        for link in re.findall(r"\]\(([^)]+\.md)\)", index.read_text(encoding="utf-8")):
            if not (root / link).resolve().exists():
                err(f"index.md: 链接失效 {link}")
    else:
        warn("缺少 index.md（magazine 的 Markdown 目录模式无法使用）")

    if not quiet:
        print(f"markdown: files={len(files)} chars={total}")
    return {"md_files": len(files), "md_chars": total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default="output", help="导出目录")
    ap.add_argument("--quiet", action="store_true", help="只输出问题")
    args = ap.parse_args()

    root = Path(args.dir)
    doc = root / "book.json"
    if not doc.exists():
        raise SystemExit(f"找不到 {doc}")

    check_json(doc, args.quiet)
    check_markdown(root, args.quiet)

    for w in warns:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print(f"\n{'FAILED' if errors else 'OK'}  错误 {len(errors)} · 警告 {len(warns)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
