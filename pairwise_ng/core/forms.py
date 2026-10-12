from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from engine import preprocess as pp

from .models import Department, PastProject, Student, Supervisor, User

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
    role = forms.ChoiceField(label="I am a", choices=[("student", "Final year student"),
                                                      ("supervisor", "Project supervisor")])
    department = forms.ModelChoiceField(
        label="Institution and department", empty_label="Choose your department",
        queryset=Department.objects.select_related("institution"))
    full_name = forms.CharField(label="Full name", max_length=120)
    matric_no = forms.CharField(label="Matric number", max_length=25, required=False,
                                help_text="Students only.")
    email = forms.EmailField(label="Email address")
    password = forms.CharField(label="Password", strip=False, min_length=8,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text="At least 8 characters.")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["department"].label_from_instance = (
            lambda d: f"{d.institution.name}, {d.name}")

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
        if data.get("role") == "student" and data.get("department"):
            m = pp.normalise_matric(data.get("matric_no"))
            dept = data["department"]
            if not m:
                self.add_error("matric_no", "Enter your matric number.")
            elif pp.matric_error(m, dept.matric_pattern or None):
                self.add_error("matric_no", f"That does not look like a {dept.institution.short_name} "
                               f"matric number. Example: {dept.matric_example or 'ask your coordinator'}.")
            else:
                existing = Student.objects.filter(pk=m).first()
                if existing and (existing.user_id or existing.department_id != dept.id):
                    self.add_error("matric_no", "This matric number is already registered. "
                                   "If that is a mistake, contact your project coordinator.")
                data["matric_no"] = m
        return data


class StudentForm(forms.ModelForm):
    """Used by the student (own profile) and the coordinator (records management)."""

    class Meta:
        model = Student
        fields = ["matric_no", "full_name", "cgpa", "interest_text"]
        labels = {"matric_no": "Matric number", "cgpa": "CGPA", "interest_text": "Project interest"}
        widgets = {"interest_text": forms.Textarea(attrs={"rows": 4, "maxlength": 600}),
                   "cgpa": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"})}

    def __init__(self, *a, department=None, lock_matric=False, require_interest=True, **kw):
        super().__init__(*a, **kw)
        self.department = department
        scale = float(department.cgpa_scale)
        self.fields["cgpa"].help_text = f"On your institution's {scale:.2f} scale."
        self.fields["cgpa"].widget.attrs["max"] = f"{scale:.2f}"
        self.fields["interest_text"].help_text = INTEREST_HELP
        self.fields["interest_text"].required = require_interest
        if department.matric_example:
            self.fields["matric_no"].help_text = f"Format: {department.matric_example}"
        if lock_matric or (self.instance and self.instance.pk):
            self.fields["matric_no"].disabled = True

    def clean_matric_no(self):
        m = pp.normalise_matric(self.cleaned_data["matric_no"])
        err = pp.matric_error(m, self.department.matric_pattern or None)
        if err:
            raise forms.ValidationError(err)
        if not self.instance.pk and Student.objects.filter(pk=m).exists():
            raise forms.ValidationError("A student with this matric number already exists.")
        return m

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
        fields = ["full_name", "specialisation_text", "capacity"]
        labels = {"specialisation_text": "Specialisation", "capacity": "Maximum number of students"}
        widgets = {"specialisation_text": forms.Textarea(attrs={"rows": 3, "maxlength": 500}),
                   "capacity": forms.NumberInput(attrs={"min": "1", "max": "60", "inputmode": "numeric"})}
        help_texts = {
            "specialisation_text": "The areas you supervise, in a sentence. For example: "
                                   "\u201cMachine learning, predictive analytics and data science\u201d.",
            "capacity": "A whole number, at least 1."}

    def clean_specialisation_text(self):
        t = pp.clean_text(self.cleaned_data["specialisation_text"])
        if len(t) < 10:
            raise forms.ValidationError("Describe your specialisation in at least a few words.")
        return t

    def clean_capacity(self):
        c = self.cleaned_data["capacity"]
        if c < 1:
            raise forms.ValidationError("Capacity must be a whole number of at least 1.")
        if self.instance.pk:
            load = self.instance.allocations.count()
            if c < load:
                raise forms.ValidationError(
                    f"{load} students are already allocated to this supervisor. "
                    "Run the allocation again or move students first.")
        return c


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
    file = forms.FileField(label="CSV file")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError("The file is larger than 2 MB.")
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file. The template shows the columns.")
        return f
