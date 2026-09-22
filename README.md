# Ren’Py Bilingual Builder

把已有的 Ren’Py 翻译与原文合并为双语对白，提供桌面界面、构建报告和带备份的安装流程。

A desktop tool for combining existing Ren’Py translations with their source text. It supports language detection, arbitrary script filenames, conservative parsing, and recoverable builds and deployment.

![桌面界面：使用内置示例完成一次构建](samples/screenshots/tool_gui.png)

## 先试用，不需要游戏文件

需要 **Python 3.10 或更高版本**，以及 Tk 桌面组件。当前提供源码版界面，不是免安装的 Windows `.exe`。

### Windows

1. 下载本仓库的 ZIP 并解压，或使用 Git 克隆。
2. 安装 [Python](https://www.python.org/downloads/)，安装时启用添加到 PATH。
3. 双击项目中的 **`start_windows.bat`**。首次启动会建立 `.venv` 并联网安装界面依赖。
4. 点击 **“试用内置示例” → “生成双语文件” → “打开输出目录”**。

示例是原创文本，预期生成 4 条双语对白。没有游戏文件也能完整体验构建；示例不应安装到其他游戏。

### Linux / macOS

```bash
bash start.sh
```

Python 需要带有 Tk。Linux 缺少 Tk 时，按发行版方式安装 `python3-tk`；macOS 可使用带 Tk 的 Python 安装包。

也可以手动启动：

```bash
python -m pip install -r requirements.txt
python app/gui.py
```

## 给自己的游戏生成双语

| 界面项目 | 需要选择什么 |
| --- | --- |
| 已有翻译 | `game/tl/` 下实际的语言目录，例如 `chinese`、`schinese`、`spanish`；需要 `.rpy` 源文件 |
| 翻译语言标识 | 工具从翻译块识别；有多个语言时需选择，建议直接选对应的语言子目录 |
| 原文目录 | 可选。翻译注释已有原文时留空即可；缺少注释时选择同一游戏版本的原始 `.rpy` 目录补充 |
| 双语输出目录 | 与输入分开的目录，用于存放完整输出；不要选择游戏的输入目录 |
| 游戏配置 | 默认“通用 Ren’Py”；仅《永恒世界》0.9.5 中文适配选择对应专用配置 |
| 游戏目录 | 安装时才需要，可以选择游戏根目录或其中的 `game` 文件夹 |

1. 选择翻译目录，确认识别出的语言。
2. 点击 **“生成双语文件”**，查看已处理数量和诊断。
3. 检查输出后，完全关闭游戏，点击 **“备份并安装到游戏”**。
4. 重启游戏，并在游戏自己的设置中选择对应翻译语言。

安装目标是 `game/tl/<语言标识>`。原文件备份放在 `game` 目录外的 `renpy_bilingual_backups/`。
改动输入、语言、配置或输出路径后，需要重新构建才能安装，防止安装错误的一套文件。

例如输入：

```renpy
translate spanish welcome_123:
    # guide "Welcome!"
    guide "¡Bienvenido!"
```

输出：

```renpy
translate spanish welcome_123:
    # guide "Welcome!"
    guide "Welcome!\n¡Bienvenido!"
```

## 通用模式与游戏适配

| 能力 | 通用 Ren’Py | 永恒世界 0.9.5 中文适配 |
| --- | --- | --- |
| 识别任意 `.rpy` 文件名和子目录 | 支持 | 支持 |
| 目标语言 | 自动识别或指定 | `chinese` |
| 生成原文＋译文 | 支持 | 支持 |
| 游戏界面、字号 | 沿用原游戏 | 可安装专用文本框补丁 |
| 特效字号冲突修复 | 不注入专用字号包装 | 保留已验证的 `{sc}` / `{bt}` 兼容处理 |

通用模式根据标准翻译结构生成文本，不依赖《永恒世界》的角色、资源或 `persistent` 设置。
它不会自动调整其他游戏的文本框高度、字体或自定义屏幕；双语长句是否放得下仍需在游戏中检查。
已有译文的语言切换、字体支持和自定义文本效果仍由游戏负责。

**适用范围是标准 Ren’Py 翻译项目，不是所有游戏引擎。** 当前支持普通双引号对白、旁白、`extend`、`centered` 及其可识别的原文注释。

以下情况会保守保留原文并记录原因，或要求准备正确输入：

- 只有 `.rpa` / `.rpyc`：本工具不提供资源解包、反编译或自动翻译。
- 三引号、实际跨行、原始字符串、单引号/反引号或带引号说话人：当前不会重写整个相关翻译块。
- 原文无法可靠配对：保留已有译文，不向后猜测其他台词，也不用菜单选项作为旁白原文。
- `translate ... strings`、Python 和样式块：复制保留，当前不会把菜单和设置全面转换成双语。
- 语言标识：使用 ASCII 字母、数字和下划线，开头不能是数字；不接受 `None` 和 Windows 保留目录名。
- 游戏和翻译版本不一致、自定义渲染或非常规脚本：不能仅凭构建成功判断运行兼容性。

## 构建报告与失败恢复

GUI 会显示逐文件进度和中文诊断，并为每次构建保存独立的 JSON 与 UTF-8 CSV 报告。
CSV 可用 Excel 打开，其中包含文件、行号、翻译块、原因和处理方式。

- `processed_statements`：生成双语的对白数量。
- `unmatched_statements`：缺少可靠原文、保持已有译文的数量。
- `skipped_already_bilingual`：识别为已生成双语而跳过的数量。
- `skipped_unsupported_blocks`：包含暂不支持语法、整块保留的数量。
- `language`：本次选定的翻译语言。

工具在临时目录完成构建后才替换输出。常见读写失败会保留或恢复上一版输出和报告；若恢复本身失败，错误信息会给出恢复文件所在位置。
构建期间需要容纳新旧两份输出的磁盘空间。这不保证断电或强制终止进程时的完整恢复。

部署会先完整暂存文件，再备份并安装；有对应 `.rpy` 时，不复制旧 `.rpyc`。空输出和危险的目标目录链接会被拒绝。

## 命令行

使用原文注释即可构建：

```bash
python tools/build_bilingual.py --src samples/demo/chinese --dst output/demo/tl/chinese --report-json output/reports/demo.json --report-csv output/reports/demo.csv
```

指定另一种语言，并可选提供原文目录：

```bash
python tools/build_bilingual.py --src samples/demo/spanish --src-original samples/demo/original --language spanish --dst output/demo/tl/spanish --report-json output/reports/spanish.json
```

`--language` 可省略：输入目录中只有一种翻译语言时自动识别；有多种语言时会提示明确选择。
stdout 是 JSON 摘要，逐文件进度写入 stderr，便于脚本调用。

## 已安装永恒世界旧双语补丁的用户

如果你已经使用本仓库修复了 `'/size' closes a text tag that isn't open`，本轮通用化没有改变那份游戏 UI 补丁，无需再次替换游戏文件。

如果仍在使用报错的旧补丁：完全退出游戏，将旧 `game/zz_bilingual_ui_patch.rpy` 和同名 `.rpyc` 备份到 `game` 外，然后复制 `patches/zz_bilingual_ui_patch.rpy` 到游戏，重启加载出错前存档。

用 GUI 重新安装时选择 **“永恒世界 0.9.5（中文排版修复）”**。通用模式发现旧的永恒世界 UI 补丁会提示处理，防止把专用界面误当成通用界面。

[永恒世界使用案例：旧版视频演示](https://www.bilibili.com/video/BV1bFREBqETU/)

## 开发与反馈

```bash
python -m unittest discover -s tests -v
```

测试覆盖通用语言和文件发现、文本解析、构建恢复、部署回滚、GUI 状态与报告校验。
缺少 Tk/customtkinter 时，GUI 测试会明确跳过。真实 Ren’Py 标签/布局测试见 [tests/README.md](tests/README.md)。

提交问题时，请说明游戏版本、Ren’Py 版本、翻译语言、系统版本，并提供错误最后几行或可共享的最小例子。
请不要在 Issue 中上传完整游戏、存档或无权分发的汉化包。
贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

本工具源码和原创演示使用 [MIT License](LICENSE)。第三方组件和游戏资源保留各自许可，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
