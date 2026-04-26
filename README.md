# Ren'Py Bilingual Builder
### Build readable and structured bilingual subtitle patches for Ren'Py games.
### 演示视频
[📺 点击此处在 Bilibili 观看演示视频](https://www.bilibili.com/video/BV1GVd5BTES3/)

为Ren'Py游戏构建可读性强、结构清晰的双语字幕补丁。

本项目提供一套实用的工具链，将标准Ren'Py翻译文件转换为更舒适的双语阅读体验。

不同于脆弱的逐行替换或原始的两行堆叠，本项目专注于：
- 基于对话块的重构
- 稳定的双语布局
- 英文为主/中文为辅的阅读层级
- 更适合迭代优化的工程化工作流


## 特性

### 基于对话块的处理
对 `translate chinese xxx:` 段落采用块级解析，而非仅依赖相邻注释匹配。

### 对话导向的工作流
针对对话密集的脚本文件优化，例如：
- `script.rpy`
- `script2.rpy` 至 `script9.rpy`
- `gallery_replay.rpy`

### 英中双语重构
将支持的对话重写为：
```text
English line
中文行
```
并结合专用UI补丁提升游戏内可读性。

### 原始英文兜底
当翻译文件不再包含可靠的英文原文行时，当前构建器可使用原始英文脚本文件作为兜底来源。

### 诊断报告
输出结构化的JSON报告，帮助检查：
- 已处理的块
- 已处理的语句
- 未匹配的块/语句
- 兜底使用情况
- 缺失的原始英文来源

### 包含UI补丁
附带专用的Ren'Py UI补丁，用于：
- 固定文本框高度
- 减少对话抖动
- 更好的双语行层级
- 提升长行可读性


## 当前组件

### `tools/build_bilingualv1.py`
原始的MVP构建器。
主要特点：
- 相邻行匹配
- 依赖英文注释+中文行配对
- 可用作早期基线/回归参考

### `tools/build_bilingual_v2.py`
改进的基于块的构建器。
主要特点：
- 解析 `translate chinese xxx:` 块
- 支持常见对话形式
- 适用于常规对话重构
- 目前推荐作为持续开发的基础

### `tools/build_bilingual.py`
当前的双源增强版本。
主要特点：
- 基于块的解析
- 原始英文兜底
- 更好的诊断功能
- 适合作为当前主构建器

### `patches/zz_bilingual_ui_patch.rpy`
用于提升游戏内体验的UI补丁。
负责：
- 固定文本框高度
- 更稳定的字幕位置
- 英文为主行
- 中文为辅行
- 相比原始 `\n` 堆叠提升可读性


## 支持的对话类型
当前工作流主要聚焦于标准对话语句：
- 角色对话：`mc "..."`、`e "..."` 等
- 旁白行：`"..."`
- `extend "..."`
- `centered "..."`


## 快速开始

### 1. 准备输入
需要两个输入目录：
- `input/chinese_tl/`：从目标Ren'Py游戏提取的已翻译.rpy文件
- `input/original_english/`：同一游戏版本的原始英文.rpy文件

推荐的目标文件包括：
`script.rpy`、`script2.rpy` 至 `script9.rpy`、`gallery_replay.rpy`

### 2. 运行构建器
若当前主构建器是v3/双源版本，运行：
```bash
python tools/build_bilingual.py \
  --src input/chinese_tl \
  --src-original input/original_english \
  --dst output/tl/chinese \
  --report-json output/reports/build_report_v25.json
```
若增强版本仍使用其他文件名，请相应替换脚本路径。

### 3. 部署输出
生成的双语文件将写入：
`output/tl/chinese/`

将其复制到游戏的：
`game/tl/chinese/`

### 4. 应用UI补丁
将：
`patches/zz_bilingual_ui_patch.rpy`

复制到游戏的：
`game/`

### 5. 清除缓存并测试
在游戏内测试前，必要时清除Ren'Py缓存，然后验证：
- 常规对话
- 旁白行
- `extend`
- `centered`
- 长双语行
- 整体文本框稳定性


## 示例工作流
1. 将已翻译的.rpy文件提取到 `input/chinese_tl/`
2. 将原始英文.rpy文件提取到 `input/original_english/`
3. 运行构建器
4. 将生成的文件从 `output/tl/chinese/` 复制到游戏的 `game/tl/chinese/`
5. 将 `patches/zz_bilingual_ui_patch.rpy` 复制到游戏的 `game/`
6. 清除Ren'Py缓存
7. 启动游戏并验证双语效果


## 项目结构
```
renpy-bilingual-builder/
├─ tools/
│  ├─ build_bilingual.py
│  └─ legacy/
│     ├─ build_bilingual_v1.py
│     └─ build_bilingual_v2.py
├─ patches/
│  └─ zz_bilingual_ui_patch.rpy
├─ samples/
│  ├─ input_demo/
│  ├─ output_demo/
│  └─ screenshots/
├─ docs/
│  └─ report_sample.json
├─ input/
│  ├─ chinese_tl/
│  └─ original_english/
├─ output/
│  └─ reports/
├─ .gitignore
└─ README.md
```
你可根据最终仓库的发布方式简化此结构。


## 输入要求
本项目不为你提取或反编译游戏文件。

你必须自行准备：
- 已翻译的Ren'Py .rpy文件
- 原始英文Ren'Py .rpy文件

工具假设这些输入已以可提取/可用的形式存在。


## 不包含的内容
为避免重新分发受版权保护的内容，本仓库不包含：
- 原始游戏文件
- .rpa归档文件
- .rpyc编译文件
- 预制的商业翻译包
- 来自受版权保护游戏的完整提取对话数据集
- 字体、图片、音频或其他游戏资产
- 存档文件、缓存文件或本地用户数据

用户必须自行提供合法的游戏文件和翻译资源。


## 限制
### 聚焦范围
本项目主要针对对话密集的文件优化，而非完整引擎UI覆盖。

### 语句覆盖
当前解析器聚焦于常见对话语句类型。更复杂的自定义脚本结构可能仍需手动调整。

### 对齐缺口
若存在以下情况，可能仍会有少量未匹配行：
- 角色前缀不兼容
- 源对齐不可靠
- 翻译脚本缺乏足够的结构对应

### UI/系统排除
系统UI、名称及相关引擎敏感文件有意从主对话工作流中排除，以降低破坏游戏的风险。


## 项目存在的原因
大多数临时的双语视觉小说补丁尝试通常存在以下一个或多个问题：
- 原始行堆叠
- 不稳定的文本框布局
- 长行可读性差
- 脆弱的匹配逻辑
- 难以维护的一次性脚本

本项目试图在以下方面取得更好的平衡：
- 可读性
- 结构正确性
- UI稳定性
- 工程可维护性


## TODO
- 完善边缘情况原始英文脚本的兜底逻辑
- 导出未解决的块以用于LLM辅助修复
- 添加结构化的基于JSON的合并流程
- 改进诊断和匹配率报告
- 扩展对更多Ren'Py语句类型的支持
- 拓宽更多Ren'Py项目的兼容性


## 许可证
MIT