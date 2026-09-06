"""Integration tests for team membership, team scoping, and the case-team join.

Three behaviours that only exist together, so they are tested together:

- creating a team enrols the creator in it. Quepid has no owner column on
  ``teams``, so a team with no ``teams_members`` row is unreachable by anyone --
  it exists, and the UI's Share case dialog reports "No teams to share with";
- every ``/teams`` endpoint answers only for teams the caller is in;
- a case reaches a team through ``teams_cases``, written either by
  ``create_case`` resolving a team or by ``POST /teams/{id}/cases/``.

Membership is asserted over HTTP rather than in SQL: because the listing is
scoped, a team appearing in the caller's own ``GET /teams/`` *is* the assertion
that the membership row was written.

The team-resolution tests need a caller whose team count they control, since
``create_case`` behaves differently at zero, one and several teams. They use
``member_api`` and skip without ``QUEPID_MEMBER_API_TOKEN`` -- see its fixture.
"""
import pytest
import requests

from conftest import BASE_URL, _create, _discard, unique


pytestmark = pytest.mark.integration


def _team_ids(session):
    """The ids of every team the session's user belongs to."""
    response = session.get(f"{BASE_URL}/teams/", timeout=30)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


def _case_count(session):
    """The caller's total case count -- the listing is paginated, so a leaked
    case could sit on a page a name check never looks at."""
    response = session.get(f"{BASE_URL}/case/", timeout=30)
    assert response.status_code == 200, response.text
    return response.json()["count"]


def _shared_case_ids(session, team_id):
    response = session.get(f"{BASE_URL}/teams/{team_id}/cases/", timeout=30)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()}


@pytest.fixture
def teams(api):
    """Make throwaway teams for one test, cleaning them up afterwards.

    A factory rather than a fixture per team because the resolution tests turn
    on *how many* teams the caller has, so a test has to be able to add one and
    watch the behaviour change.
    """
    created = []

    def make(session=api):
        row = _create(session, f"{BASE_URL}/teams/", {"name": unique("team")})
        created.append((session, row))
        return row

    yield make

    for session, row in reversed(created):
        _discard(session, f"{BASE_URL}/teams/{row['id']}/")


@pytest.fixture
def owned_case(api, scorer, teams):
    """A case belonging to ``api``'s user, shared with one throwaway team.

    Passes ``team_id`` explicitly: the caller may already be in any number of
    teams, and letting the team be resolved implicitly would make the fixture's
    behaviour depend on that count.
    """
    home = teams()
    row = _create(
        api,
        f"{BASE_URL}/case/",
        {"name": unique("case"), "scorer_id": scorer["id"], "team_id": home["id"]},
    )
    yield row
    _discard(api, f"{BASE_URL}/case/{row['id']}/")


# --- creating a team enrols its creator -------------------------------------

def test_created_team_is_visible_to_its_creator(api, teams):
    """The membership row, observed through the scoped listing."""
    team = teams()
    assert team["id"] in _team_ids(api)


def test_created_team_is_fetchable_by_its_creator(api, teams):
    team = teams()
    response = api.get(f"{BASE_URL}/teams/{team['id']}/", timeout=10)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == team["id"]


def test_a_new_team_has_no_cases(api, teams):
    assert _shared_case_ids(api, teams()["id"]) == set()


# --- teams are scoped to their members --------------------------------------

def test_team_is_invisible_to_a_non_member(api, member_api, teams):
    team = teams()
    assert team["id"] not in _team_ids(member_api)


def test_non_member_cannot_read_a_team(api, member_api, teams):
    team = teams()
    response = member_api.get(f"{BASE_URL}/teams/{team['id']}/", timeout=10)
    # 404, not 403: whether another user's team exists is not theirs to learn.
    assert response.status_code == 404


def test_non_member_cannot_rename_a_team(api, member_api, teams):
    team = teams()
    response = member_api.put(
        f"{BASE_URL}/teams/{team['id']}/", json={"name": "hijacked"}, timeout=10
    )
    assert response.status_code == 404

    still_there = api.get(f"{BASE_URL}/teams/{team['id']}/", timeout=10)
    assert still_there.json()["name"] == team["name"]


def test_non_member_cannot_delete_a_team(api, member_api, teams):
    team = teams()
    response = member_api.delete(f"{BASE_URL}/teams/{team['id']}/", timeout=10)
    assert response.status_code == 404
    assert api.get(f"{BASE_URL}/teams/{team['id']}/", timeout=10).status_code == 200


