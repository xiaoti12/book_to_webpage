#!/usr/bin/env python3
"""导出脚本模板：EPUB → book.json + 分章 Markdown（给 magazine.html 用）。

复制本文件到目标项目，改 CONVENTIONS 六项即可。整份流程：
  1. 读 container.xml → .opf → spine / metadata
  2. 读 toc.ncx（或 nav.xhtml）得到 篇→章→节 层级
  3. 扫脚注定义（正文锚点指向的段落）
  4. 扫图片尺寸（渲染时占位，避免滚动后布局跳动）
  5. 按 spine 顺序遍历，遇到目录锚点就切换目标 section，逐块解析
  6. 输出 book.json / chapters/*.md / images/

用法: python extract_template.py 书.epub [-o 输出目录]
"""

import argparse
import json
import posixpath
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image

# ---------------------------------------------------------------- 唯一需要改的地方

CONVENTIONS = {
    # 脚注定义段落的 class：<p class="fncontent"> ...
    "footnote_def": "fncontent",
    # 正文里脚注引用的 href 形态：<a href="part0020.xhtml#jz_1_53">(1)</a>
    "footnote_ref": r"#(jz_\w+)$",
    # 图片容器（div/section 里包着 img + 图题）
    "image_box": r"chatu_img|^title_img$",
    # 图题 / 图注（数据来源）的 class
    "caption": r"tuti",
    "credit": r"tuzhu",
    # 引文（楷体、摘录、落款）：段落 class 命中即视为引文
    "quote": r"kaiti|copycontent|signcontent",
    # 目录页标题（渲染时改名为"卷首"，只保留题记）
    "toc_page": "目录",
}

FOOTNOTE_REF = re.compile(CONVENTIONS["footnote_ref"])
IMAGE_BOX = re.compile(CONVENTIONS["image_box"])
CAPTION = re.compile(CONVENTIONS["caption"])
CREDIT = re.compile(CONVENTIONS["credit"])
QUOTE = re.compile(CONVENTIONS["quote"])


# ---------------------------------------------------------------- 工具

def classes_of(el) -> str:
    # 注意：lxml-xml 解析时 class 是字符串；html 解析时是 list
    cls = el.get("class") or []
    return " ".join(cls) if isinstance(cls, list) else str(cls)


