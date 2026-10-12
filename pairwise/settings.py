"""Settings for PairWise NG. Change SITE_NAME to rename the system everywhere."""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
SITE_NAME = os.environ.get("SITE_NAME", "PairWise NG")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    CSRF_TRUSTED_ORIGINS.append("https://" + os.environ["RENDER_EXTERNAL_HOSTNAME"])

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "core",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "pairwise.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context.site",
    ]},
}]
WSGI_APPLICATION = "pairwise.wsgi.application"

# SQLite out of the box. Set DATABASE_URL to keep data on a hosted database:
#   mysql://user:password@host:port/dbname        (filess.io, the report's MySQL)
#   postgres://user:password@host:port/dbname
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("mysql"):
    import pymysql  # pure-Python MySQL driver, nothing to compile on the host

    pymysql.install_as_MySQLdb()
# Free hosted databases allow only a handful of connections at once, so by default a
# connection is closed after each request instead of being held open.
DATABASES = {"default": dj_database_url.parse(
    DATABASE_URL or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "0")))}
if DATABASES["default"]["ENGINE"].endswith("mysql"):
    DATABASES["default"].setdefault("OPTIONS", {}).update({
        "charset": "utf8mb4",
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES', default_storage_engine=INNODB",
        "connect_timeout": 15,
    })

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "landing"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# SBERT model files live here; each ModelVersion row points at one sub-folder.
MODELS_DIR = BASE_DIR / "models"
PRETRAINED_MODEL = "sbert-minilm-pretrained"
DEFAULT_THRESHOLD = 0.30
# Show the demonstration sign-in shortcuts on the login page. Set DEMO_MODE=0 for real use.
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
