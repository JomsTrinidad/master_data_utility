from django import template
import json

register = template.Library()


@register.filter
def in_group(user, group_name: str) -> bool:
    """Template helper: {% if request.user|in_group:'approver' %}."""
    try:
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
    except Exception:
        return False

@register.filter
def get_item(d, key):
    if isinstance(d, dict):
        return d.get(key, "")
    return ""

@register.filter
def json_loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}
    
@register.filter
def status_badge_color(status: str) -> str:
    """
    Maps MDUHeader.status -> Bootstrap badge color.
    Return values align to Bootstrap 5: primary, secondary, success, danger, warning, info, dark, light.
    """
    if not status:
        return "secondary"

    s = str(status).upper()

    # Header lifecycle statuses
    if s == "ACTIVE":
        return "success"
    if s in {"PENDING_REVIEW", "IN_REVIEW"}:
        return "warning"
    if s == "REJECTED":
        return "danger"
    if s == "RETIRED":
        return "secondary"

    # Fallback for any future statuses
    return "secondary"