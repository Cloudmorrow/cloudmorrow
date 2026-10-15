"""`python -m cloudmorrow.icons check` says what is wrong with the library;
`python -m cloudmorrow.icons sheet out.html` writes a contact sheet to look at."""

from __future__ import annotations

import sys
from pathlib import Path

from cloudmorrow.icons import check, icons, svg, themes

STYLE = """
body { background: #15171d; color: #d8a85b; font: 13px/1.4 system-ui, sans-serif; margin: 24px; }
h1, h2 { color: #c9d2e3; font-weight: 600; } h2 { margin-top: 36px; }
p { color: #8a93a6; }
.grid { display: flex; flex-wrap: wrap; gap: 18px; }
figure { margin: 0; width: 72px; text-align: center; }
svg { width: 48px; height: 48px; display: block; margin: 0 auto 6px; }
.small svg { width: 20px; height: 20px; }
figcaption { color: #8a93a6; font-size: 11px; word-break: break-all; }
"""


def sheet(out: Path) -> None:
    parts = [f"<!doctype html><meta charset=utf-8><title>Icons</title><style>{STYLE}</style><h1>The icon library</h1>"]
    found = icons()
    for theme in themes():
        mine = [i for i in found.values() if i.theme == theme["id"]]
        parts.append(f"<h2>{theme['name']} · {len(mine)}</h2><p>{theme['description']}</p><div class=grid>")
        parts += [f"<figure>{svg(i.rows)}<figcaption>{i.id}</figcaption></figure>" for i in mine]
        parts.append("</div><div class='grid small'>")
        parts += [f"<figure>{svg(i.rows)}</figure>" for i in mine]
        parts.append("</div>")
    out.write_text("\n".join(parts), encoding="utf-8")


def main(argv: list[str]) -> int:
    if argv[:1] == ["check"]:
        problems = check()
        print("\n".join(problems) if problems else f"{len(icons())} icons in {len(themes())} themes check out")
        return 1 if problems else 0
    if argv[:1] == ["sheet"] and len(argv) == 2:
        sheet(Path(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
