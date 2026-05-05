# Ren'Py Bilingual Builder

### A GUI-assisted tool for building readable bilingual subtitle patches for Ren'Py games.

为 Ren'Py 游戏构建结构清晰、阅读舒适的双语字幕补丁。

本项目最初以《Eternum / 永恒世界》作为验证案例，但工具本身并不只面向这一款游戏。  
它主要适用于 **Ren'Py 游戏**，尤其是拥有标准 `.rpy` 翻译脚本结构的视觉小说项目。

> 当前版本不是通用游戏字幕工具，也不支持所有游戏引擎。  
> 其他 Ren'Py 游戏如果能准备原始英文 `.rpy` 和对应中文翻译 `.rpy`，理论上可以尝试适配。

---

## Demo

演示视频：

[📺 在 Bilibili 观看演示视频](https://www.bilibili.com/video/BV1bFREBqETU/)

示例效果：

```text
English line
中文行
```

建议在仓库中放入：

```text
samples/screenshots/before_english.png
samples/screenshots/before_chinese.png
samples/screenshots/after_bilingual.png
```

然后可在这里补充截图：

```markdown
![English](samples/screenshots/before_english.png)
![Chinese](samples/screenshots/before_chinese.png)
![Bilingual](samples/screenshots/after_bilingual.png)
```

---

## What is this?

Ren'Py Bilingual Builder 是一个面向 Ren'Py 游戏的双语字幕构建工具链。

它的目标不是简单把中英文粗暴堆成两行，而是尽量实现：

- 基于 `translate chinese xxx:` 块的结构化处理
- 英文主显示、中文辅助显示
- 更稳定的文本框布局
- 更适合实际游玩的双语阅读体验
- 对普通用户更友好的 GUI 操作流程

---

## Key Features

### GUI Preview

当前项目已经包含实验性桌面 GUI。

GUI 支持：

- 选择中文翻译目录
- 选择原始英文目录
- 选择输出目录
- 选择游戏目录
- 一键构建双语文件
- 查看构建日志
- 查看构建摘要
- 一键部署到 Ren'Py 游戏目录
- 部署前自动备份原 `tl/chinese`

---

### Block-based Dialogue Reconstruction

工具会按 Ren'Py 翻译块进行处理，而不是只依赖脆弱的逐行替换。

主要处理类似：

```renpy
translate chinese example_id:
    # mc "Hello."
    mc "你好。"
```

并生成更适合双语显示的文本结构。

---

### Original English Fallback

当中文翻译文件中缺少可靠英文原文时，工具可以尝试从原始英文 `.rpy` 脚本中补回英文。

---

### UI Patch

项目包含一个 Ren'Py UI 补丁：

```text
patches/zz_bilingual_ui_patch.rpy
```

它用于改善游戏内双语显示体验，包括：

- 固定文本框高度
- 减少字幕位置抖动
- 英文为主行
- 中文为辅行
- 提升长句阅读体验

---

### Diagnostic Report

构建完成后会生成 JSON 报告，用于检查：

- 已处理对白数量
- 未匹配对白数量
- 原始英文兜底数量
- 缺失原文数量

---

## Supported Scope

当前主要支持：

- Ren'Py `.rpy` 翻译脚本
- `translate chinese xxx:` 块
- 普通角色对白
- 旁白
- `extend`
- `centered`

常见支持形式：

```renpy
mc "Hello."
"Some narration."
extend "More text."
centered "Chapter 1"
```

---

## Not a Universal Game Subtitle Tool

请注意：

本项目目前主要面向 **Ren'Py 游戏**。

它不是：

- 所有英文游戏通用字幕工具
- Unity / Unreal / RPG Maker 通用工具
- 自动翻译器
- 游戏资源提取器
- 游戏本体分发工具

如果其他游戏也是 Ren'Py，并且脚本结构接近，可以尝试适配。  
但并不保证所有 Ren'Py 项目都能开箱即用。

---

## Quick Start: GUI

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run GUI

```bash
python app/gui.py
```

### 3. Select paths

在 GUI 中选择：

- 中文翻译目录
- 原始英文目录
- 输出目录
- 游戏目录

### 4. Build

点击：

```text
开始构建
```

工具会生成双语输出文件。

### 5. Deploy

点击：

```text
一键部署
```

工具会将生成结果复制到 Ren'Py 游戏目录中，并复制 UI patch。

部署时如果发现原有：

```text
game/tl/chinese
```

会先自动备份为：

```text
game/tl/chinese_backup_YYYYMMDD_HHMMSS
```

---

## Quick Start: CLI

如果你更喜欢命令行，也可以直接运行构建器：

```bash
python tools/build_bilingual.py \
  --src input/chinese_tl \
  --src-original input/original_english \
  --dst output/tl/chinese \
  --report-json output/reports/build_report_gui.json
```

生成结果会输出到：

```text
output/tl/chinese
```

然后你可以手动复制到游戏目录：

```text
game/tl/chinese
```

并将 UI patch 复制到：

```text
game/zz_bilingual_ui_patch.rpy
```

---

## Input Requirements

你需要自行准备两个输入目录。

### 1. Translated Chinese `.rpy` files

```text
input/chinese_tl/
```

这里放中文翻译 `.rpy` 文件。

### 2. Original English `.rpy` files

```text
input/original_english/
```

这里放同版本原始英文 `.rpy` 文件。

推荐目标文件包括：

```text
script.rpy
script2.rpy
script3.rpy
script4.rpy
script5.rpy
script6.rpy
script7.rpy
script8.rpy
script9.rpy
gallery_replay.rpy
```

不同 Ren'Py 游戏的脚本文件名可能不同，后续版本会继续增强通用性。

---

## Project Structure

```text
renpy-bilingual-builder/
├─ app/
│  └─ gui.py
├─ tools/
│  ├─ build_bilingual.py
│  ├─ build_bilingual_v2.py
│  └─ build_bilingualv1.py
├─ patches/
│  └─ zz_bilingual_ui_patch.rpy
├─ input/
│  ├─ chinese_tl/
│  └─ original_english/
├─ output/
│  ├─ tl/
│  └─ reports/
├─ unresolved/
├─ samples/
│  └─ screenshots/
├─ requirements.txt
├─ README.md
└─ .gitignore
```

如果你的实际仓库结构和这里不同，请以仓库当前文件为准。

---

## Current Components

### `app/gui.py`

实验性桌面 GUI。

适合不想使用命令行的用户。

---

### `tools/build_bilingual.py`

当前主构建器。

主要功能：

- 基于 Ren'Py 翻译块解析
- 双源输入
- 原始英文兜底
- 生成双语 `.rpy`
- 输出诊断报告

---

### `tools/build_bilingual_v2.py`

早期块级解析版本。

保留用于参考和回归测试。

---

### `tools/build_bilingualv1.py`

最早的 MVP 版本。

主要依赖“英文注释 + 下一行中文”的相邻行匹配。

---

### `patches/zz_bilingual_ui_patch.rpy`

游戏内 UI 显示补丁。

用于优化双语字幕显示效果。

---

## Example Workflow

1. 准备目标 Ren'Py 游戏
2. 提取或准备中文翻译 `.rpy`
3. 提取或准备原始英文 `.rpy`
4. 打开 GUI
5. 选择输入和输出目录
6. 点击构建
7. 查看日志与摘要
8. 一键部署到游戏目录
9. 启动游戏测试双语效果

---

## What is NOT included

为避免分发受版权保护内容，本仓库不包含：

- 游戏本体
- `.rpa` 归档文件
- `.rpyc` 编译文件
- 完整商业翻译包
- 完整游戏脚本数据集
- 字体文件
- 图片资源
- 音频资源
- 存档文件
- 缓存文件

用户必须自行准备合法的游戏文件和翻译资源。

---

## Known Limitations

### Ren'Py only

当前主要面向 Ren'Py。  
其他游戏引擎暂不支持。

---

### Not all Ren'Py games are guaranteed

不同 Ren'Py 项目的脚本结构可能不同。  
如果脚本结构差异较大，可能需要手动适配。

---

### Dialogue-focused

当前主要优化普通对白文件。  
系统 UI、角色名、菜单、复杂自定义逻辑暂不作为主处理目标。

---

### Text tag compatibility

带复杂 Ren'Py 文本标签的句子可能需要保守处理。  
后续版本会继续提升兼容性。

---

### Alignment gaps

少量句子可能由于以下原因无法自动匹配：

- 角色前缀不兼容
- 原文缺失
- 翻译脚本结构变化
- 自定义脚本格式特殊

---

## Roadmap

- [ ] GUI polish
- [ ] Windows executable release
- [ ] Better game directory auto-detection
- [ ] Safer Ren'Py text tag handling
- [ ] Export unresolved blocks
- [ ] LLM-assisted unresolved repair
- [ ] Better match-rate report
- [ ] More flexible target file detection
- [ ] Broader Ren'Py project compatibility

---

## For Users

如果你只是想使用双语补丁：

1. 准备对应版本游戏
2. 准备翻译文件
3. 使用 GUI 构建和部署
4. 启动游戏测试

本项目不提供游戏本体。

---

## For Developers

欢迎提交 issue、PR 或适配其他 Ren'Py 项目的经验。

适合贡献的方向：

- GUI 改进
- 兼容更多 Ren'Py 脚本结构
- 更好的 text tag 处理
- unresolved 自动修复流程
- Windows 打包
- 文档和示例补充

---

## License

MIT