import math


TEXT_LIMITS = {
    "project_name": 255,
    "project_type": 100,
    "sector": 100,
}
MAX_TAGS = 20
MAX_TAG_LENGTH = 50


class ValidationError(ValueError):
    def __init__(self, errors):
        """Store field errors and combine them into the exception message."""
        self.errors = errors
        message = "; ".join(f"{field}: {error}" for field, error in errors.items())
        super().__init__(message)


def normalize_project_name(value):
    """Trim and normalize a project name, treating missing values as empty."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if str(value).strip().lower() in {"nan", "none"}:
        return ""
    return " ".join(str(value or "").split())


def project_identity(value):
    """Return the case-insensitive form used to compare project names."""
    return normalize_project_name(value).casefold()


def parse_tags(value):
    """Convert tags into a cleaned, unique list while enforcing tag limits."""
    if value is None or value == "" or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, str):
        if value.strip().lower() in {"nan", "none"}:
            return []
        raw_tags = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw_tags = value
    else:
        raise ValueError("tags must be a comma-separated string or list")

    tags = []
    seen = set()
    for raw_tag in raw_tags:
        tag = " ".join(str(raw_tag).split())
        if not tag:
            raise ValueError("tags cannot contain blank entries")
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"each tag must be {MAX_TAG_LENGTH} characters or fewer")
        if any(ord(character) < 32 for character in tag):
            raise ValueError("tags cannot contain control characters")
        identity = tag.casefold()
        if identity not in seen:
            tags.append(tag)
            seen.add(identity)
    if len(tags) > MAX_TAGS:
        raise ValueError(f"a project can have at most {MAX_TAGS} tags")
    return tags


def parse_bool(value, field):
    """Convert a yes-or-no value into a Boolean or raise a field-specific error."""
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"y", "yes", "true", "1", "1.0"}:
        return True
    if normalized in {"n", "no", "false", "0", "0.0"}:
        return False
    raise ValueError(f"{field} must be yes or no")


def validate_project(values):
    """Validate and normalize all fields needed to save a project."""
    errors = {}
    normalized = dict(values)
    try:
        normalized["tags"] = parse_tags(values.get("tags", []))
    except ValueError as exc:
        errors["tags"] = str(exc)

    for field, limit in TEXT_LIMITS.items():
        value = normalize_project_name(values.get(field))
        if not value:
            errors[field] = "is required"
        elif len(value) > limit:
            errors[field] = f"must be {limit} characters or fewer"
        normalized[field] = value

    integer_fields = {
        "sqft": (1, None),
        "levels": (1, None),
        "partition_density": (0, None),
        "site_condition": (1, 3),
        "scan_count": (1, None),
    }
    for field, (minimum, maximum) in integer_fields.items():
        try:
            raw_value = values.get(field)
            if isinstance(raw_value, bool) or float(raw_value) != int(float(raw_value)):
                raise ValueError
            value = int(raw_value)
            if value < minimum or (maximum is not None and value > maximum):
                raise ValueError
            normalized[field] = value
        except (TypeError, ValueError, OverflowError):
            errors[field] = "must be a valid whole number in the allowed range"

    try:
        coverage = float(values.get("coverage"))
        if not math.isfinite(coverage) or not 0 <= coverage <= 1:
            raise ValueError
        normalized["coverage"] = coverage
    except (TypeError, ValueError, OverflowError):
        errors["coverage"] = "must be a finite number between 0 and 1"

    for field in ("interior", "exterior", "roof"):
        try:
            normalized[field] = "y" if parse_bool(values.get(field), field) else "n"
        except ValueError as exc:
            errors[field] = str(exc)

    if errors:
        raise ValidationError(errors)
    return normalized


def validate_prediction(values):
    """Validate prediction inputs by applying the fields that are not entered by users."""
    project_values = dict(values)
    project_values["project_name"] = "prediction"
    project_values["scan_count"] = 1
    return validate_project(project_values)
