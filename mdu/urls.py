from django.urls import path

from . import views
from .views_changes import change_modal
from .views_exports import approved_export_csv, approved_export_json
from .views_compare import compare_modal, compare_versions

app_name = "mdu"

urlpatterns = [
    # Catalog / Reference detail
    path("", views.catalog, name="catalog"),
    path("catalog/", views.catalog, name="catalog"),
    path("references/<int:pk>/", views.header_detail, name="header_detail"),

    # Proposed changes
    path("proposed/", views.proposed_change_list, name="proposed_change_list"),
    path("references/<int:header_pk>/propose/", views.propose_change, name="propose_change"),
    path("proposed/<int:pk>/", views.proposed_change_detail, name="proposed_change_detail"),
    path("proposed/<int:pk>/edit/", views.proposed_change_edit, name="proposed_change_edit"),
    path("proposed/<int:pk>/submit/", views.proposed_change_submit, name="proposed_change_submit"),
    path("proposed/<int:pk>/decide/<str:decision>/", views.proposed_change_decide, name="proposed_change_decide"),
    path("proposed/<int:pk>/generate-load-files/", views.generate_load_files, name="generate_load_files"),

    # Change modals
    path("changes/<int:pk>/modal/", change_modal, name="change_modal"),

    # Approved exports
    path("headers/<int:pk>/approved.csv", approved_export_csv, name="approved_export_csv"),
    path("headers/<int:pk>/approved.json", approved_export_json, name="approved_export_json"),

    # Compare
    path("references/<int:pk>/compare/", compare_versions, name="compare_versions"),
    path("references/<int:pk>/compare/modal/", compare_modal, name="compare_modal"),

    # Certifications
    path("certifications/", views.cert_list, name="cert_list"),
    path("certifications/new/", views.cert_create, name="cert_create"),
]
