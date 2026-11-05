# 探查与约定填写

## 1. 跑 probe

```bash
python scripts/probe_epub.py 书.epub
```

输出五段，逐段判读：

### ① 概览

```
EPUB: 书.epub
META: {'title': ..., 'creator': ..., 'publisher': ...}
spine: 62 个文档 | 图片: 30 张
```

`spine` 数量远小于目录条目 → 说明一章拆成多文件，或一章一个文件；两者脚本都能处理（按锚点切分）。

### ② 目录

```
目录源: EPUB2 ncx: OEBPS/toc.ncx  条目 59
  d1 上篇 微观机制  →  OEBPS/Text/part0006.xhtml#isbn…1
    d2 第一章 …     →  OEBPS/Text/part0007.xhtml#isbn…1_1
      d3 第一节 …   →  OEBPS/Text/part0008.xhtml#isbn…1_1_1
层级分布: {1: 8, 2: 8, 3: 43}
```

- 三层（篇/章/节）→ `Builder` 的 depth1=part、depth2=chapter、depth3=section 分支正好覆盖
- 两层（章/节）→ 章会落成 `unit`，节落成 `unit.sections`，同样可用；此时目录里"篇"的层级不存在
- 全是一层 → 所有条目都成 `unit`，每章一个文件，没有节

### ③ 元素 + class 频次

找三类：

| 要找的 | 长什么样 |
| --- | --- |
| 正文段落 | 数量最多、文本最长的 `<p class="…">`（如 `bodycontent`） |
| 脚注段落 | 数量与"每章脚注数 × 章数"相当、文本短、以编号开头（如 `fncontent`） |
| 引文段落 | class 里带 `kaiti` / `quote` / `copycontent` / `signcontent` / `epigraph` |

### ④ 脚注候选

```
a#jz_1_14 < p.fncontent < body.calibre   | (1)
… 另有 56 个链接指向普通位置（目录/交叉引用），已忽略
```

这行直接给出两个约定：

- `footnote_def = "fncontent"`（定义所在段落的 class）
- 引用形态由 `a[href]` 决定，取 id 的规律 → `footnote_ref = r"#(jz_\w+)$"`

若没有输出「脚注候选」，说明这本书没有脚注，或脚注用了别的机制（见第 3 节）。

### ⑤ 图片所在父元素 class

```
   26  <parent class="chatu_img">
```

→ `image_box = "chatu_img"`；再对上一条图注候选（`tuti` / `tuzhu`）即可确定 `caption` / `credit`。

## 2. 六项约定怎么填

```python
CONVENTIONS = {
    "footnote_def": "fncontent",                 # 脚注定义段落 class
    "footnote_ref": r"#(jz_\w+)$",               # 正文引用 href 的正则（分组 1 = key）
    "image_box": r"chatu_img|^title_img$",       # 图片容器 class
    "caption": r"tuti",                          # 图题 class
    "credit": r"tuzhu",                          # 图注/数据来源 class
    "quote": r"kaiti|copycontent|signcontent",   # 引文 class
    "toc_page": "目录",                          # 目录页标题，渲染时改名"卷首"
}
```

- `footnote_ref` 的分组必须只匹配 key 本身，不要带 `#`
- 一本书里出现多种引文类名时用 `|` 合并，宁可多匹配也别漏（引文匹配过宽只会让个别段落变成引用块，容易肉眼发现）
- 没有图注的书把 `credit` 设成一个不会命中的正则（如 `r"__none__"`）

## 3. 不同来源 EPUB 的特征

| 来源 | 常见特征 | 处理 |
| --- | --- | --- |
| calibre 转换（本书） | `toc.ncx` + `Text/partNNNN.xhtml`，`fncontent` / `chatu_img` / `tuti` / `tuzhu`，脚注双向回链 | 模板默认即是 |
| Sigil / 手作 EPUB3 | 只有 `nav.xhtml`（`<nav epub:type="toc">`），`<figure>/<figcaption>` | `parse_toc` 换成读 nav 的嵌套 `<ol>`；图题取值改 `figcaption` |
| 出版社原始 | class 是语义化的（`chapter` / `para` / `caption` / `note`），可能有 `<section epub:type="chapter">` | 约定用语义类名；容器 div 需要递归下钻 |
| Kindle 导出 | `<div class="calibreN">` 满天飞，class 基本无语义，标题靠 `<h1>`~`<h4>` | 用标签判定：`h1/h2/h3` 定层级，`blockquote` 当引文，`figure/figcaption` 当图，脚注看 `epub:type` |
| 扫描 OCR 转 EPUB | 无脚注结构、段落被硬换行切碎 | 段落合并（`joinSoft`），脚注可放弃或按行首编号抓取 |

## 4. 边界情况

**目录锚点为空**

```
d1 第一章  →  OEBPS/Text/ch01.xhtml#-
```

说明 toc 指向整个文件而不带 `#anchor`。模板里的 `file_toc` 兜底会处理：进入该文件时创建 unit/章，然后按 spine 顺序写入。

**一章跨多个文件**

锚点分别落在不同文件，脚本会依次 `enter()` 创建 section，内容自然分段，无需特殊处理。

**同一文件包含多章**

`anchor_map` 按 `(file, anchor)` 匹配，遍历时遇到锚点就切换目标，也能正确切分 —— 前提是锚点挂在正文元素上（模板的 `emit` 会先 `enter` 再解析该元素）。

**标题重复**

ncx 标题 `第一节 分税制改革`（半角空格）与正文 `<h2>第一节　分税制改革</h2>`（全角）不完全相等，但 `same_title` 去掉空白与标点后判定相同 → 用正文版本覆盖目录标题，不重复插入。

**脚注在文件末尾（尾注）**

同一文件里的 `<a href="#fn1">` → 文件末尾 `<p class="footnote">`。只要定义段落的 class 进了 `footnote_def`，跨不跨文件都能配对上。

**图题里带脚注**

`<p class="tuti">图5-3（b）…<a href="#note23">(23)</a></p>`。`parse_image` 里必须用 inline 转换而不是 `get_text()`，否则这条脚注会变成"定义了却没被引用"。

**封面 / 版权页**

它们会作为 `unit` 出现。封面只有图（blocks 只有 image）；版权页是一堆短段落，都无需特殊处理。若封面纯装饰想略过，在 `build_document` 末尾按 title 过滤。
