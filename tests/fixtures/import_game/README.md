# Original compiled fixtures

Original MIT-licensed dialogue written for this project, compiled with Ren'Py
8.3.2 using `renpy.sh <temporary project> compile`. The `.bin` files contain actual
RPYC2 slot 1/2 data; they are not game assets. Copies of the input sources are here
for review. `module.rpym` was loaded by the synthetic project's init to create its
RPYMC; the application never invokes this init during import.

`translation.rpy` intentionally has no original comments and has one unknown ID.
The original and translation filenames differ. Tests check that slot 2 IDs, not
decompiled line numbers or neighbouring statements, recover the original text.
