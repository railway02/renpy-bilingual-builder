# 回归验证

构建、解析和部署测试只用 Python 标准库。GUI 状态测试需要安装
`requirements.txt` 中的依赖，但不需要打开图形窗口；缺少 Tk/customtkinter 时会明确跳过：

```bash
python -m unittest discover -s tests -v
```

测试包含构建中断、资源复制失败、报告写入失败、部署回滚、目标符号链接、输出路径
变更、报告真实性检查和不支持的文本语法。构建的失败恢复测试还会验证原文件仍被保留。

Ren'Py 测试使用 8.3.2（与 Eternum 0.9.5 的报错环境一致）。复制到临时目录，避免在仓库里生成编译缓存：

```bash
cp -r tests/renpy /tmp/rbb-renpy-test
cp patches/zz_bilingual_ui_patch.rpy /tmp/rbb-renpy-test/game/
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy /path/to/renpy-8.3.2-sdk/renpy.sh /tmp/rbb-renpy-test rbb_smoke
```

预期输出 `RBB_SMOKE_OK`。测试先确认两条用户提供的台词在旧格式化逻辑下触发 `/size` 异常，再验证新逻辑、普通双语、未闭合样式、字符转义等。

该测试调用真实引擎的文本标签处理和文本布局，为特效显示对象提供占位尺寸，因此不验证画面、动画或剧情流程。默认附带最小特效处理器；如需使用已有游戏脚本验证，可另将游戏原始 `text.rpy` 复制为临时项目的 `game/effects.rpy`。无需提交或分发游戏脚本。
