import os

from pathlib import Path

# Safe at settings-import time: a string constant, no Django imports.
from quepid_mcp.instructions import SERVER_INSTRUCTIONS

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET')

# SECURITY WARNING: don't run with debug turned on in production!

DEBUG = bool(int(os.getenv('DJANGO_DEBUG', 0)))

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
]


# Application definition

INSTALLED_APPS = [
    # 'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    # django-mcp-server imports SESSION_ENGINE at startup, so the app has to be
    # installed even though we run the MCP server stateless (see SESSION_ENGINE).
    'django.contrib.sessions',
    # 'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'mcp_server',
    'quepid',
    # Must be installed: django-mcp-server autodiscovers quepid_mcp/mcp.py.
    'quepid_mcp',
    # Must be installed: Django only discovers management commands (here,
    # load_dataset) in installed apps. It has no models and no URLs.
    'quepid_datasets',
]

# Cookie-backed so nothing ever needs a django_session table -- this project
# has no migrations and never runs `migrate`.
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

REST_FRAMEWORK = {
    # Keep BrowsableAPIRenderer out of content negotiation on the MCP endpoint.
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'quepid_api.urls'

# MCP server (see docs/mcp-server-plan.md). Same bearer tokens as the ninja API.
# Setting DJANGO_MCP_AUTHENTICATION_CLASSES makes mcp_server.urls apply
# IsAuthenticated automatically, so the endpoint is closed by default.
DJANGO_MCP_AUTHENTICATION_CLASSES = [
    'quepid_mcp.auth.QuepidTokenAuthentication',
]

DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    'name': 'quepid',
    # Stateless: no Django session is layered on the transport. The underlying
    # StreamableHTTPSessionManager is stateless regardless, and read-only tools
    # have no per-session state worth keeping.
    'stateless': True,
    # Prose lives with the toolsets it describes, in the quepid_mcp app.
    'instructions': SERVER_INSTRUCTIONS,
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'quepid_api.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    },
    'quepid': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('QUEPID_DB_NAME'),
        'USER': os.getenv('QUEPID_DB_USER'),
        'PASSWORD': os.getenv('QUEPID_DB_PASSSWORD'),
        'HOST': os.getenv('QUEPID_DB_HOST'),
        'PORT': os.getenv('QUEPID_DB_PORT'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    # {
    #     'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    # },
    # {
    #     'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    # },
    # {
    #     'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    # },
    # {
    #     'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    # },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')


# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'urllib3': {
            'level': 'NOTSET',
            'propagate': False,
        },
        'urllib3.*': {
            'level': 'NOTSET',
            'propagate': False,
        },
    },
}
