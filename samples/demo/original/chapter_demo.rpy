# Original demo written for Ren'Py Bilingual Builder; no game assets required.
define guide = Character("Guide")
default player_name = "Player"

label start:
    guide "Welcome, [player_name]!" id demo_welcome
    "This is a short example of narration." id demo_narration
    guide "You can keep {b}emphasis{/b} in both languages." id demo_format
    guide "The first line.\nThe second line." id demo_multiline
    return
