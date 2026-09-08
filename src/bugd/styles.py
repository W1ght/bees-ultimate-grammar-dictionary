"""Card CSS shipped as the dictionary's `styles.css`.

Yomitan renders dictionary glossaries inside a shadow root, so base design tokens
are defined on this dictionary's own preserved wrapper rather than only on
`:root`. Selectors are scoped to this dictionary's `data-sc-*` markers so the
stylesheet cannot restyle Yomitan or another dictionary's entries.
"""

from __future__ import annotations

from .banks import CARD_ROOT_ROLE

STYLES_CSS = f"""\
[data-sc-{CARD_ROOT_ROLE}] {{
  --bugd-gap: 0.35em;
  --bugd-muted: rgba(0, 0, 0, 0.62);
  --bugd-rule: rgba(0, 0, 0, 0.16);
  display: flow-root;
  line-height: 1.5;
}}

@media (prefers-color-scheme: dark) {{
  [data-sc-{CARD_ROOT_ROLE}] {{
    --bugd-muted: rgba(255, 255, 255, 0.68);
    --bugd-rule: rgba(255, 255, 255, 0.24);
  }}
}}

@media (forced-colors: active) {{
  [data-sc-{CARD_ROOT_ROLE}] {{
    --bugd-muted: CanvasText;
    --bugd-rule: CanvasText;
  }}
}}
"""


__all__ = ["STYLES_CSS"]
