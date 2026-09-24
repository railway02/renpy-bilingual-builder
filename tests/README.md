# 回归验证

构建、解析和部署测试只用 Python 标准库。GUI 状态测试需要安装
`requirements.txt` 中的依赖，但不需要打开图形窗口；缺少 Tk/customtkinter 时会明确跳过：

```bash
python -m unittest discover -s tests -v
```

测试包含构建中断、资源复制失败、报告写入失败、部署回滚、目标符号链接、输出路径
变更、报告真实性检查和不支持的文本语法。构建的失败恢复测试还会验证原文件仍被保留。

便携版还覆盖直接调用构建核心、队列状态、任务中关闭保护、资源与输出隔离、可写目录
回退和 UTF-8 错误日志。Windows 最终 ZIP 的验收命令：

```powershell
python tools/smoke_windows_bundle.py dist/RenPy-Bilingual-Builder-windows-x64.zip
```

该测试运行打包后的 EXE，验证中文/空格路径、不同启动目录、PATH 中没有 Python、
主题/字体/补丁/示例资源、4 条双语输出、JSON/CSV 报告、日志及程序目录未被改写。
详细打包步骤见 [packaging/README.md](../packaging/README.md)。

导入测试使用原创的真实 Ren'Py 8.3.2 编译样例，覆盖 RPA2/3、恶意 pickle、路径穿越、
无英文注释按 ID 匹配、来源隔离、字体依赖、RPYM、零转换失败、多个候选和安装回滚。
可选的真实引擎集成验证：

```bash
python tools/smoke_renpy_import.py --renpy /path/to/renpy-8.3.2-sdk/renpy.sh
```

它只构造临时的原创测试游戏，走 RPA 导入、反编译、构建和安装，随后启动测试引擎。
预期 `RBB_IMPORTED_RPA_MODULE_OK`：生成的 RPYM 未自动加载，显式 load_module 后模块
可用，普通对白与模块对白的双语内容都正确。产品的导入阶段本身从不调用引擎。

Ren'Py 测试使用 8.3.2（与 Eternum 0.9.5 的报错环境一致）。复制到临时目录，避免在仓库里生成编译缓存：

```bash
cp -r tests/renpy /tmp/rbb-renpy-test
cp patches/zz_bilingual_ui_patch.rpy /tmp/rbb-renpy-test/game/
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy /path/to/renpy-8.3.2-sdk/renpy.sh /tmp/rbb-renpy-test rbb_smoke
```

预期输出 `RBB_SMOKE_OK`。测试先确认两条用户提供的台词在旧格式化逻辑下触发 `/size` 异常，再验证新逻辑、普通双语、未闭合样式、字符转义等。

该测试调用真实引擎的文本标签处理和文本布局，为特效显示对象提供占位尺寸，因此不验证画面、动画或剧情流程。默认附带最小特效处理器；如需使用已有游戏脚本验证，可另将游戏原始 `text.rpy` 复制为临时项目的 `game/effects.rpy`。无需提交或分发游戏脚本。
