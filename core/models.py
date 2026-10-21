"""Database tables (report Table 4.2), plus institutions, departments and per-level
allocation cycles, so every department can allocate its ND and HND students separately."""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q

ZONES = ["North Central", "North East", "North West", "South East", "South South", "South West"]
ND, HND = "ND", "HND"
LEVELS = [(ND, "National Diploma (ND)"), (HND, "Higher National Diploma (HND)")]
LEVEL_NAMES = dict(LEVELS)


class User(AbstractUser):
    """users table: login accounts for students, supervisors and administrators."""
    STUDENT, SUPERVISOR, COORDINATOR = "student", "supervisor", "coordinator"
    ROLES = [(STUDENT, "Student"), (SUPERVISOR, "Supervisor"), (COORDINATOR, "Coordinator")]
    role = models.CharField(max_length=12, choices=ROLES, default=STUDENT)
    email = models.EmailField(unique=True)
    department = models.ForeignKey("Department", null=True, blank=True, on_delete=models.SET_NULL,
                                   help_text="Department a coordinator administers")

    def display_name(self):
        return self.get_full_name() or self.email


class Institution(models.Model):
    KINDS = [("University", "University"), ("Polytechnic", "Polytechnic"),
             ("College of Technology", "College of Technology"),
             ("College of Education", "College of Education")]
    name = models.CharField(max_length=160, unique=True)
    short_name = models.CharField(max_length=30)
    kind = models.CharField(max_length=30, choices=KINDS)
    state = models.CharField(max_length=40)
    zone = models.CharField(max_length=20, choices=[(z, z) for z in ZONES])
    cgpa_scale = models.DecimalField(max_digits=3, decimal_places=2, default=4,
                                     help_text="4.00 for polytechnics, 5.00 for most universities")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=120)
    session = models.CharField(max_length=12, default="2025/2026")
    matric_pattern = models.CharField(max_length=120, blank=True,
                                      help_text="Regular expression for this department's matric format")
    matric_example = models.CharField(max_length=40, blank=True)

    class Meta:
        unique_together = [("institution", "name")]
        ordering = ["institution__name", "name"]

    def __str__(self):
        return f"{self.name}, {self.institution.short_name}"

    @property
    def cgpa_scale(self):
        return self.institution.cgpa_scale

    def cycle(self, level):
        """The allocation cycle of one level in this department (created on first use)."""
        c, _ = Cycle.objects.get_or_create(department=self, level=level)
        return c

    @property
    def any_published(self):
        return self.cycles.filter(published=True).exists()


class Cycle(models.Model):
    """One allocation per level per department: ND projects and HND projects are
    allocated, reviewed and published separately."""
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="cycles")
    level = models.CharField(max_length=3, choices=LEVELS)
    threshold = models.FloatField(default=0.30)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_version = models.ForeignKey("ModelVersion", null=True, blank=True, on_delete=models.SET_NULL)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("department", "level")]
        ordering = ["department", "-level"]

    def __str__(self):
        return f"{self.level} allocation, {self.department}"

    @property
    def level_name(self):
        return LEVEL_NAMES[self.level]


class Student(models.Model):
    """students table: matric number is the primary key, so no student appears twice."""
    matric_no = models.CharField(max_length=25, primary_key=True)
    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="students")
    full_name = models.CharField(max_length=120)
    level = models.CharField(max_length=3, choices=LEVELS, default=HND)
    cgpa = models.DecimalField(max_digits=3, decimal_places=2)
    interest_text = models.TextField(blank=True)

    class Meta:
        ordering = ["matric_no"]
        constraints = [models.CheckConstraint(condition=Q(cgpa__gte=0) & Q(cgpa__lte=5),
                                              name="cgpa_in_range")]

    def __str__(self):
        return f"{self.matric_no} {self.full_name}"

    @property
    def ready(self):
        return bool(self.interest_text.strip())


