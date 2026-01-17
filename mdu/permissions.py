from functools import wraps
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

def in_group(user, group_name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=group_name).exists()

def group_required(*group_names):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if any(in_group(request.user, g) for g in group_names):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("You don't have access to this page.")
        return _wrapped
    return decorator
