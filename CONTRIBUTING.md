# 开发说明

## 从源码启动

需要 Python 3.10 或更高版本，并带有 Tk。

Windows 运行 `start_windows.bat`；Linux/macOS 运行 `sh start.sh`。启动脚本会创建虚拟环境并安装依赖。

也可以使用自己的 Python 环境：

```bash
python -m pip install -r requirements.txt
python app/gui.py
```

## 命令行构建

命令行处理已有的 `.rpy/.rpym` 翻译目录；RPA 和编译脚本导入使用桌面界面。

```bash
python tools/build_bilingual.py --src samples/demo/chinese --dst output/demo --report-json output/report.json
```

用 `--language` 指定语言，用 `--src-original` 补充原文目录；更多选项见 `--help`。

## 测试与打包

```bash
python -m unittest discover -s tests -v
```

[测试说明](tests/README.md) · [Windows 便携版打包](packaging/README.md)

## 提交改动

描述用户遇到的问题、修改后的行为和已完成的验证。解析或安装逻辑的改动，请附最小原创样例及相应测试。

不要提交完整游戏、汉化资源、存档、个人配置或生成的安装包。测试、内置示例、第三方库及许可证属于项目必要内容。
