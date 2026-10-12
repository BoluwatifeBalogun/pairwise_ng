from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Allocation, Department, Institution, ModelVersion, PastProject, Student, Supervisor, User


@admin.register(User)
class UA(UserAdmin):
    list_display = ("email", "role", "department", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role", "department")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Role", {"fields": ("email", "role", "department")}),)


admin.site.register([Institution, Department, Student, Supervisor, PastProject, ModelVersion, Allocation])
admin.site.site_header = "Platform administration"
