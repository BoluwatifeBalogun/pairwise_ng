from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from engine import preprocess as pp

from .models import HND, LEVELS, ND, Department, PastProject, Student, Supervisor, User

INTEREST_HELP = ("Say what you want to work on in your own words. For example: "
                 "\u201ca mobile app that helps farmers check market prices\u201d.")


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(
        attrs={"autocomplete": "email", "autofocus": True}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(
        attrs={"autocomplete": "current-password"}))

    def clean_username(self):
        return self.cleaned_data["username"].lower()


class RegisterForm(forms.Form):
    """Self sign-up is for students only. Supervisors are added by their department's coordinator
    or the administrator; coordinators are created by the administrator."""
    department = forms.ModelChoiceField(label="Department", empty_label="Choose your department",
                                        queryset=Department.objects.select_related("institution"))
    level = forms.ChoiceField(label="Programme", choices=LEVELS, initial=HND, required=False)
    full_name = forms.CharField(label="Full name", max_length=120)
    matric_no = forms.CharField(label="Matric number", max_length=25,
                                error_messages={"required": "Enter your matric number."},
                                help_text="For example F/HD/24/3210001 or F/ND/24/3210001.")
    email = forms.EmailField(label="Email address")
    password = forms.CharField(label="Password", strip=False, min_length=8,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text="At least 8 characters.")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["department"].label_from_instance = lambda d: d.name

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists. Sign in instead.")
        return email

    def clean_password(self):
        validate_password(self.cleaned_data["password"])
        return self.cleaned_data["password"]

    def clean(self):
        data = super().clean()
        data["role"] = "student"
        if data.get("department") and data.get("matric_no"):
            m = pp.normalise_matric(data.get("matric_no"))
            dept = data["department"]
            if pp.matric_error(m, dept.matric_pattern or None):
                self.add_error("matric_no", f"That does not look like a {dept.institution.short_name} "
                               f"matric number. Example: {dept.matric_example or 'ask your coordinator'}.")
            else:
                existing = Student.objects.filter(pk=m).first()
                if existing and (existing.user_id or existing.department_id != dept.id):
                    self.add_error("matric_no", "This matric number is already registered. "
                                   "If that is a mistake, contact your project coordinator.")
                data["matric_no"] = m
                from_matric = pp.level_from_matric(m)
                chosen = data.get("level") or from_matric or HND
                if from_matric and from_matric != chosen:
                    self.add_error("level", f"This matric number is an {from_matric} number. "
                                   f"Choose {from_matric}, or check the number.")
                data["level"] = chosen
        return data


