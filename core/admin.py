from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm

from .models import Allocation, Cycle, Department, Institution, ModelVersion, PastProject, Student, Supervisor, User


class EmailUserCreationForm(UserCreationForm):
    """Accounts sign in with their email address, so the admin asks for that, not a username."""

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "department")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        data = super().clean()
        if data.get("role") == User.COORDINATOR and not data.get("department"):
            self.add_error("department", "Choose the department this coordinator will run.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email
        if commit:
            user.save()
        return user


@admin.register(User)
class UA(UserAdmin):
    add_form = EmailUserCreationForm
    list_display = ("email", "first_name", "last_name", "role", "department", "approved", "is_superuser")
    list_filter = ("role", "approved", "is_superuser", "department")
    actions = ["approve_coordinators"]

    @admin.action(description="Approve the selected coordinators")
    def approve_coordinators(self, request, queryset):
        n = queryset.filter(role=User.COORDINATOR).update(approved=True)
        self.message_user(request, f"Approved {n} coordinator account(s).")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Person", {"fields": ("first_name", "last_name")}),
        ("Role", {"fields": ("role", "department", "approved")}),
        ("Access", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": (
        "email", "first_name", "last_name", "role", "department", "password1", "password2")}),)

    def save_model(self, request, obj, form, change):
        obj.email = (obj.email or "").strip().lower()
        obj.username = obj.email
        super().save_model(request, obj, form, change)


@admin.register(Department)
class DA(admin.ModelAdmin):
    list_display = ("name", "institution", "session", "matric_example")
    fields = ("institution", "name", "session", "matric_pattern", "matric_example")


@admin.register(Institution)
class IA(admin.ModelAdmin):
    list_display = ("name", "short_name", "kind", "state", "zone", "cgpa_scale")


@admin.register(PastProject)
class PA(admin.ModelAdmin):
    list_display = ("title", "supervisor", "session", "held_out")
    list_filter = ("held_out", "session", "supervisor__department")
    list_editable = ("held_out",)
    search_fields = ("title", "keywords")


@admin.register(Student)
class SA(admin.ModelAdmin):
    list_display = ("matric_no", "full_name", "level", "department", "cgpa")
    list_filter = ("level", "department")
    search_fields = ("matric_no", "full_name")


@admin.register(Supervisor)
class SupA(admin.ModelAdmin):
    list_display = ("full_name", "department", "capacity", "capacity_nd", "approved")
    list_filter = ("department", "approved")


@admin.register(Cycle)
class CA(admin.ModelAdmin):
    list_display = ("department", "level", "last_run_at", "published")
    list_filter = ("level", "published")


admin.site.register([ModelVersion, Allocation])
admin.site.site_header = "Platform administration"
admin.site.site_title = "Platform administration"
admin.site.index_title = "Institutions, departments and coordinator accounts"
