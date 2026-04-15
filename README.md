# renpy-bilingual-builder

A standalone workspace for building bilingual Ren'Py translation files.

## Structure

- `tools/`: build and helper scripts
- `patches/`: optional UI patch files
- `samples/`: demo input/output samples
- `input/`: source folders (`chinese_tl`, `original_english`)
- `output/`: generated outputs
- `unresolved/`: unresolved alignment artifacts

## Quick Start

```bash
python tools/build_bilingual_v2.py --src input/chinese_tl --dst output/tl/chinese --report-json output/build_report_v2.json
```
