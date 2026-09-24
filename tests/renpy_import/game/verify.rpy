# Original engine-level regression: the imported module must not load eagerly.
init -900 python:
    assert not renpy.has_label("optional_scene"), "Module loaded before load_module"

    def rbb_import_check():
        assert renpy.has_label("optional_scene"), "Explicit module load failed"
        translations = renpy.game.script.translator.language_translates
        for identifier, expected in (
            ("stable_welcome", "Hello from the original.\n原作中的你好。"),
            ("module_line", "An optional module line.\n可选模块中的一句话。"),
        ):
            node = translations[(identifier, "chinese")]
            actual = node.what if hasattr(node, "what") else node.block[0].what
            assert actual == expected, (identifier, actual)
        print("RBB_IMPORTED_RPA_MODULE_OK")
        return False

    renpy.arguments.register_command("rbb_import_check", rbb_import_check)
