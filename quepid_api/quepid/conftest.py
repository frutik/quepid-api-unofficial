"""Django bootstrap for the unit tests in this app -- see test_customizations.py.

Separate from tests/conftest.py at the repo root on purpose: that suite is HTTP
integration only and deliberately never imports Django (see its docstring and
pytest.ini). This one does the opposite -- it configures Django settings with
no database connection, so it can inspect quepid/models.py field definitions
directly without a live MySQL.
"""
import os

import django


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quepid_api.settings")
# Only needed for django.setup() to complete; nothing here signs or verifies
# anything with it. QUEPID_DB_* are deliberately left unset -- these tests
# never open a database connection.
os.environ.setdefault("DJANGO_SECRET", "unit-test-placeholder")

django.setup()
