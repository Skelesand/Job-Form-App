import math


TEXT_LIMITS = {
    "project_name": 255,
    "project_type": 100,
    "sector": 100,
}


class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        message = "; ".join(f"{field}: {error}" for field, error in errors.items())
        super().__init__(message)


def normalize_project_name(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if str(value).strip().lower() in {"nan", "none"}:
        return ""
    return " ".join(str(value or "").split())


def project_identity(value):
    return normalize_project_name(value).casefold()


def parse_bool(value, field):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"y", "yes", "true", "1", "1.0"}:
        return True
    if normalized in {"n", "no", "false", "0", "0.0"}:
        return False
    raise ValueError(f"{field} must be yes or no")


def validate_project(values):
    errors = {}
    normalized = dict(values)

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
    project_values = dict(values)
    project_values["project_name"] = "prediction"
    project_values["scan_count"] = 1
    return validate_project(project_values)
