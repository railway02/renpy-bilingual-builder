init -2 python:
    def format_bilingual_text(s, cn_scale=0.84, gap=6):
        if not s:
            return ""

        s = s.strip()

        # 单语：直接返回
        if "\n" not in s:
            return s

        # 双语：第一行英文，第二行中文
        en, cn = s.split("\n", 1)
        en = en.strip()
        cn = cn.strip()

        if not cn:
            return en

        cn_size = max(12, int(persistent.text_size * cn_scale))

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