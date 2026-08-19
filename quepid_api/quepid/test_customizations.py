"""Unit tests for the four hand-patches CLAUDE.md documents in models.py.

``models.py`` is otherwise pure ``inspectdb`` output, regenerable at any time
by re-running inspectdb against a migrated Quepid database. Four fields are a
documented exception -- type corrections inspectdb cannot infer because the
relationship exists in Rails but not as a database constraint -- and a
regeneration silently drops them back to inspectdb's plain-integer guess.
These tests exist to catch that the moment it happens, rather than the moment
something calling ``api/search_endpoints.py`` or ``api/cases.py`` breaks with a
bare 400.

No database connection: field types are metadata on the model class, so these
run against ``quepid/models.py`` alone. See ``conftest.py`` in this directory
for the (DB-free) Django bootstrap that makes the import possible.

Run from ``quepid_api/`` (with this app's dependencies installed and a
``QUEPID_DB_*``-free environment, e.g. inside the built app image)::

    docker compose exec quepid-api-app pytest quepid/test_customizations.py
"""
from django.core.exceptions import FieldDoesNotExist
from django.db import models as djm
import pytest

from quepid.models import CaseScores, Judgements, SearchEndpoints, Tries, Users


def _assert_foreign_key(model, field_name, target_model):
    try:
        field = model._meta.get_field(field_name)
    except FieldDoesNotExist:
        pytest.fail(
            f"{model.__name__}.{field_name} is gone -- inspectdb regenerated it "
            f"as a plain '{field_name}_id' integer field again. Re-apply the "
            f"hand-patch documented in CLAUDE.md."
        )

    assert isinstance(field, djm.ForeignKey), (
        f"{model.__name__}.{field_name} is a {type(field).__name__}, not a "
        f"ForeignKey -- the CLAUDE.md hand-patch was dropped by a regeneration."
    )
    assert field.remote_field.model is target_model, (
        f"{model.__name__}.{field_name} points at "
        f"{field.remote_field.model.__name__}, expected {target_model.__name__}"
    )


def test_search_endpoints_owner_is_a_foreign_key():
    _assert_foreign_key(SearchEndpoints, "owner", Users)


def test_tries_search_endpoint_is_a_foreign_key():
    _assert_foreign_key(Tries, "search_endpoint", SearchEndpoints)


def test_judgements_user_is_a_foreign_key():
    _assert_foreign_key(Judgements, "user", Users)


def test_case_scores_queries_is_a_binary_field():
    field = CaseScores._meta.get_field("queries")
    assert isinstance(field, djm.BinaryField), (
        f"CaseScores.queries is a {type(field).__name__}, not a BinaryField -- "
        f"the column is a mediumblob (see CLAUDE.md); the CLAUDE.md hand-patch "
        f"was dropped by a regeneration."
    )
