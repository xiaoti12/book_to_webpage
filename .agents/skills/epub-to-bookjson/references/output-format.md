# 产物格式与 magazine 消费规则

## 1. book.json

```json
{
  "meta": { "title": "书名", "creator": "作者", "publisher": "出版社", "date": "2021-08-01" },
  "toc":  [ { "depth": 1, "title": "上篇　微观机制", "file": "OEBPS/Text/part0006.xhtml", "anchor": "isbn…" } ],
  "notes": { "jz_1_53": { "label": "(1)", "text": "脚注正文" } },
  "units": [
    {
      "kind": "unit",
      "title": "前言　从了解现状开始",
      "blocks": [ { "type": "para", "text": "…" } ],
      "sections": [ { "title": "本书结构与数据说明", "blocks": [ … ] } ],
      "chapters": [],
      "notes": [ { "key": "jz_1_53", "label": "(1)", "text": "…" } ]
    },
    {
      "kind": "part",
      "title": "上篇　微观机制",
      "blocks": [ { "type": "para", "text": "篇导语" } ],
      "sections": [],
      "chapters": [
        { "title": "第一章　地方政府的权力与事务", "blocks": [], "sections": [ … ], "notes": [ … ] }
      ]
    }
  ]
}
```

要点：

| 字段 | 说明 |
| --- | --- |
| `units` | 顶层单元数组。`kind: "unit"` = 平铺章节；`kind: "part"` = 篇，内容在 `chapters`，篇导语在 `blocks` |
| `blocks` | 章/篇的导语区（章标题之后、第一个节之前的内容） |
| `sections` | 节数组，每项 `{ title, blocks }`。**magazine 的目录展开只读这个字段** |
| `toc` | 原始目录快照，仅供追溯，magazine 不读 |
| `notes`（顶层） | 全量脚注表 `key → {label, text}` |
| `notes`（章级） | 数组，只放本章引用到的脚注；magazine 用它渲染章末脚注表和悬停浮层 |

## 2. block 类型

| type | 字段 | 渲染 |
| --- | --- | --- |
| `para` | `text` | 段落；章内第一个段落自动首字下沉 |
| `heading` | `level`(3~4), `text` | 小标题（`###`）；不要用它写章/节标题，那由 units/sections 承担 |
| `quote` | `text` 或 `paras[]` | 引用块；连续的多个 quote 会合并 |
| `image` | `src`, `width`, `height`, `caption`, `note` | 图片 + 图题 + 图注；宽高用于占位，**必须给** |
| `list` | `ordered`, `items[]` | 列表 |
| `table` | `rows[][]` | 表格（magazine 暂按段落降级渲染） |
| `hr` | — | 分隔线 |

`text` 里允许的内联标记：`**粗体**`、`*斜体*`、`[^key]`（脚注引用）。图片的 `caption` / `note` 也支持 `[^key]`，会渲染成图题里的可点上标。

## 3. Markdown 格式

`chapters/NN-章名.md`：

```markdown
# 第二章 财税与政府行为

章导语段落……

## 第一节 分税制改革

正文段落，带脚注引用。[^jz_1_53]

### “财政包干”及后果：1985—1993年

> 引文段落（`>` 开头）
>
> 引文第二段

![图2-1](../images/image00209.jpeg)

**图2-1　地方公共预算收支占全国收支的比重**

*数据来源：万得数据库。*

[^jz_1_53]: 脚注正文
```

约定：

- 每章一个文件，`#` = 章，`##` = 节，`###` = 小标题
- 图片路径相对 `chapters/`，所以是 `../images/xxx.jpeg`
- 图题用 `**加粗**` 独占一行，图注用 `*斜体*` 独占一行（magazine 的 md 解析器会把紧邻图片的这两行收进 figure）
- 脚注定义必须写在**同一文件**末尾，key 与正文一致

`index.md`（magazine 的 Markdown 目录模式入口）：

```markdown
# 书名

- [第一章　…](chapters/01-第一章.md)
- [第二章　…](chapters/02-第二章.md)
```

必须是 `- [标题](相对路径.md)` 形式的列表；magazine 解析出条目后按需 fetch 每个文件。

## 4. magazine 的读取规则

- `?src=x.json` → 读 `units`（也接受 `chapters` 平铺数组或纯数组）
- `?src=index.md` → 解析其中的链接列表，懒加载各章；`?src=a.md,b.md` → 逐个作为一章
- 图片路径由 `new URL(src, 数据文件URL)` 解析，所以 **`src` 相对数据文件位置**即可
- 目录展开读 `sections[].title`；`sections` 为空时该章不显示展开按钮
- 章标题里 `第X章　副题` 会被拆成 kicker 标签 + 主标题；`前言/结语/参考文献` 同理
- `[^key]` 的显示序号按**首次引用顺序**重排，与 `notes` 里的 `label` 无关（`label` 仅作追溯）
- 元信息：`meta.title`（刊头，会清洗掉 `【推荐语】`）、`meta.creator`、`meta.publisher`、`meta.date`
