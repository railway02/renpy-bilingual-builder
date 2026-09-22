# 参与开发

欢迎通过 Issue 提供可复现问题，或通过 Pull Request 改进工具。请先阅读
[README](README.md) 中的适用范围和启动说明。

## 本地运行

需要 Python 3.10 或更高版本。Windows 可双击 `start_windows.bat`；Linux/macOS
可在项目目录运行 `sh start.sh`。启动脚本会创建本地 `.venv`，安装
`requirements.txt` 中的依赖并启动界面。失效的旧虚拟环境会保存在
`.venv.backup-*`，正常运行后可以自行删除该备份。

也可以手动创建环境，直接调用其中的 Python，无需激活脚本：

```bash
python -m venv .venv
# Linux/macOS
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app/gui.py
```

```powershell
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app\gui.py
```

虚拟环境不能作为可移植的程序目录分发；重新下载或移动项目后可以重建环境。
详见 [Python venv 文档](https://docs.python.org/3/library/venv.html)。

## 验证改动

在项目根目录运行，使用上面虚拟环境中的 Python：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python .github/workflows/smoke_launchers.py
```

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe .github\workflows\smoke_launchers.py
```

构建和部署测试使用临时目录与虚构脚本，不需要任何商业游戏文件。GUI 状态测试
不打开窗口，但需要 Tk 和 `customtkinter`；本地缺少它们时测试会明确跳过，
CI 会先确认依赖可导入。启动脚本测试在独立临时项目中运行，使用空依赖列表和
替代入口，验证环境创建、复用、失效环境备份和错误退出，不验证实际窗口布局。

CI 在 Linux、Windows 上使用 Python 3.10 和 3.13 运行以上检查。
真实 Ren'Py 文本布局验证的可选步骤见 [tests/README.md](tests/README.md)。
涉及文本标签或游戏内补丁的改动，请说明使用的引擎版本和验证范围。

## 提交内容

- 对解析或匹配规则的修复，提供几行虚构输入及预期结果，补充能复现问题的测试。
- 对构建或部署的修复，检查失败时旧文件仍能恢复，避免在游戏目录内保留可执行备份。
- 对界面改动，说明使用者看到的行为；适用时附截图。
- PR 描述写明修复的问题、最终行为和已运行的验证；未完成的游戏实测请如实说明。

请只提交工具代码、文档和自行编写的最小样例。不要提交完整游戏、汉化资源、
存档、生成的补丁包、个人配置、构建输出或虚拟环境。报告问题时可以隐去本机
用户名和私人目录路径。

当前采用源码运行方式。CI 只验证代码，不自动生成安装程序、不上传游戏资源，
也不自动发布 Release。
