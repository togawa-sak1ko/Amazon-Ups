from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS")
if allowed_hosts_env:
    ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(",") if host.strip()]
elif DEBUG:
    # In debug-only environments, avoid DisallowedHost on ad-hoc IP access.
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = [
        "127.0.0.1",
        "localhost",
        "host.docker.internal",
        "vcm-51642.vm.duke.edu",
        "67.159.74.167",
        "67.159.75.250",
    ]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://127.0.0.1:8081,http://localhost:8081,http://127.0.0.1,http://localhost,http://vcm-51642.vm.duke.edu:8081,http://67.159.74.167:8081,http://67.159.75.250:8081,http://vcm-51642.vm.duke.edu:8191,http://67.159.74.167:8191,http://67.159.75.250:8191",
    ).split(",")
    if origin.strip()
]

# Avoid cookie name collisions with Amazon when both run on localhost.
SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "ups_sessionid")
CSRF_COOKIE_NAME = os.environ.get("CSRF_COOKIE_NAME", "ups_csrftoken")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ups",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "ups.middleware.SetupErrorMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.environ.get("DATABASE_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DATABASE_NAME", "ups"),
            "USER": os.environ.get("DATABASE_USER", "ups"),
            "PASSWORD": os.environ.get("DATABASE_PASSWORD", "ups"),
            "HOST": os.environ.get("DATABASE_HOST", "db"),
            "PORT": os.environ.get("DATABASE_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_REDIRECT_URL = "ups:dashboard"
LOGOUT_REDIRECT_URL = "login"

UPS_HTTP_PORT = int(os.environ.get("UPS_PORT", "8081"))
AMAZON_HOST = os.environ.get("AMAZON_HOST", "amazon")
AMAZON_PORT = int(os.environ.get("AMAZON_PORT", "8080"))
AMAZON_BASE_URL = os.environ.get("AMAZON_BASE_URL", f"http://{AMAZON_HOST}:{AMAZON_PORT}")

UPS_WORLD_HOST = os.environ.get("WORLD_HOST", "world")
UPS_WORLD_PORT = int(os.environ.get("WORLD_PORT", "12345"))
UPS_API_TOKEN = os.environ.get("UPS_API_TOKEN", "")
UPS_WORLD_DAEMON_DRY_RUN = os.environ.get("WORLD_DAEMON_DRY_RUN", "1") == "1"
# After a world UErr, requeue the same seq_num up to this many times before leaving the row FAILED.
UPS_WORLD_COMMAND_MAX_RETRIES = int(os.environ.get("UPS_WORLD_COMMAND_MAX_RETRIES", "5"))
