#!/usr/bin/env python3
"""探查一本 EPUB 的结构，给出写导出脚本所需的全部线索。

用法: python probe_epub.py 书.epub
"""

import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup


def load_opf(z):
    container = z.read("META-INF/container.xml").decode("utf-8")
    opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
    opf = BeautifulSoup(z.read(opf_path), "lxml-xml")
    base = str(Path(opf_path).parent)
    manifest = {it["id"]: it.get("href", "") for it in opf.find_all("item")}
    spine = [manifest[r["idref"]] for r in opf.find_all("itemref") if r.get("idref") in manifest]
    meta = {}
    for t in ("title", "creator", "publisher"):
        el = opf.find(f"dc:{t}")
        if el:
            meta[t] = el.get_text().strip()
    nav = next((f"{base}/{it['href']}" for it in opf.find_all("item")
                if "nav" in (it.get("properties") or "").split()), None)
    return base, spine, meta, nav


def dump_toc(z, base, nav_path):
    items = []

    if nav_path:
        soup = BeautifulSoup(z.read(nav_path), "lxml-xml")
        nav_dir = str(Path(nav_path).parent)

        def walk(ol, depth):
            if ol is None:
                return
            for li in ol.find_all("li", recursive=False):
                a = li.find(["a", "span"], recursive=False)
                if a is not None and a.name == "a":
                    href = a.get("href") or ""
                    f, _, anc = href.partition("#")
                    items.append((depth, a.get_text(" ").strip(), f"{nav_dir}/{f}".replace("//", "/"), anc))
                inner = li.find("ol", recursive=False)
                if inner is not None:
                    walk(inner, depth + 1)

        walk(soup.find("ol"), 1)
        src = f"EPUB3 nav: {nav_path}"
    else:
        name = next((n for n in z.namelist() if n.lower().endswith(".ncx")), None)
        if not name:
            return "（无 nav 也无 ncx，需按 spine 顺序切章）", []
        soup = BeautifulSoup(z.read(name), "lxml-xml")
        ncx_dir = str(Path(name).parent)

        def walk_ncx(node, depth):
            for np in node.find_all("navPoint", recursive=False):
                label, content = np.find("navLabel"), np.find("content")
                if label and content:
                    f, _, anc = content["src"].partition("#")
                    items.append((depth, label.get_text().strip(), f"{ncx_dir}/{f}".replace("//", "/"), anc))
                walk_ncx(np, depth + 1)

        walk_ncx(soup.find("navMap"), 1)
        src = f"EPUB2 ncx: {name}"

    lines = [f"目录源: {src}  条目 {len(items)}"]
    for depth, title, f, anc in items[:14]:
        lines.append(f"  {'  ' * (depth - 1)}d{depth} {title}  →  {f}#{anc or '-'}")
    if len(items) > 14:
        lines.append(f"  … 其余 {len(items) - 14} 条")
    depths = Counter(d for d, *_ in items)
    lines.append(f"层级分布: {dict(sorted(depths.items()))}")
    return "\n".join(lines), items


def main(path: str):
    with zipfile.ZipFile(path) as z:
        base, spine, meta, nav_path = load_opf(z)
        files = [f"{base}/{f}".replace("//", "/") for f in spine]
        images = [n for n in z.namelist() if re.search(r"\.(jpe?g|png|gif|webp)$", n, re.I)]

        print(f"EPUB: {Path(path).name}")
        print(f"META: {meta}")
        print(f"spine: {len(files)} 个文档 | 图片: {len(images)} 张\n")

        toc_text, toc = dump_toc(z, base, nav_path)
        print(toc_text, "\n")

        # ---- class 频次（决定正文/引文/图注规则）
        tag_class = Counter()
        id_target = {}
        links = []
        img_boxes = Counter()
        for rel in files:
            soup = BeautifulSoup(z.read(rel), "lxml-xml")
            for el in soup.find_all(True):
                cls = el.get("class") or []
                cls = " ".join(cls) if isinstance(cls, list) else str(cls)
                if cls:
                    tag_class[(el.name, cls)] += 1
                if el.get("id"):
                    id_target.setdefault(el["id"], el)
                if el.name == "a" and "#" in (el.get("href") or ""):
                    links.append(el["href"].partition("#")[2])
                if el.name == "img":
                    parent = el.parent
                    pcls = parent.get("class") or []
                    img_boxes[" ".join(pcls) if isinstance(pcls, list) else str(pcls)] += 1

        print("元素 + class 频次（前 22，用来挑正文/引文/脚注规则）")
        for (tag, cls), n in tag_class.most_common(22):
            print(f"  {n:5d}  <{tag} class=\"{cls}\">")
        print()

        # ---- 脚注候选：被 # 引用的 id，且目标元素/祖先带 note 语义或编号开头
        def looks_note(el):
            node, depth = el, 0
            while node is not None and depth < 3:
                cls = node.get("class") or []
                cls = " ".join(cls) if isinstance(cls, list) else str(cls)
                if re.search(r"(fn|note|脚注|尾注|注释)", cls + str(node.get("id") or ""), re.I):
                    return True
                node, depth = node.parent, depth + 1
            text = el.get_text(" ").strip()
            return bool(re.match(r"^\s*[(（\[【]?\s*\d{1,3}", text)) and len(text) < 240

        print("脚注候选（正文链接指向的元素 + 其祖先 class）")
        seen = set()
        skipped = 0
        for anchor in links:
            el = id_target.get(anchor)
            if el is None or anchor in seen:
                continue
            if not looks_note(el):
                skipped += 1
                continue
            chain = []
            node, depth = el, 0
            while node is not None and depth < 3:
                cls = node.get("class") or []
                cls = " ".join(cls) if isinstance(cls, list) else str(cls)
                chain.append(f"{node.name}{'.' + cls if cls else ''}{'#' + node['id'] if node.get('id') else ''}")
                node, depth = node.parent, depth + 1
            key = " < ".join(chain)
            if key in seen:
                continue
            seen.add(key)
            text = re.sub(r"\s+", " ", el.get_text(" ")).strip()[:46]
            print(f"  {' < '.join(chain)}   | {text}")
            if len(seen) >= 8:
                break
        if not seen:
            print("  （没有明显的脚注结构）")
        elif skipped:
            print(f"  … 另有 {skipped} 个链接指向普通位置（目录/交叉引用），已忽略")
        print()

        print("图片所在父元素 class")
        for cls, n in img_boxes.most_common(8):
            print(f"  {n:5d}  <parent class=\"{cls}\">")
        print()

        # ---- 图注/引文候选
        print("图注/引文候选（class 关键词命中）")
        for (tag, cls), n in tag_class.most_common():
            if re.search(r"(cap|tuti|tuzhu|credit|source|quote|kaiti|copy|sign|note|fn)", cls, re.I):
                print(f"  {n:5d}  <{tag} class=\"{cls}\">")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python probe_epub.py 书.epub")
    main(sys.argv[1])
