# Windows 便携包维护说明

用户只需解压 ZIP 并双击 EXE。以下步骤仅用于维护者生成发布产物。

在 Windows 10/11 x64 上使用 python.org 的 CPython 3.13（包含 Tcl/Tk）：

```powershell
py -3.13 -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements-build.txt
.venv-build\Scripts\python -m unittest discover -s tests -v
.venv-build\Scripts\python tools/package_windows.py
.venv-build\Scripts\python tools/smoke_windows_bundle.py dist/RenPy-Bilingual-Builder-windows-x64.zip
```

产物：`dist/RenPy-Bilingual-Builder-windows-x64.zip` 及 `.zip.sha256`。
目录式 PyInstaller 配置在 `windows.spec`，支持文件目录固定为 `运行依赖文件`。
脚本拒绝在 Linux 或非 x64 Python 中打包，避免产生错误平台的产物。
构建依赖固定于 `requirements-build.txt`；实际 Python 和依赖版本随包写入 `build-info.json`。
Python、组件与字体许可证随包保存；不会打包游戏截图、用户游戏或输出文件。

自动验收会解压 ZIP 到中文和空格路径，切换到其他工作目录，从 PATH 中移除 Python，
清除 Python/Tcl 环境变量，然后运行真正的窗口版 EXE。它会创建 CustomTkinter 窗口、
加载内置示例、使用 GUI 后台线程生成 4 条双语对白，检查报告、日志和示例部署禁用，
并验证程序目录的文件列表及内容完全未被写入。失败时进程返回非零退出码。
随后用真实 Ren'Py 8.3.2 编译的原创小型样例生成 RPA 包，走普通界面自动导入、
EXE 内置反编译辅助进程和生成流程，验证 3 条按标识匹配的双语对白、1 条未匹配译文、
RPYM 模块扩展名和字体依赖，并安装到临时测试游戏验证备份以及 RPA 未被修改。
最后再尝试完全缺少原文的包，验证失败报告包含位置、安装保持禁用、上一份输出和原 RPA 保持原样。
`--smoke-test <result.json>` 是维护者验收入口，普通用户无需使用。

CI 在 `.github/workflows/windows-portable.yml` 中执行同样流程，只上传通过检查的 ZIP。
此工作流不会自动发布 GitHub Release。试用包未签名；发行前可另行配置签名。
还应在未安装 Python 的 Windows 10 和 Windows 11 桌面分别做人工双击验收，
检查目录选择、系统缩放、文件关联打开、真实游戏显示和恢复流程。

实现参考：[PyInstaller 资源路径](https://pyinstaller.org/en/stable/runtime-information.html)、
[PyInstaller spec](https://pyinstaller.org/en/stable/spec-files.html)、
[CustomTkinter 打包说明](https://github.com/TomSchimansky/CustomTkinter/wiki/Packaging)。

输入格式参考：[Ren'Py archive loader](https://github.com/renpy/renpy/blob/master/renpy/loader.py)、
[翻译标识](https://www.renpy.org/doc/html/translation.html)、
[模块加载](https://www.renpy.org/doc/html/other.html#renpy.load_module)、
[unrpyc 上游](https://github.com/CensoredUsername/unrpyc)。
