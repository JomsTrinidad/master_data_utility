import django_filters
from django import forms
from django.db.models import Q
from .models import MDUHeader, ChangeRequest

class HeaderFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(
        method="filter_q",
        label="Search",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Search name, tags, description…"
        }),
    )

    status = django_filters.ChoiceFilter(
        # UX: dropdown defaults to "All" (blank)
        choices=[("", "All"), *list(MDUHeader.Status.choices)],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ref_type = django_filters.ChoiceFilter(
        choices=[("", "All"), ("map", "Map"), ("list", "List")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    mode = django_filters.ChoiceFilter(
        choices=[("", "All"), ("versioning", "Versioning"), ("snapshot", "Snapshot")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = MDUHeader
        fields = ["q", "status", "ref_type", "mode"]

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        v = value.strip()
        return queryset.filter(
            Q(ref_name__icontains=v) |
            Q(tags__icontains=v) |
            Q(description__icontains=v)
        )


class ProposedChangeFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="filter_q", label="Search")
    class Meta:
        model = ChangeRequest
        fields = ["status", "header"]

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(display_id__icontains=value)
