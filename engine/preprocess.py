"""Data validation and text preprocessing (application layer, Figure 3.1)."""
import re

MIN_INTEREST_CHARS = 20
MIN_INTEREST_WORDS = 4
DEFAULT_MATRIC_PATTERN = r"^[A-Z0-9][A-Z0-9/\-.]{4,24}$"


def clean_text(text):
    """Collapse whitespace and strip control characters before encoding."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def normalise_matric(matric):
    return re.sub(r"\s+", "", (matric or "")).upper()


def matric_error(matric, pattern=None):
    m = normalise_matric(matric)
    if not re.match(pattern or DEFAULT_MATRIC_PATTERN, m):
        return "Matric number is not in this department's format."
    return None


def cgpa_error(cgpa, scale):
    try:
        v = float(cgpa)
    except (TypeError, ValueError):
        return "CGPA must be a number."
    if not 0.0 <= v <= float(scale):
        return f"CGPA must be between 0.00 and {float(scale):.2f}."
    return None


def interest_error(text):
    t = clean_text(text)
    if len(t) < MIN_INTEREST_CHARS or len(t.split()) < MIN_INTEREST_WORDS:
        return ("Describe your interest in at least a few words (20 characters or more) "
                "so the model has enough meaning to work with.")
    return None


def project_text(title, keywords="", abstract=""):
    """The text of a past project as given to the model: title, keywords, abstract."""
    parts = [clean_text(title)]
    if clean_text(keywords):
        parts.append(clean_text(keywords))
    if clean_text(abstract):
        parts.append(clean_text(abstract))
    return ". ".join(parts)
