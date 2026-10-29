from django.contrib.auth import views as auth
from django.urls import path

from . import views as v
from .forms import LoginForm

urlpatterns = [
    path("", v.landing, name="landing"),
    path("api/match", v.api_match, name="api_match"),
    path("login", auth.LoginView.as_view(template_name="core/login.html",
                                         authentication_form=LoginForm), name="login"),
    path("logout", auth.LogoutView.as_view(), name="logout"),
    path("register", v.register, name="register"),
    path("home", v.home, name="home"),
    path("student", v.student_home, name="student_home"),
    path("supervisor", v.supervisor_home, name="supervisor_home"),
    path("supervisor/projects/<int:pk>/delete", v.project_delete, name="project_delete"),
    path("coordinator", v.c_overview, name="c_overview"),
    path("coordinator/coordinators/<int:pk>", v.c_coordinator_decide, name="c_coordinator_decide"),
    path("coordinator/students", v.c_students, name="c_students"),
    path("coordinator/students/add", v.c_student_form, name="c_student_add"),
    path("coordinator/students/import", v.c_students_import, name="c_students_import"),
    path("coordinator/students/edit/<path:matric>", v.c_student_form, name="c_student_edit"),
    path("coordinator/students/delete/<path:matric>", v.c_student_delete, name="c_student_delete"),
    path("coordinator/students/view/<path:matric>", v.c_student_detail, name="c_student_detail"),
    path("coordinator/supervisors", v.c_supervisors, name="c_supervisors"),
    path("coordinator/supervisors/add", v.c_supervisor_form, name="c_supervisor_add"),
    path("coordinator/supervisors/<int:pk>/edit", v.c_supervisor_form, name="c_supervisor_edit"),
    path("coordinator/supervisors/<int:pk>/delete", v.c_supervisor_delete, name="c_supervisor_delete"),
    path("coordinator/supervisors/<int:pk>/approve", v.c_supervisor_approve, name="c_supervisor_approve"),
    path("coordinator/projects", v.c_projects, name="c_projects"),
    path("coordinator/models", v.c_models, name="c_models"),
    path("coordinator/run", v.c_run, name="c_run"),
    path("coordinator/flagged", v.c_flagged, name="c_flagged"),
    path("coordinator/report", v.c_report, name="c_report"),
    path("coordinator/report.csv", v.c_report_csv, name="c_report_csv"),
    path("template/<str:name>.csv", v.csv_template, name="csv_template"),
    path("template/<str:name>.xlsx", v.csv_template, {"ext": "xlsx"}, name="xlsx_template"),
    path("coordinator/supervisors/import", v.c_supervisors_import, name="c_supervisors_import"),
    path("coordinator/supervisors.xlsx", v.c_supervisors_xlsx, name="c_supervisors_xlsx"),
    path("coordinator/students.xlsx", v.c_students_xlsx, name="c_students_xlsx"),
    path("coordinator/report.xlsx", v.c_report_xlsx, name="c_report_xlsx"),
]