class Supervisor(models.Model):
    """supervisors table: specialisation statement and maximum number of students per level."""
    supervisor_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="supervisors")
    full_name = models.CharField(max_length=120)
    specialisation_text = models.TextField(blank=True)
    capacity = models.PositiveIntegerField(default=5, help_text="Maximum number of HND students")
    capacity_nd = models.PositiveIntegerField(default=3, help_text="Maximum number of ND students")
    approved = models.BooleanField(default=True, help_text="Confirmed by the coordinator")

    class Meta:
        ordering = ["full_name"]
        constraints = [models.CheckConstraint(condition=Q(capacity__gte=1) | Q(capacity_nd__gte=1),
                                              name="capacity_at_least_one")]

    def __str__(self):
        return self.full_name

    def capacity_for(self, level):
        return self.capacity_nd if level == ND else self.capacity

    @property
    def ready(self):
        return self.approved and bool(self.specialisation_text.strip())

    def takes(self, level):
        return self.ready and self.capacity_for(level) >= 1

    def load(self, level):
        return self.allocations.filter(student__level=level).count()


class PastProject(models.Model):
    """past_projects table: earlier supervised projects. They build supervisor
    profiles and are the records the model is fine-tuned and evaluated on."""
    project_id = models.BigAutoField(primary_key=True)
    supervisor = models.ForeignKey(Supervisor, on_delete=models.CASCADE, related_name="past_projects")
    title = models.CharField(max_length=300)
    keywords = models.CharField(max_length=300, blank=True)
    abstract = models.TextField(blank=True)
    session = models.CharField(max_length=12, blank=True)
    held_out = models.BooleanField(default=False, help_text="Kept back from training; used only for evaluation")

    class Meta:
        ordering = ["supervisor", "-session", "title"]

    def __str__(self):
        return self.title


class ModelVersion(models.Model):
    """model_versions table: each saved SBERT version with its evaluation scores."""
    version_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    training_round = models.PositiveIntegerField(default=0, help_text="0 = pretrained, no fine-tuning")
    top1 = models.FloatField(null=True, blank=True)
    top3 = models.FloatField(null=True, blank=True)
    mrr = models.FloatField(null=True, blank=True)
    n_train = models.PositiveIntegerField(null=True, blank=True)
    n_eval = models.PositiveIntegerField(null=True, blank=True)
    file_path = models.CharField(max_length=200, help_text="Folder inside models/")
    notes = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["training_round", "version_id"]

    def __str__(self):
        return self.name

    @classmethod
    def active(cls):
        return cls.objects.filter(is_active=True).first()


class EmbeddingCache(models.Model):
    """Stored embeddings: each text is encoded once per model version."""
    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE)
    text_hash = models.CharField(max_length=40)
    vector = models.BinaryField()

    class Meta:
        unique_together = [("model_version", "text_hash")]


class FitScore(models.Model):
    """fit_scores table: cosine-similarity fit of each student-supervisor pair."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, db_column="matric_no", related_name="fit_scores")
    supervisor = models.ForeignKey(Supervisor, on_delete=models.CASCADE, related_name="fit_scores")
    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE)
    score = models.FloatField()
    rank = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("student", "supervisor")]
        ordering = ["student", "rank"]


class Allocation(models.Model):
    """allocations table: matric number is the primary key, so the database
    cannot record more than one supervisor for the same student."""
    student = models.OneToOneField(Student, primary_key=True, on_delete=models.CASCADE,
                                   db_column="matric_no", related_name="allocation")
    supervisor = models.ForeignKey(Supervisor, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="allocations")
    fit_score = models.FloatField(null=True, blank=True)
    choice_rank = models.PositiveIntegerField(null=True, blank=True)
    priority_position = models.PositiveIntegerField(default=0)
    flagged = models.BooleanField(default=False)
    flag_reason = models.CharField(max_length=20, blank=True)  # weak_fit | no_place
    resolved = models.BooleanField(default=False)
    resolution = models.CharField(max_length=200, blank=True)
    manual = models.BooleanField(default=False)
    allocated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority_position"]

    @property
    def open_flag(self):
        return self.flagged and not self.resolved