def test_non_member_cannot_list_a_teams_cases(member_api, teams):
    team = teams()
    response = member_api.get(f"{BASE_URL}/teams/{team['id']}/cases/", timeout=10)
    assert response.status_code == 404


# --- sharing a case with a team ---------------------------------------------

def test_share_case_with_team(api, teams, owned_case):
    other = teams()
    assert owned_case["id"] not in _shared_case_ids(api, other["id"])

    response = api.post(
        f"{BASE_URL}/teams/{other['id']}/cases/",
        json={"case_id": owned_case["id"]},
        timeout=30,
    )
    assert response.status_code == 200, response.text
    assert owned_case["id"] in _shared_case_ids(api, other["id"])


def test_sharing_twice_is_idempotent(api, teams, owned_case):
    """teams_cases is keyed on (case_id, team_id): a re-share must not 500."""
    other = teams()
    url = f"{BASE_URL}/teams/{other['id']}/cases/"
    payload = {"case_id": owned_case["id"]}

    assert api.post(url, json=payload, timeout=30).status_code == 200
    assert api.post(url, json=payload, timeout=30).status_code == 200

    listed = [row["id"] for row in api.get(url, timeout=30).json()]
    assert listed.count(owned_case["id"]) == 1


def test_unshare_case_from_team(api, teams, owned_case):
    other = teams()
    api.post(
        f"{BASE_URL}/teams/{other['id']}/cases/",
        json={"case_id": owned_case["id"]},
        timeout=30,
    )

    response = api.delete(
        f"{BASE_URL}/teams/{other['id']}/cases/{owned_case['id']}/", timeout=10
    )
    assert response.status_code == 204
    assert owned_case["id"] not in _shared_case_ids(api, other["id"])


def test_unsharing_leaves_the_case_itself_alone(api, teams, owned_case):
    other = teams()
    api.post(
        f"{BASE_URL}/teams/{other['id']}/cases/",
        json={"case_id": owned_case["id"]},
        timeout=30,
    )
    api.delete(f"{BASE_URL}/teams/{other['id']}/cases/{owned_case['id']}/", timeout=10)

    assert api.get(f"{BASE_URL}/case/{owned_case['id']}/", timeout=10).status_code == 200


def test_unshare_a_case_that_was_never_shared_is_404(api, teams, owned_case):
    other = teams()
    response = api.delete(
        f"{BASE_URL}/teams/{other['id']}/cases/{owned_case['id']}/", timeout=10
    )
    assert response.status_code == 404


def test_share_unknown_case_is_400(api, teams):
    response = api.post(
        f"{BASE_URL}/teams/{teams()['id']}/cases/",
        json={"case_id": 999999999},
        timeout=10,
    )
    assert response.status_code == 400


def test_share_into_a_team_you_are_not_in_is_404(api, member_api, teams, owned_case):
    """Scoping is checked before ownership, so this is 404 rather than 400."""
    team = teams()
    response = member_api.post(
        f"{BASE_URL}/teams/{team['id']}/cases/",
        json={"case_id": owned_case["id"]},
        timeout=10,
    )
    assert response.status_code == 404


def test_cannot_share_a_case_you_do_not_own(member_api, teams, owned_case):
    """Seeing a case is not licence to pass it on to further teams."""
    mine = teams(session=member_api)
    response = member_api.post(
        f"{BASE_URL}/teams/{mine['id']}/cases/",
        json={"case_id": owned_case["id"]},
        timeout=10,
    )
    assert response.status_code == 400
    assert "not owned by you" in response.text


# --- which team a new case lands in -----------------------------------------

def test_case_is_unshared_when_the_caller_has_no_teams(member_api, scorer, teams):
    """No team is not an error: it is how Quepid creates cases by default."""
    if _team_ids(member_api):
        pytest.skip("member account already belongs to a team")

    case = _create(
        member_api,
        f"{BASE_URL}/case/",
        {"name": unique("case-noteam"), "scorer_id": scorer["id"]},
    )
    try:
        # Nothing to share it with at creation time, so a team made afterwards
        # must not somehow contain it.
        assert case["id"] not in _shared_case_ids(member_api, teams(session=member_api)["id"])
    finally:
        _discard(member_api, f"{BASE_URL}/case/{case['id']}/")


