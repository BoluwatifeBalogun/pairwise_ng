from pathlib import Path

from django.conf import settings
from django.templatetags.static import static

_logo = None


def logo_url():
    """static/img/logo.svg or logo.png, if one has been added; otherwise None and the
    wordmark is shown instead."""
    global _logo
    if _logo is None:
        _logo = ""
        for name in ("logo.svg", "logo.png"):
            if (Path(settings.BASE_DIR) / "static" / "img" / name).exists():
                _logo = static("img/" + name)
                break
    return _logo or None


def site(request):
    return {"SITE_NAME": settings.SITE_NAME, "INSTITUTION_NAME": settings.INSTITUTION_NAME,
            "INSTITUTION_SHORT": settings.INSTITUTION_SHORT, "LOGO_URL": logo_url(),
            "DEMO_MODE": settings.DEMO_MODE}
