from django.contrib import admin
from .models import MDUHeader, ChangeRequest, MDUCert

@admin.register(MDUHeader)
class HeaderAdmin(admin.ModelAdmin):
    list_display = ("ref_name","ref_type","mode","status","owner_group","updated_at")
    search_fields = ("ref_name","tags","owner_group")
    list_filter = ("ref_type","mode","status")

@admin.register(ChangeRequest)
class ChangeAdmin(admin.ModelAdmin):
    list_display = ("display_id","header","status","submitted_at","decided_at")
    search_fields = ("display_id","tracking_id","header__ref_name")
    list_filter = ("status",)

@admin.register(MDUCert)
class CertAdmin(admin.ModelAdmin):
    list_display = ("header","cert_cycle_id","certification_status","cert_expiry_dttm")
    search_fields = ("header__ref_name","cert_cycle_id")
    list_filter = ("certification_status",)
