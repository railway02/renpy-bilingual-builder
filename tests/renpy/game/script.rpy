# Headless regression command. See tests/README.md.
init -10 python:
    persistent.text_size = 32
    persistent.text_outline = 2
    persistent.textbox_width = 1400
    persistent.textbox_height = 350

init python:
    def _rbb_test_effect(tag, argument, contents):
        # Minimal reproduction of Eternum's DispTextStyle: an effect consumes
        # style tags inside it and emits displayables instead of outer tags.
        styles = {}
        result = []
        for kind, value in contents:
            if kind == renpy.TEXT_TAG:
                name, _, arg = value.partition("=")
                if name in ("b", "i", "size"):
                    styles[name] = arg
                    continue
                if name in ("/b", "/i", "/size"):
                    styles.pop(name[1:])
                    continue
            result.append((kind, value))
        return result

    # A runner may copy the game's actual effects.rpy for integration tests.
    if "sc" not in config.custom_text_tags:
        config.custom_text_tags["sc"] = _rbb_test_effect
        config.custom_text_tags["bt"] = _rbb_test_effect

    def _rbb_test_layout(s):
        text = Text(s, substitute=False)
        text.update()
        # Exercise Ren'Py's real tag expansion and Layout.segment without a
        # window/GPU. Effect displayables get placeholder dimensions here.
        renders = {d: renpy.Render(1, 1) for d in text.displayables}
        renpy.text.text.Layout(text, 1600, 500, renders, drawable_res=False, size_only=True)

    def rbb_smoke():
        cases = [
            "{sc=2}THE PERFECT HOST.\n{b}完美的宿主。{/sc}",
            "{sc=2}I can create the PERFECT ORGANISM!\n我马上就能创造出{b}完美的生物{/b}！{/sc}",
        ]
        reproduced = 0
        for s in cases:
            en, cn = s.split("\n", 1)
            old = en + "\n{vspace=6}{size=26}" + cn + "{/size}"
            try:
                _rbb_test_layout(old)
            except Exception as error:
                assert "closes a text tag that isn't open" in str(error), str(error)
                reproduced += 1
            else:
                raise AssertionError("Old formatter should reproduce the reported failure")
            fixed = format_bilingual_text(s)
            assert fixed == s
            _rbb_test_layout(fixed)

        special = [
            "Hello\n{sc=2}中文",
            "{bt=3}Hello\n中文{/bt}",
            "{i}Hello\n中文",
            "Hello\n{b}中文",
            "{color=#fff}Hello\n中文{/color}",
        ]
        for s in special:
            assert format_bilingual_text(s) == s
            _rbb_test_layout(format_bilingual_text(s))

        for s in ["Hello\n中文", "{b}Hello{/b}\n{b}中文{/b}", "{{sc=2}literal\n中文"]:
            fixed = format_bilingual_text(s)
            assert "{size=26}" in fixed
            _rbb_test_layout(fixed)
        assert format_bilingual_text("  unchanged  ") == "  unchanged  "
        assert format_bilingual_text("Hello\n") == "Hello\n"
        assert format_bilingual_text("English\ncontinued\n中文") == "English\ncontinued\n中文"
        assert not _rbb_can_wrap_text("{size=30}{b}bad nesting{/size}{/b}")
        assert not _rbb_can_wrap_text("{unknown}text{/unknown}")
        persistent.text_size = None
        assert format_bilingual_text("Hello\n中文") == "Hello\n中文"
        persistent.text_size = 32
        print("RBB_SMOKE_OK: %d original crashes reproduced; 16 regression checks passed" % reproduced)
        return False

    renpy.arguments.register_command("rbb_smoke", rbb_smoke)