def norm(text: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", text).strip()


def same_title(a: str, b: str) -> bool:
    """忽略空白与标点后比较（ncx 常用半角空格，正文用全角）。"""
    key = lambda s: re.sub(r"[\W_]+", "", s or "")
    return key(a) == key(b)


# ---------------------------------------------------------------- EPUB 读取

def load_package(zf):
    container = zf.read("META-INF/container.xml").decode("utf-8")
    opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
    opf = BeautifulSoup(zf.read(opf_path), "lxml-xml")
    base = str(Path(opf_path).parent)

    manifest = {it["id"]: it["href"] for it in opf.find_all("item")}
    spine = [manifest[r["idref"]] for r in opf.find_all("itemref")]
    meta = {}
    for tag in ("title", "creator", "publisher", "date"):
        el = opf.find(f"dc:{tag}")
        if el:
            meta[tag] = el.get_text().strip()
    return base, spine, meta


def parse_toc(zf, base):
    """toc.ncx → [{depth, title, file, anchor}]。

    EPUB3 用 nav.xhtml 的 <nav epub:type="toc"><ol><li><a>，递归 ol 得到同样的 depth。
    """
    ncx = next(n for n in zf.namelist() if n.endswith(".ncx"))
    soup = BeautifulSoup(zf.read(ncx), "lxml-xml")
    ncx_dir = str(Path(ncx).parent)
    items = []

    def walk(node, depth):
        for nav in node.find_all("navPoint", recursive=False):
            file_part, _, anchor = nav.find("content")["src"].partition("#")
            items.append({
                "depth": depth,
                "title": nav.find("navLabel").get_text().strip(),
                "file": f"{ncx_dir}/{file_part}".replace("//", "/"),
                "anchor": anchor,
            })
            walk(nav, depth + 1)

    walk(soup.find("navMap"), 1)
    return items


def index_images(zf):
    """图片 zip 路径 → (输出文件名, 宽, 高)。宽高用于 <img width height> 占位。"""
    out = {}
    for name in zf.namelist():
        if "/Images/" not in name or name.endswith("/"):
            continue
        try:
            with Image.open(BytesIO(zf.read(name))) as im:
                out[name] = (Path(name).name, *im.size)
        except Exception:
            out[name] = (Path(name).name, 0, 0)
    return out


def collect_notes(zf, files):
    """脚注定义：p.<footnote_def> 内带 id 的 a，键为该 id。"""
    notes = {}
    for rel in files:
        soup = BeautifulSoup(zf.read(rel), "lxml-xml")
        for p in soup.find_all("p", class_=CONVENTIONS["footnote_def"]):
            a = p.find("a", id=True)
            if not a:
                continue
            label = norm(a.get_text())
            notes[a["id"]] = {"label": label, "text": norm(norm(p.get_text(" ")).replace(label, "", 1))}
    return notes


# ---------------------------------------------------------------- 块解析

class Ctx:
    """携带当前文件的相对基准，用来把图片路径解析成 zip 内路径。"""

    def __init__(self, notes, images, from_dir):
        self.notes, self.images, self.from_dir = notes, images, from_dir

    def image_of(self, src):
        real = posixpath.normpath(f"{self.from_dir}/{src}")   # ../Images/x.jpg → OEBPS/Images/x.jpg
        name, w, h = self.images.get(real, (Path(src).name, 0, 0))
        return {"src": f"images/{name}", "width": w, "height": h}


def inline_md(node, ctx):
    """把内联标签转成 Markdown；脚注引用转成 [^key]。"""
    out = []
    for c in node.children:
        if isinstance(c, str):
            out.append(c)
            continue
        name = c.name or ""
        if name in ("i", "em"):
            out.append(f"*{inline_md(c, ctx)}*")
        elif name in ("b", "strong"):
            out.append(f"**{inline_md(c, ctx)}**")
        elif name == "a":
            m = FOOTNOTE_REF.search(c.get("href") or "")
            out.append(f"[^{m.group(1)}]" if m else inline_md(c, ctx))
        else:
            out.append(inline_md(c, ctx))
    return "".join(out)


def parse_image(el, ctx):
    img = el.find("img")
    cap = el.find("p", class_=CAPTION)
    credit = el.find("p", class_=CREDIT)
    return {
        "type": "image",
        # 图题/图注也要走 inline_md：里面可能带脚注上标
        "caption": norm(inline_md(cap, ctx)) if cap else "",
        "note": norm(inline_md(credit, ctx)) if credit else "",
        **ctx.image_of(img["src"]),
    }


def parse_block(el, ctx):
    name = el.name
    cls = classes_of(el)

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        text = norm(el.get_text())
        return {"type": "heading", "level": int(name[1]), "text": text} if text else None

    if IMAGE_BOX.search(cls):
        return parse_image(el, ctx) if el.find("img") else None

    if name != "p" or CONVENTIONS["footnote_def"] in cls:
        return None                                # 脚注定义不进入正文

    text = norm(inline_md(el, ctx))
    if not text:
        return None
    return {"type": "quote" if QUOTE.search(cls) else "para", "text": text, "class": cls}


# ---------------------------------------------------------------- 章节组装

class Builder:
    """depth1 → unit（有子节点则视为"篇"），depth2 → 篇下的章 / 普通 unit 的节，depth3 → 节。"""

    def __init__(self, toc):
        self.toc, self.units = toc, []
        self.state = {"unit": None, "chapter": None, "target": None, "title": None}

    def holder(self):
        return self.state["chapter"] or self.state["unit"]

    def has_child(self, item):
        i = self.toc.index(item)
        return i + 1 < len(self.toc) and self.toc[i + 1]["depth"] > item["depth"]

    def enter(self, item):
        d = item["depth"]
        if d == 1:
            unit = {"kind": "part" if self.has_child(item) else "unit",
                    "title": item["title"], "blocks": [], "sections": [], "chapters": []}
            self.units.append(unit)
            self.state.update(unit=unit, chapter=None,
                              target=unit["blocks"], title=unit["title"])
        elif d == 2 and self.state["unit"] and self.state["unit"]["kind"] == "part":
            ch = {"title": item["title"], "blocks": [], "sections": []}
            self.state["unit"]["chapters"].append(ch)
            self.state.update(chapter=ch, target=ch["blocks"], title=ch["title"])
        else:
            sec = {"title": item["title"], "blocks": []}
            self.holder()["sections"].append(sec)
            self.state.update(target=sec["blocks"], title=item["title"])

    def rename(self, title):
        self.state["title"] = title
        node = self.holder()
        for sec in node["sections"]:
            if sec["blocks"] is self.state["target"]:
                sec["title"] = title
                return
        node["title"] = title

    def add(self, el, path, anchors, ctx):
        aid = el.get("id")
        hit = anchors.get((path, aid)) if aid else None
        if hit:
            self.enter(hit)
        if self.state["target"] is None:
            return
        blk = parse_block(el, ctx)
        if blk is None:
            return
        # 正文标题与目录标题重复时，用正文版本（全角空格）覆盖目录标题，而不是再插入一个标题
        if blk["type"] == "heading" and self.state["title"] and same_title(blk["text"], self.state["title"]):
            self.rename(norm(blk["text"]))
            return
        self.state["target"].append(blk)


def attach_notes(units, notes):
    """把每章真正引用到的脚注挂到该节点（magazine 用它渲染脚注表）。"""
    for unit in units:
        for node in [unit, *unit["chapters"]]:
            used = []
            blocks = list(node.get("blocks", [])) + [x for s in node["sections"] for x in s["blocks"]]
            for b in blocks:
                for field in ("text", "caption", "note"):
                    for key in re.findall(r"\[\^([^\]]+)\]", b.get(field) or ""):
                        if key not in used:
                            used.append(key)
            if used:
                node["notes"] = [{"key": k, **notes.get(k, {"label": "", "text": "（缺失）"})} for k in used]


def build_document(epub: Path):
    with zipfile.ZipFile(epub) as zf:
        base, spine, meta = load_package(zf)
        files = [f"{base}/{f}" for f in spine]
        toc = parse_toc(zf, base)
        anchors = {(t["file"], t["anchor"]): t for t in toc if t["anchor"]}
        file_toc = {}
        for t in toc:
            file_toc.setdefault(t["file"], t)
        notes = collect_notes(zf, files)
        images = index_images(zf)

        b = Builder(toc)
        for rel in files:
            soup = BeautifulSoup(zf.read(rel), "lxml-xml")
            if soup.body is None:
                continue
            ctx = Ctx(notes, images, str(Path(rel).parent))
            # 目录锚点不在正文元素上时（如锚点为空），用文件级目录项兜底
            if b.state["target"] is None and rel in file_toc:
                b.enter(file_toc[rel])
            for el in soup.body.find_all(True, recursive=False):
                b.add(el, rel, anchors, ctx)

        for u in b.units:                                  # 目录页 → 卷首
            if same_title(u["title"], CONVENTIONS["toc_page"]):
                u["blocks"] = [x for x in u["blocks"] if "contents" not in x.get("class", "")]
                u["title"] = "卷首"
        b.units[:] = [u for u in b.units if u["blocks"] or u["sections"] or u["chapters"]]

        attach_notes(b.units, notes)
        return {"meta": meta, "toc": toc, "notes": notes, "units": b.units}


# ---------------------------------------------------------------- 输出

def emit_blocks(blocks, lines):
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b["type"] == "quote":                        # 连续引文合并成一个引用块
            group = []
            while i < len(blocks) and blocks[i]["type"] == "quote":
                group.append(blocks[i]["text"])
                i += 1
            for k, g in enumerate(group):
                lines.append(("> " if k == 0 else ">\n> ") + g)
            lines.append("")
            continue
        if b["type"] == "heading":
            lines += ["#" * min(b["level"], 6) + " " + b["text"], ""]
        elif b["type"] == "image":
            cap = b["caption"]
            short = re.split(r"[\s\u3000]+", cap, maxsplit=1)[0] if cap else "插图"
            # Markdown 在 chapters/ 下，图片在 ../images/ → 补一层
            lines += [f"![{short}](../{b['src']})", ""]
            if cap:
                lines += [f"**{cap}**", ""]
            if b["note"]:
                lines += [f"*{b['note']}*", ""]
        else:
            lines += [b["text"], ""]
        i += 1


def slug(title: str) -> str:
    return re.sub(r"[\s\u3000]+", "-", title.strip()).replace("/", "-")


def write_markdown(doc, out: Path):
    ch_dir = out / "chapters"
    if ch_dir.exists():
        shutil.rmtree(ch_dir)
    ch_dir.mkdir(parents=True)

    index = ["# " + doc["meta"].get("title", "未命名"), "", f"作者：{doc['meta'].get('creator','')}", ""]
    n, grouped = 0, False

    def write(title, node, sections, prefix=None):
        nonlocal n
        n += 1
        lines = [f"# {title}", ""]
        if prefix:
            lines += prefix + [""]
        emit_blocks(node.get("blocks", []), lines)
        for sec in sections:
            lines += [f"## {sec['title']}", ""]
            emit_blocks(sec["blocks"], lines)
        for note in node.get("notes", []):
            lines.append(f"[^{note['key']}]: {note['text']}")
        if node.get("notes"):
            lines.append("")
        path = ch_dir / f"{n:02d}-{slug(title)}.md"
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        index.append(f"- [{title}](chapters/{path.name})")

    for unit in doc["units"]:
        if unit["kind"] == "part":
            index += ["", f"## {unit['title']}", ""]
            grouped = True
            intro = unit["blocks"]
            for ch in unit["chapters"]:
                prefix = None
                if intro:                                 # 篇导语并入首章
                    prefix = [x["text"] for x in intro if x.get("text")]
                    intro = []
                write(ch["title"], ch, ch["sections"], prefix)
            continue
        if grouped:
            index.append("")
            grouped = False
        write(unit["title"], unit, unit["sections"])

    (out / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return n


def export_images(epub: Path, out: Path):
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub) as zf:
        for src, (name, _, _) in index_images(zf).items():
            (img_dir / name).write_bytes(zf.read(src))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("-o", "--out", default="output")
    args = ap.parse_args()

    epub, out = Path(args.epub).expanduser(), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    doc = build_document(epub)
    (out / "book.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    export_images(epub, out)
    total = write_markdown(doc, out)

    chapters = sum(len(u["chapters"]) or 1 for u in doc["units"])
    print(f"{epub.name} → {out}/  units={len(doc['units'])} chapters={chapters} "
          f"notes={len(doc['notes'])} md={total}")


if __name__ == "__main__":
    main()
