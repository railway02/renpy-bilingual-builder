define guide = Character("Guide")
init python:
    renpy.load_module("extras/optional")
label start:
    guide "Hello from the original." id stable_welcome
    guide "Another original line." id stable_second
    return
