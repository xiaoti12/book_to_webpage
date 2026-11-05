# EPUB → book.json → 杂志排版阅读器

把 EPUB 电子书抽取成结构化数据（`book.json` + 分章 Markdown + 图片），再用一个单文件 HTML 模板排版成杂志风格的在线阅读页。

```
EPUB ──probe_epub.py──▶ 结构探查 ──▶ 填 6 项约定 ──▶ extract 脚本 ──▶ book.json / index.md / chapters/ / images/
                                                                          │
                                                                magazine.html（单文件，无构建）
```

## 目录结构

```
.
├── magazine.html                          # 单文件阅读器模板（无构建、无框架）
└── .agents/skills/epub-to-bookjson/
    ├── SKILL.md                           # 工作流 + 硬规则 + 验收标准
    ├── references/output-format.md        # book.json / Markdown 数据契约
    ├── references/probing-and-conventions.md
    └── scripts/
        ├── probe_epub.py                  # 结构探查
        ├── extract_template.py            # 可复制的导出骨架（只改顶部约定）
        └── check_output.py                # 产物校验
```

## 环境

```bash
python3 -m venv .venv
.venv/bin/pip install beautifulsoup4 lxml pillow        # 抽取
# 可选：PDF 交叉校验时再装 pymupdf
```

## 一、抽取 EPUB

不是通用转换器，而是**一本书一个脚本**：先探查结构，把该书的 class / 锚点规则填进骨架顶部的 6 项约定，再跑。

```bash
# 1. 探查：目录层级、元素/class 频次、脚注与图注候选
.venv/bin/python .agents/skills/epub-to-bookjson/scripts/probe_epub.py 书.epub

# 2. 写脚本：复制骨架，只改 CONVENTIONS 六项（脚注定义 / 脚注引用 / 图片容器 / 图题 / 图注 / 引文）
cp .agents/skills/epub-to-bookjson/scripts/extract_template.py extract_xxx.py

# 3. 生成：默认取目录里的 epub，输出目录可指定
.venv/bin/python extract_xxx.py 书.epub -o out

# 4. 校验：结构 / 脚注闭合 / 图片 / Markdown 一致性
.venv/bin/python .agents/skills/epub-to-bookjson/scripts/check_output.py out/
```

产出（每次运行重建）：

```
out/
├── index.md        # 全书目录（- [标题](chapters/xx.md) 列表）
├── book.json       # 结构化数据（章节树 / blocks / 脚注 / 图片路径）
├── chapters/       # 分章 Markdown（章导语 + 各节 + 脚注）
└── images/         # 图片
```

语义还原要点：篇/章/节多级目录、引文 → 引用块、图题与数据来源、脚注按锚点双向配对。不同书的边界情况见 `references/probing-and-conventions.md`，最常见的坑（class 字符串、目录锚点去重、脚注双向回链、图题内嵌脚注、图片宽高缺失导致布局错位）写在 `SKILL.md` 的硬规则里。

## 二、杂志排版阅读器

`magazine.html` 直接加载上面的 JSON 或任意 Markdown：

```bash
python3 -m http.server 8000
```

| 访问 | 说明 |
| --- | --- |
| `http://localhost:8000/magazine.html` | 默认读 `output/book.json` |
| `.../magazine.html?src=out/book.json` | JSON 模式（章节树 + 脚注） |
| `.../magazine.html?src=out/index.md` | Markdown 模式，自动解析 `index.md` 里的目录链接，按需加载各章 |
| `.../magazine.html?src=notes/a.md,notes/b.md` | 多个 Markdown，逗号分隔 |
| `.../magazine.html?src=notes/post.md` | 单篇 Markdown |
| `.../magazine.html?src=out/book.json#6-3` | 深链到第 6 章第 3 节 |

**不经服务器**：直接双击打开 `magazine.html`，把 `.json` / `.md` 文件拖进页面即可（浏览器禁止 `file://` 下的 fetch，故改为文件选择）。

### 支持的内容格式

- JSON：`{meta, units:[{title, blocks, chapters:[{title, blocks, sections:[{title, blocks}], notes}]}]}`，也接受 `chapters` 平铺数组或纯数组
- block 类型：`para` / `heading` / `quote` / `image`（可带 `caption`、`note`）/ `list` / `hr`
- Markdown：ATX 标题（`#`→章、`##`→节、`###`→小标题）、段落、`>` 引用、图片 + 紧随的 `**图题**` 与 `*来源*` 行、`[^脚注]` 与 `[^key]: 定义`、粗斜体、行内链接、列表、分隔线、YAML front-matter 的 `title`

### 排版特性

双线刊头 · 目录侧栏可展开小节并随滚动高亮（移动端抽屉）· 首字下沉 · 「第X章/第X节」类型标签与主标题分离 · 图片与正文同宽（竖图自动收窄，`is-wide` 可跨栏）、宽高占位防跳动、灯箱 · 图题与数据来源 · 脚注悬停浮层 + 章末脚注表 · 阅读进度条与迷你顶栏 · 键盘 `←/→` 翻章 · 图片懒加载 · 打印样式

## 注意

- 仅用于处理自己有权使用的电子书；抽取产物（`book.json`、`chapters/`、`images/`）包含原书正文，请勿随仓库分发。
