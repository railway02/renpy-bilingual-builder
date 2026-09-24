# Third-party components and game data

Ren'Py Bilingual Builder's code is distributed under the [MIT license](LICENSE).

The desktop interface depends on [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
and its dependencies, which keep their own licenses. Python and Tcl/Tk likewise
retain their respective licenses. The source launcher installs these packages.
The Windows portable distribution bundles CPython, Tcl/Tk, CustomTkinter,
darkdetect, packaging and Pillow. Their license texts are included under
`运行依赖文件/licenses/` and in the corresponding package metadata directories.
CustomTkinter's Roboto fonts retain their Apache 2.0 license, copied from the
[upstream font repository](https://github.com/googlefonts/roboto/blob/main/LICENSE)
in `packaging/licenses/Roboto-LICENSE.txt`. Its shapes font and themes are included
with CustomTkinter under its MIT license. Windows system fonts are not redistributed.
PyInstaller is used for packaging with its
[bootloader distribution exception](https://pyinstaller.org/en/stable/license.html);
this does not change the application's MIT license.

The compiled-script reader includes the unmodified MIT-licensed decompiler library
from [unrpyc](https://github.com/CensoredUsername/unrpyc), pinned to commit
`3ae8334ed71a05535927dcc559663d3aca51215b`. Its license and provenance are under
`vendor/unrpyc/` in source distributions and `运行依赖文件/licenses/unrpyc/` in the
portable package. Injectors, deobfuscators and the upstream CLI are not included.
The application implements its own restricted object loader and process wrapper.
Original compiled fixtures under `tests/fixtures/import_game/` were written for this
project, are MIT-licensed, and are also bundled for executable verification.

Ren'Py itself is not included. See the engine's
[license documentation](https://www.renpy.org/doc/html/license.html) when using or
redistributing it separately.

User-provided translations, game scripts, images, fonts, audio, archives, saves,
and generated bilingual patches are not covered by this repository's MIT license.
Their rights remain with their respective authors. This repository's language
examples under `samples/demo/` were written specifically for this tool and are
covered by its MIT license.

Legacy Eternum screenshots illustrate an existing game integration; the game's
artwork remains the property of its respective rights holders. They are not
required by the tool, tests, or synthetic demo.
