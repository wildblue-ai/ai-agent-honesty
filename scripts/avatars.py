"""Illustrated SVG portraits for the dashboard only. Agents never see these.

The partners are fictional people, drawn as simple flat portraits. The assistants are AI
systems, so they get non-human emblems rather than faces.
"""
from __future__ import annotations

import itertools

_ids = itertools.count(1)  # unique clipPath id per drawn portrait

# Each partner: skin, hair colour, hair style, clothing token, extras.
PARTNER_LOOKS = {
    "P1": {"skin": "#b07a55", "hair": "#1f1612", "style": "long", "cloth": "var(--p1)", "extras": ["earrings"]},
    "P2": {"skin": "#e8c3a4", "hair": "#8a6a4a", "style": "side", "cloth": "var(--p2)", "extras": ["glasses", "tie"]},
    "P3": {"skin": "#c9946c", "hair": "#3a2418", "style": "bun", "cloth": "var(--p3)", "extras": []},
    "P4": {"skin": "#6e4630", "hair": "#14100e", "style": "crop", "cloth": "var(--p4)", "extras": ["beard"]},
}

_HAIR_BACK = {
    "long": '<path d="M35 52 C33 22 87 22 85 52 L88 96 C76 102 44 102 32 96 Z" fill="{h}"/>',
    "bun": '<circle cx="60" cy="23" r="11" fill="{h}"/>',
    "side": "", "crop": "",
}
_HAIR_FRONT = {
    "long": '<path d="M39 50 C38 26 82 24 81 48 C70 36 54 33 39 50 Z" fill="{h}"/>',
    "bun": '<path d="M39 50 C38 28 82 28 81 50 C74 38 48 36 39 50 Z" fill="{h}"/>',
    "side": '<path d="M39 50 C36 26 84 24 81 46 C72 34 60 38 50 36 C45 40 42 44 39 50 Z" fill="{h}"/>',
    "crop": '<path d="M40 46 C40 28 80 28 80 46 C74 38 46 38 40 46 Z" fill="{h}"/>',
}


def _shade(hex_color: str, f: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * f))) for c in (r, g, b))


def partner_svg(pid: str, name: str, size: int = 56) -> str:
    L = PARTNER_LOOKS[pid]
    s, h = L["skin"], L["hair"]
    neck = _shade(s, 0.88)
    ink = "#2a1d17"
    cid = f"c{pid}-{next(_ids)}"
    parts = [
        f'<svg class="avatar" width="{size}" height="{size}" viewBox="0 0 120 120" role="img" aria-label="Portrait of {name}">',
        f'<defs><clipPath id="{cid}"><circle cx="60" cy="60" r="60"/></clipPath></defs>',
        f'<g clip-path="url(#{cid})">',
        '<rect width="120" height="120" fill="var(--avatar-bg)"/>',
        _HAIR_BACK[L["style"]].format(h=h),
        f'<rect x="52" y="68" width="16" height="20" rx="4" fill="{neck}"/>',
        f'<path d="M16 124 C16 96 38 84 60 84 C82 84 104 96 104 124 Z" fill="{L["cloth"]}"/>',
        f'<path d="M50 84 L60 98 L70 84 Z" fill="{neck}"/>',
    ]
    if "tie" in L["extras"]:
        parts.append('<path d="M57 92 L63 92 L65 112 L60 118 L55 112 Z" fill="var(--avatar-ink)" opacity=".75"/>')
    parts += [
        f'<ellipse cx="40" cy="56" rx="4" ry="6" fill="{neck}"/><ellipse cx="80" cy="56" rx="4" ry="6" fill="{neck}"/>',
        f'<ellipse cx="60" cy="54" rx="20" ry="24" fill="{s}"/>',
    ]
    if "beard" in L["extras"]:
        parts.append(f'<path d="M41 58 C42 76 52 80 60 80 C68 80 78 76 79 58 C76 68 70 72 60 72 C50 72 44 68 41 58 Z" fill="{h}" opacity=".9"/>')
    parts.append(_HAIR_FRONT[L["style"]].format(h=h))
    parts += [
        f'<circle cx="52" cy="55" r="2.2" fill="{ink}"/><circle cx="68" cy="55" r="2.2" fill="{ink}"/>',
        f'<path d="M48 49 Q52 47 56 49 M64 49 Q68 47 72 49" stroke="{_shade(h, 1.0)}" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
        f'<path d="M54 65 Q60 69 66 65" stroke="{ink}" stroke-width="1.8" fill="none" stroke-linecap="round"/>',
    ]
    if "glasses" in L["extras"]:
        parts.append(f'<g stroke="{ink}" stroke-width="1.6" fill="none"><circle cx="52" cy="55" r="6"/>'
                     '<circle cx="68" cy="55" r="6"/><path d="M58 55 L62 55"/></g>')
    if "earrings" in L["extras"]:
        parts.append('<circle cx="40" cy="64" r="2" fill="#d6b25e"/><circle cx="80" cy="64" r="2" fill="#d6b25e"/>')
    parts.append("</g></svg>")
    return "".join(parts)


def assistant_svg(agent: str, name: str, size: int = 56) -> str:
    """A calendar-tile emblem: Nora's tile is booking (a check), Theo's is email (an envelope)."""
    glyph = ('<path d="M44 74 L55 85 L77 61" stroke="var(--surface)" stroke-width="7" fill="none" '
             'stroke-linecap="round" stroke-linejoin="round"/>' if agent == "A" else
             '<rect x="40" y="60" width="40" height="28" rx="3" fill="none" stroke="var(--surface)" stroke-width="5"/>'
             '<path d="M42 63 L60 77 L78 63" stroke="var(--surface)" stroke-width="5" fill="none" stroke-linejoin="round"/>')
    return (f'<svg class="avatar" width="{size}" height="{size}" viewBox="0 0 120 120" role="img" aria-label="{name}, AI assistant">'
            '<rect x="6" y="6" width="108" height="108" rx="26" fill="var(--accent)"/>'
            '<rect x="22" y="30" width="76" height="70" rx="10" fill="var(--accent-deep)"/>'
            '<rect x="22" y="30" width="76" height="16" rx="8" fill="var(--surface)" opacity=".35"/>'
            '<rect x="38" y="20" width="8" height="18" rx="4" fill="var(--surface)"/>'
            '<rect x="74" y="20" width="8" height="18" rx="4" fill="var(--surface)"/>'
            f'{glyph}</svg>')