def test_case_joins_the_only_team_the_caller_belongs_to(member_api, scorer, teams):
    if _team_ids(member_api):
        pytest.skip("member account already belongs to a team")

    only = teams(session=member_api)
    case = _create(
        member_api,
        f"{BASE_URL}/case/",
        {"name": unique("case-auto"), "scorer_id": scorer["id"]},
    )
    try:
        assert case["id"] in _shared_case_ids(member_api, only["id"])
    finally:
        _discard(member_api, f"{BASE_URL}/case/{case['id']}/")


def test_several_teams_without_team_id_is_400(member_api, scorer, teams):
    if _team_ids(member_api):
        pytest.skip("member account already belongs to a team")

    first, second = teams(session=member_api), teams(session=member_api)

    before = _case_count(member_api)
    response = member_api.post(
        f"{BASE_URL}/case/",
        json={"name": unique("case-ambiguous"), "scorer_id": scorer["id"]},
        timeout=30,
    )
    assert response.status_code == 400
    assert "team_id" in response.text
    # The error names the teams, so the caller can act on it without a lookup.
    assert first["name"] in response.text and second["name"] in response.text
    assert _case_count(member_api) == before, "rejected case leaked"


def test_explicit_team_id_resolves_the_ambiguity(member_api, scorer, teams):
    if _team_ids(member_api):
        pytest.skip("member account already belongs to a team")

    first, second = teams(session=member_api), teams(session=member_api)
    case = _create(
        member_api,
        f"{BASE_URL}/case/",
        {
            "name": unique("case-explicit"),
            "scorer_id": scorer["id"],
            "team_id": second["id"],
        },
    )
    try:
        assert case["id"] in _shared_case_ids(member_api, second["id"])
        assert case["id"] not in _shared_case_ids(member_api, first["id"])
    finally:
        _discard(member_api, f"{BASE_URL}/case/{case['id']}/")


def test_team_id_the_caller_is_not_in_is_400(member_api, scorer, teams):
    not_mine = teams()

    before = _case_count(member_api)
    response = member_api.post(
        f"{BASE_URL}/case/",
        json={
            "name": unique("case-foreign-team"),
            "scorer_id": scorer["id"],
            "team_id": not_mine["id"],
        },
        timeout=30,
    )
    assert response.status_code == 400
    assert "not a member" in response.text
    assert _case_count(member_api) == before, "rejected case leaked"


def test_team_id_zero_opts_out_of_sharing(member_api, scorer, teams):
    """The escape hatch: belonging to a team must not force every case into it.

    Quepid creates every case unshared, so an API that cannot do the same would
    have taken a capability away from anyone in exactly one team.
    """
    if _team_ids(member_api):
        pytest.skip("member account already belongs to a team")

    only = teams(session=member_api)
    case = _create(
        member_api,
        f"{BASE_URL}/case/",
        {"name": unique("case-optout"), "scorer_id": scorer["id"], "team_id": 0},
    )
    try:
        assert case["id"] not in _shared_case_ids(member_api, only["id"])
    finally:
        _discard(member_api, f"{BASE_URL}/case/{case['id']}/")


def test_team_id_zero_opts_out_even_with_several_teams(member_api, scorer, teams):
    """...and does so without tripping the ambiguity check."""
    if _team_ids(member_api):
        pytest.skip("member account already belongs to a team")

    first, second = teams(session=member_api), teams(session=member_api)
    case = _create(
        member_api,
        f"{BASE_URL}/case/",
        {"name": unique("case-optout"), "scorer_id": scorer["id"], "team_id": 0},
    )
    try:
        assert case["id"] not in _shared_case_ids(member_api, first["id"])
        assert case["id"] not in _shared_case_ids(member_api, second["id"])
    finally:
        _discard(member_api, f"{BASE_URL}/case/{case['id']}/")


def test_unknown_team_id_is_400(api, scorer):
    response = api.post(
        f"{BASE_URL}/case/",
        json={
            "name": unique("case-unknown-team"),
            "scorer_id": scorer["id"],
            "team_id": 999999999,
        },
        timeout=30,
    )
    assert response.status_code == 400


# --- authentication ----------------------------------------------------------

def test_team_cases_require_authentication(live_stack, ):
    assert requests.get(f"{BASE_URL}/teams/1/cases/", timeout=10).status_code == 401
