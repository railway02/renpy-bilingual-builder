init -2 python:
    def _rbb_can_wrap_text(s):
        # Character.what_prefix/what_suffix are already part of `what` here.
        # Custom tags consume their contents before normal text layout. A size
        # opener inside {sc} and its closer outside {/sc} therefore cannot pair.
        # Only wrap independently balanced, built-in formatting on each side.
        stack = []
        paired = {"b", "i", "u", "s", "plain", "font", "color",
                  "outlinecolor", "size", "alpha", "k", "cps", "a",
                  "alt", "noalt", "rt", "rb", "art"}
        single = {"w", "p", "nw", "fast", "done", "space", "vspace", "image"}
        try:
            tokens = renpy.text.textsupport.tokenize(s)
        except Exception:
            return False
        for kind, value in tokens:
            if kind != renpy.TEXT_TAG:
                continue
            if value.startswith("#"):
                continue
            name = value.partition("=")[0]
            bare = name.lstrip("/")
            if (bare in renpy.config.custom_text_tags or
                    bare in renpy.config.self_closing_custom_text_tags):
                return False
            if name.startswith("/"):
                if not stack or stack.pop() != bare:
                    return False
            elif name in paired:
                stack.append(name)
            elif name not in single:
                return False
        return not stack

    def format_bilingual_text(s, cn_scale=0.84, gap=6):
        if not s:
            return ""

        # 单语和有自然换行的多行台词：直接返回
        if s.count("\n") != 1:
            return s

        # 双语：第一行英文，第二行中文
        en, cn = s.split("\n", 1)
        if not cn or not (_rbb_can_wrap_text(en) and _rbb_can_wrap_text(cn)):
            # Keep both languages and the game's effects, without adding tags
            # across a custom tag or a Character's formatting boundary.
            return s

        try:
            cn_size = max(12, int(persistent.text_size * cn_scale))
        except (TypeError, ValueError, OverflowError):
            return s

        # 一个 text 控件内完成双语排版
        # 英文保持原样；中文缩小一点，但颜色和描边沿用原英文样式
        return "{}\n{{vspace={}}}{{size={}}}{}{{/size}}".format(
            en, gap, cn_size, cn
        )


screen say(who, what):
    style_prefix "say"

    $ processed_what = format_bilingual_text(what)
    $ extra_h = 56

    window:
        id "window"

        if persistent.quick_menu:
            ypos config.screen_height - persistent.textbox_height - extra_h - 32
        else:
            ypos config.screen_height - persistent.textbox_height - extra_h

        xsize persistent.textbox_width + 274
        ysize persistent.textbox_height + extra_h
        background Transform("gui/textbox.png", alpha=persistent.textbox_opacity)

        vbox:
            xpos gui.name_xpos
            ypos 40
            xsize persistent.textbox_width
            spacing 4

            if who is not None:
                window:
                    id "namebox"
                    style "namebox"
                    text who id "who"

            text processed_what id "what":
                style "say_dialogue"
                size persistent.text_size
                line_spacing 1
                outlines [ (absolute(persistent.text_outline), "#000", absolute(0), absolute(0)) ]


screen multiple_say(who, what, multiple):
    style_prefix "say"

    $ processed_what = format_bilingual_text(what)
    $ extra_h = 56

    window:
        id "window"

        if persistent.quick_menu:
            ypos config.screen_height - (persistent.textbox_height * multiple[0]) - extra_h - 32
        else:
            ypos config.screen_height - (persistent.textbox_height * multiple[0]) - extra_h

        xsize persistent.textbox_width + 274
        ysize persistent.textbox_height + extra_h
        background Transform("gui/textbox.png", alpha=persistent.textbox_opacity)

        vbox:
            xpos gui.name_xpos
            ypos 40
            xsize persistent.textbox_width
            spacing 4

            if who is not None:
                window:
                    id "namebox"
                    style "namebox"
                    text who id "who"

            text processed_what id "what":
                style "say_dialogue"
                size persistent.text_size
                line_spacing 1
                outlines [ (absolute(persistent.text_outline), "#000", absolute(0), absolute(0)) ]