class StudentForm(forms.ModelForm):
    """Used by the student (own profile) and the coordinator (records management)."""

    class Meta:
        model = Student
        fields = ["matric_no", "full_name", "level", "cgpa", "interest_text"]
        labels = {"matric_no": "Matric number", "level": "Programme", "cgpa": "CGPA",
                  "interest_text": "Project interest"}
        widgets = {"interest_text": forms.Textarea(attrs={"rows": 4, "maxlength": 600}),
                   "cgpa": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"})}

    def __init__(self, *a, department=None, lock_matric=False, require_interest=True, level=None, **kw):
        super().__init__(*a, **kw)
        self.department = department
        if level and not (self.instance and self.instance.pk):
            self.fields["level"].initial = level
        scale = float(department.cgpa_scale)
        self.fields["cgpa"].help_text = f"On your institution's {scale:.2f} scale."
        self.fields["cgpa"].widget.attrs["max"] = f"{scale:.2f}"
        self.fields["interest_text"].help_text = INTEREST_HELP
        self.fields["interest_text"].required = require_interest
        if department.matric_example:
            self.fields["matric_no"].help_text = f"Format: {department.matric_example}"
        if lock_matric or (self.instance and self.instance.pk):
            self.fields["matric_no"].disabled = True
        if lock_matric:
            self.fields["level"].disabled = True

    def clean_matric_no(self):
        m = pp.normalise_matric(self.cleaned_data["matric_no"])
        err = pp.matric_error(m, self.department.matric_pattern or None)
        if err:
            raise forms.ValidationError(err)
        if not self.instance.pk and Student.objects.filter(pk=m).exists():
            raise forms.ValidationError("A student with this matric number already exists.")
        return m

    def clean(self):
        data = super().clean()
        m = data.get("matric_no") or (self.instance.pk if self.instance else "")
        from_matric = pp.level_from_matric(m)
        if from_matric and data.get("level") and from_matric != data["level"]:
            self.add_error("level", f"This matric number is an {from_matric} number.")
        return data

    def clean_cgpa(self):
        err = pp.cgpa_error(self.cleaned_data["cgpa"], self.department.cgpa_scale)
        if err:
            raise forms.ValidationError(err)
        return self.cleaned_data["cgpa"]

    def clean_interest_text(self):
        t = pp.clean_text(self.cleaned_data.get("interest_text"))
        if t or self.fields["interest_text"].required:
            err = pp.interest_error(t)
            if err:
                raise forms.ValidationError(err)
        return t


class SupervisorForm(forms.ModelForm):
    class Meta:
        model = Supervisor
        fields = ["full_name", "specialisation_text", "capacity", "capacity_nd"]
        labels = {"specialisation_text": "Specialisation", "capacity": "Maximum number of HND students",
                  "capacity_nd": "Maximum number of ND students"}
        widgets = {"specialisation_text": forms.Textarea(attrs={"rows": 3, "maxlength": 500}),
                   "capacity": forms.NumberInput(attrs={"min": "0", "max": "60", "inputmode": "numeric"}),
                   "capacity_nd": forms.NumberInput(attrs={"min": "0", "max": "60", "inputmode": "numeric"})}
        help_texts = {
            "specialisation_text": "The areas you supervise, in a sentence. For example: "
                                   "\u201cMachine learning, predictive analytics and data science\u201d.",
            "capacity": "Enter 0 if you do not supervise HND projects.",
            "capacity_nd": "Enter 0 if you do not supervise ND projects."}

    login_email = forms.EmailField(label="Sign-in email", required=False,
                                   help_text="Optional. Give the supervisor a sign-in so they can see their students.")
    login_password = forms.CharField(label="Password", required=False, strip=False,
                                     widget=forms.PasswordInput(attrs={"autocomplete": "new-password"},
                                                                render_value=False))

    def __init__(self, *a, with_login=True, **kw):
        super().__init__(*a, **kw)
        self.fields["specialisation_text"].required = True
        if not with_login:
            del self.fields["login_email"], self.fields["login_password"]
            return
        user = self.instance.user if self.instance.pk else None
        if user:
            self.fields["login_email"].initial = user.email
            self.fields["login_password"].help_text = "Leave blank to keep the current password."
        else:
            self.fields["login_password"].help_text = "At least 8 characters. Share it with the supervisor."

    def clean_login_email(self):
        email = (self.cleaned_data.get("login_email") or "").strip().lower()
        if email:
            other = User.objects.filter(email=email)
            if self.instance.pk and self.instance.user_id:
                other = other.exclude(pk=self.instance.user_id)
            if other.exists():
                raise forms.ValidationError("Another account already uses this email.")
        return email

    def clean_specialisation_text(self):
        t = pp.clean_text(self.cleaned_data["specialisation_text"])
        if len(t) < 10:
            raise forms.ValidationError("Describe your specialisation in at least a few words.")
        return t

    def _check_capacity(self, field, level):
        c = self.cleaned_data[field]
        if c is None or c < 0:
            raise forms.ValidationError("Enter a whole number, 0 or more.")
        if self.instance.pk:
            load = self.instance.load(level)
            if c < load:
                raise forms.ValidationError(
                    f"{load} {level} students are already allocated to this supervisor. "
                    "Run the allocation again or move students first.")
        return c

    def clean_capacity(self):
        return self._check_capacity("capacity", HND)

    def clean_capacity_nd(self):
        return self._check_capacity("capacity_nd", ND)

    def clean(self):
        data = super().clean()
        if not (data.get("capacity") or data.get("capacity_nd")):
            self.add_error("capacity", "At least one of the two capacities must be 1 or more.")
        if "login_email" in self.fields:
            email, pw = data.get("login_email"), data.get("login_password")
            has_login = bool(self.instance.pk and self.instance.user_id)
            if pw and not email:
                self.add_error("login_email", "Enter the email the supervisor will sign in with.")
            elif email and not has_login and not pw:
                self.add_error("login_password", "Set a password for the new sign-in.")
            if pw:
                try:
                    validate_password(pw)
                except forms.ValidationError as e:
                    self.add_error("login_password", e)
        return data

    def save_login(self, sup):
        """Create or update the supervisor's sign-in from the two optional fields."""
        email = self.cleaned_data.get("login_email")
        pw = self.cleaned_data.get("login_password")
        if not email:
            return None
        user = sup.user
        first, _, last = sup.full_name.partition(" ")
        if user is None:
            user = User(role=User.SUPERVISOR, first_name=first, last_name=last)
        user.email = user.username = email
        if pw:
            user.set_password(pw)
        user.save()
        if sup.user_id != user.pk:
            sup.user = user
            sup.save(update_fields=["user"])
        return user


class ProjectForm(forms.ModelForm):
    class Meta:
        model = PastProject
        fields = ["title", "keywords", "session"]
        labels = {"title": "Project title", "keywords": "Keywords", "session": "Session"}
        help_texts = {"keywords": "Separated by commas.", "session": "For example 2023/2024."}

    def clean_title(self):
        t = pp.clean_text(self.cleaned_data["title"])
        if len(t) < 10:
            raise forms.ValidationError("Enter the full project title.")
        return t


class UploadForm(forms.Form):
    file = forms.FileField(label="Excel or CSV file", widget=forms.ClearableFileInput(
        attrs={"accept": ".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"}))

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The file is larger than 5 MB.")
        name = f.name.lower()
        if name.endswith(".xls"):
            raise forms.ValidationError("This is an old Excel file (.xls). In Excel choose Save As, then "
                                        "Excel Workbook (.xlsx), and upload that.")
        if not name.endswith((".xlsx", ".csv")):
            raise forms.ValidationError("Upload an Excel (.xlsx) or CSV file. The template shows the columns.")
        return f
