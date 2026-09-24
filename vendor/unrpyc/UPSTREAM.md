# unrpyc decompiler library

Source: https://github.com/CensoredUsername/unrpyc
Commit: `3ae8334ed71a05535927dcc559663d3aca51215b`
License: MIT (see LICENSE and per-file headers).

Only the decompiler library is vendored, unmodified. No injectors, game launcher,
deobfuscation routines or command-line driver are included. The application uses
its own restricted unpickler, size limits, subprocess timeout, and rejects unknown
nodes or decompiler warnings instead of publishing placeholder scripts.
