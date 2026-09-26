# Ren’Py 双语工具

把 Ren’Py 游戏已有的汉化与原文合并，在游戏中同时显示两种语言。

**[下载 Windows 便携版](https://github.com/railway02/renpy-bilingual-builder/releases/latest/download/RenPy-Bilingual-Builder-windows-x64.zip)** · [版本发布](https://github.com/railway02/renpy-bilingual-builder/releases)

适用于 Windows 10/11 64 位。完整解压 ZIP 后双击 `RenPy双语工具.exe`，无需安装 Python。

<img src="samples/screenshots/tool_gui.png" alt="工具界面" width="760">

## 使用

1. **选择游戏／汉化**：选择游戏目录；汉化单独存放时，再选择汉化包或文件夹。
2. **检查并生成双语**：工具自动读取脚本、匹配原文。有多个汉化或语言时，选择需要的一项。
3. **备份并安装**：关闭游戏后安装，再进入游戏选择对应语言。

没有游戏也可以点击“试用内置示例”。输出位置和游戏配置在“更多选项”中。

默认使用通用模式。永恒世界 0.9.5 中文用户可选择专用排版配置。

## 支持范围

支持标准 RPA 2/3、RPY、RPYC、RPYM 和 RPYMC。自动解包和恢复脚本，无需手动寻找原文目录。

本工具使用已有译文，不提供自动翻译。无法可靠匹配的对白会保留译文并报告；加密、混淆或非标准汉化可能无法处理。

安装会备份原文件，原 RPA 保持不变。备份位于游戏 `game` 目录同级的 `renpy_bilingual_backups`。

## 反馈与开发

遇到问题可在 [Issues](https://github.com/railway02/renpy-bilingual-builder/issues) 反馈，附上游戏版本、错误信息和工具日志。

[开发说明](CONTRIBUTING.md) · [Windows 打包](packaging/README.md) · [MIT 许可证](LICENSE) · [第三方许可](THIRD_PARTY_NOTICES.md)
