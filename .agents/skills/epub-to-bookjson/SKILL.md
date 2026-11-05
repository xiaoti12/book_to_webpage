---
name: epub-to-bookjson
description: 把 EPUB 电子书抽取成 magazine 阅读器可用的 book.json + 分章 Markdown（含图片、图题、引文、脚注），并为某一本具体 EPUB 编写或调整 Python 导出脚本。当需要导出电子书章节内容、复用 EPUB→JSON 抽取流程、或排查导出产物问题（章节缺失、脚注错位、图题丢失、图片路径失效、目录只有章没有节）时使用。关键词：EPUB、epub 提取、电子书转 Markdown、book.json、分章导出、脚注、图注、magazine.html。
---

# EPUB → book.json / Markdown

## 产出结构

```
out/
├── book.json          # magazine.html?src=out/book.json
├── index.md           # magazine.html?src=out/index.md（Markdown 目录模式入口）
├── chapters/01-章名.md
└── images/*.jpg
```

## 工作流

1. **探查**：`python scripts/probe_epub.py 书.epub`
   输出目录层级、元素/class 频次、脚注候选（含祖先 class 链）、图注候选。
2. **定约定**：按探查结果填 `CONVENTIONS` 六项（脚注定义 / 脚注引用 / 图片容器 / 图题 / 图注 / 引文）。
3. **写脚本**：复制 `scripts/extract_template.py` 到项目，只改 `CONVENTIONS`，跑出产物。
4. **校验**：`python scripts/check_output.py out/`，再 `python -m http.server` 打开 `magazine.html` 目视。

不要追求通吃所有 EPUB。针对一本书写/调一个脚本，比维护通用转换器可靠得多；六项约定足以覆盖绝大多数书。

## 数据契约（写脚本前必读）

完整 schema 见 [references/output-format.md](references/output-format.md)。三条最容易错：

- 图片 `src` 相对 **book.json 所在目录**；Markdown 在 `chapters/` 下，必须多写一层 `../`。
- 脚注 key 与正文 `[^key]` 严格一致；每章的 `notes` 数组只放本章引用到的条目。
- `index.md` 必须是 `- [标题](chapters/xx.md)` 列表，否则 magazine 的 Markdown 模式找不到章节。

## 硬规则（改脚本必踩的坑）

1. `lxml-xml` 解析下 `class` 是**字符串**；`" ".join(el.get("class"))` 会把 `"fncontent"` 拆成单字符。
2. 目录锚点常挂在 `<h1>`/`<h2>` 或容器 `<div>` 上：命中锚点后仍要解析该元素（否则标题丢失），但同名标题必须去重，否则一节出现两个标题。
3. 脚注是双向回链（正文→定义→正文）。只认一个方向，否则脚注数翻倍。
4. ncx 标题用半角空格、正文标题用全角空格（`\u3000`）。比较用 `re.sub(r"[\W_]+", "", s)`。
5. 图题 / 图注里可能嵌脚注链接，`get_text()` 会吃掉它们，必须走 inline 转换（否则脚注变"定义了却没引用"）。
6. 图片不写 `width`/`height`，magazine 跳到小节后布局会错位（它用宽高做占位）。
7. 目录页混在 units 里会产出空章节：过滤 `contents` 类段落并改名为「卷首」。

## 验收标准

- `check_output.py` 0 错误 0 警告
- 脚注数、图片数、章节数与 `probe_epub.py` 统计吻合
- 与 PDF / 原书抽查对账：字数差异只应来自页眉页码（<1%）
- 浏览器里：目录可展开小节、图题图注在位、脚注浮层可点、滚动/跳转时图片不跳动

## 资源

- [references/output-format.md](references/output-format.md) — book.json schema、block 类型、Markdown 格式、magazine 消费规则
- [references/probing-and-conventions.md](references/probing-and-conventions.md) — probe 输出判读、六项约定填法、不同来源 EPUB 的特征、边界情况
- `scripts/probe_epub.py` — 结构探查
- `scripts/extract_template.py` — 可复制的导出骨架（本书实测与正式脚本输出逐块一致）
- `scripts/check_output.py` — 产物校验（结构 / 脚注闭合 / 图片 / Markdown 一致性）
