from pathlib import Path

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()
_icons = {}


@register.simple_tag
def icon(name, size=18):
    """Inline a Lucide icon (decorative: hidden from assistive technology)."""
    if name not in _icons:
        p = Path(settings.BASE_DIR) / "static" / "icons" / f"{name}.svg"
        svg = p.read_text() if p.exists() else ""
        start = svg.find(">", svg.find("<svg")) + 1
        _icons[name] = svg[start:svg.rfind("</svg>")].strip()
    return mark_safe(
        f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{_icons[name]}</svg>')


@register.filter
def score(v):
    return "" if v is None else f"{float(v):.2f}"


@register.filter
def pct(v):
    """Fit score to bar width (cosine 0..1 mapped to 0..100)."""
    try:
        return max(2, min(100, round(float(v) * 100)))
    except (TypeError, ValueError):
        return 0


@register.filter
def percent(v):
    return "to be filled" if v is None else f"{float(v) * 100:.1f}%"


@register.filter
def get(d, key):
    return d.get(key)
