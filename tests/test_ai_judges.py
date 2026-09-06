"""AI judges -- ``/api/ai_judges/``.

An AI judge is not a record type. It is a row in ``users`` whose ``llm_key`` is
not null, which is exactly how Quepid tells them apart (``User.only_ai_judges``
is ``where.not(llm_key: nil)``). That makes these tests unusual in one respect:
most of them exist to prove the router stays on its side of a table it shares
with every human account on the installation.
"""
import pytest

from conftest import BASE_URL, fk_id, unique


def judges_url(judge=None, suffix=""):
    if judge is None:
        return f"{BASE_URL}/ai_judges/"
    return f"{BASE_URL}/ai_judges/{judge['id']}/{suffix}"


def test_a_judge_is_created_on_its_team(api, team):
    response = api.post(
        judges_url(),
        json={"name": unique("judge"), "llm_key": "sk-x", "team_id": team["id"]},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"]

    # Deleted here rather than left to the team fixture: tearing down the team
    # only removes the teams_members row, and a judge with no team is
    # unreachable through this router by design -- so a leak here is a row
    # nothing can clean up afterwards.
    api.delete(judges_url(response.json()), timeout=10)


def test_a_judge_is_readable_and_listed(api, ai_judge):
    read = api.get(judges_url(ai_judge), timeout=10)
    assert read.status_code == 200, read.text
    assert read.json()["name"] == ai_judge["name"]

    listed = api.get(judges_url(), timeout=10).json()["items"]
    assert ai_judge["id"] in [row["id"] for row in listed]


def test_the_key_is_never_returned(api, ai_judge):
    """It is a paid LLM credential, which Rails encrypts at rest.

    Accepted on the way in, absent on the way out -- from the create response,
    the read and the listing alike.
    """
    assert "llm_key" not in ai_judge

    assert "llm_key" not in api.get(judges_url(ai_judge), timeout=10).json()

    listed = api.get(judges_url(), timeout=10).json()["items"]
    for row in listed:
        assert "llm_key" not in row


def test_no_login_columns_are_exposed(api, ai_judge):
    """``users`` is the login table; a judge response is not a user dump."""
    for column in ("email", "password", "administrator", "invitation_token",
                   "reset_password_token"):
        assert column not in ai_judge


def test_the_default_prompt_asks_for_zero_to_three(ai_judge):
    """Omitting system_prompt gets Quepid's own DEFAULT_SYSTEM_PROMPT.

    This text, not ``books.scale``, is what puts a judge on a 0-3 scale:
    ``LlmService#make_user_prompt`` sends the query and the document fields and
    nothing else, so the rating instruction has nowhere else to come from.
    """
    assert "scale of 0 to 3" in ai_judge["system_prompt"]
    assert '"judgment"' in ai_judge["system_prompt"]


def test_a_prompt_can_be_given_instead(api, team):
    prompt = "Rate 0 or 1. 1 means the document is about the query."
    response = api.post(
        judges_url(),
        json={
            "name": unique("judge"),
            "llm_key": "sk-x",
            "system_prompt": prompt,
            "team_id": team["id"],
        },
        timeout=10,
    )
    assert response.status_code == 200, response.text
    judge = response.json()
    assert judge["system_prompt"] == prompt
    api.delete(judges_url(judge), timeout=10)


def test_judge_options_default_to_the_ones_quepid_offers(ai_judge):
    options = ai_judge["judge_options"]
    assert options["llm_provider"] == "openai"
    assert options["llm_service_url"] == "https://api.openai.com"
    assert options["llm_model"] == "gpt-4o"
    assert options["llm_timeout"] == 30


def test_judge_options_given_at_create_merge_over_the_defaults(api, team):
    """Naming one option keeps the rest, so a caller need not restate them."""
    response = api.post(
        judges_url(),
        json={
            "name": unique("judge"),
            "llm_key": "sk-x",
            "team_id": team["id"],
            "judge_options": {"llm_model": "gpt-4o-mini"},
        },
        timeout=10,
    )
    assert response.status_code == 200, response.text
    judge = response.json()
    assert judge["judge_options"]["llm_model"] == "gpt-4o-mini"
    assert judge["judge_options"]["llm_provider"] == "openai"
    api.delete(judges_url(judge), timeout=10)


def test_a_judge_without_a_key_is_refused(api, team):
    """Without one it is not a judge at all -- it is a passwordless account."""
    response = api.post(
        judges_url(),
        json={"name": unique("judge"), "llm_key": "   ", "team_id": team["id"]},
        timeout=10,
    )
    assert response.status_code == 400, response.text
    assert "llm_key" in response.json()


def test_a_judge_without_a_name_is_refused(api, team):
    response = api.post(
        judges_url(),
        json={"name": "  ", "llm_key": "sk-x", "team_id": team["id"]},
        timeout=10,
    )
    assert response.status_code == 400, response.text


def test_a_missing_name_is_a_schema_error(api, team):
    response = api.post(
        judges_url(), json={"llm_key": "sk-x", "team_id": team["id"]}, timeout=10
    )
    assert response.status_code == 422, response.text


def test_a_judge_on_a_team_you_are_not_in_is_refused(api):
    response = api.post(
        judges_url(),
        json={"name": unique("judge"), "llm_key": "sk-x", "team_id": 10 ** 9},
        timeout=10,
    )
    assert response.status_code == 400, response.text
    assert "team" in response.json().lower()


def test_a_human_account_is_not_reachable_as_a_judge(api, case):
    """The router must never touch a login account.

    ``case`` is owned by the caller, so its owner id is a real user row that
    certainly exists -- and every judge endpoint should still answer 404 for it,
    because ``llm_key`` is null there. Without this, a typo'd id could rename or
    delete a colleague's account.
    """
    owner_id = fk_id(case, "owner")
    url = f"{BASE_URL}/ai_judges/{owner_id}/"

    assert api.get(url, timeout=10).status_code == 404
    assert api.put(url, json={"name": "hijacked"}, timeout=10).status_code == 404
    assert api.delete(url, timeout=10).status_code == 404


def test_an_unknown_judge_is_404(api):
    assert api.get(f"{BASE_URL}/ai_judges/{10 ** 9}/", timeout=10).status_code == 404


def test_a_judge_can_be_renamed_and_reprompted(api, ai_judge):
    name = unique("judge")
    response = api.put(
        judges_url(ai_judge),
        json={"name": name, "system_prompt": "Rate everything 3."},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == name
    assert response.json()["system_prompt"] == "Rate everything 3."


def test_updating_one_field_leaves_the_others(api, ai_judge):
    response = api.put(judges_url(ai_judge), json={"name": unique("judge")}, timeout=10)
    assert response.status_code == 200, response.text
    assert response.json()["system_prompt"] == ai_judge["system_prompt"]
    assert response.json()["judge_options"] == ai_judge["judge_options"]


def test_update_replaces_judge_options_wholesale(api, ai_judge):
    """Not merged -- Rails' ``judge_options=`` overwrites the key outright.

    Documented by this test rather than fixed, because merging would leave a
    caller no way to *remove* an option they had set.
    """
    response = api.put(
        judges_url(ai_judge),
        json={"judge_options": {"llm_model": "claude-opus-5"}},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert response.json()["judge_options"] == {"llm_model": "claude-opus-5"}


def test_a_key_can_be_rotated(api, ai_judge):
    """Write-only, so the only observable is that the update is accepted."""
    response = api.put(judges_url(ai_judge), json={"llm_key": "sk-rotated"}, timeout=10)
    assert response.status_code == 200, response.text
    assert "llm_key" not in response.json()


def test_a_blank_key_cannot_be_written_over_a_good_one(api, ai_judge):
    response = api.put(judges_url(ai_judge), json={"llm_key": "  "}, timeout=10)
    assert response.status_code == 400, response.text


def test_a_judge_is_really_deleted(api, team):
    """A real delete, unlike ``DELETE /case/{id}/``, which only archives."""
    judge = api.post(
        judges_url(),
        json={"name": unique("judge"), "llm_key": "sk-x", "team_id": team["id"]},
        timeout=10,
    ).json()

    assert api.delete(judges_url(judge), timeout=10).status_code == 204
    assert api.get(judges_url(judge), timeout=10).status_code == 404


def test_deleting_a_judge_leaves_its_team_standing(api, team):
    judge = api.post(
        judges_url(),
        json={"name": unique("judge"), "llm_key": "sk-x", "team_id": team["id"]},
        timeout=10,
    ).json()
    api.delete(judges_url(judge), timeout=10)

    assert api.get(f"{BASE_URL}/teams/{team['id']}/", timeout=10).status_code == 200


def test_a_judge_can_be_attached_to_a_book(api, ai_judge, book):
    """Team membership is not enough: ``run_judge_judy`` reads ``@book.ai_judges``."""
    response = api.post(
        judges_url(ai_judge, "books/"), json={"book_id": book["id"]}, timeout=10
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == book["id"]

    attached = api.get(judges_url(ai_judge, "books/"), timeout=10).json()
    assert [row["id"] for row in attached] == [book["id"]]


def test_attaching_twice_does_not_duplicate(api, ai_judge, book):
    """``books_ai_judges`` is uniquely indexed on (book_id, user_id)."""
    for _ in range(2):
        response = api.post(
            judges_url(ai_judge, "books/"), json={"book_id": book["id"]}, timeout=10
        )
        assert response.status_code == 200, response.text

    attached = api.get(judges_url(ai_judge, "books/"), timeout=10).json()
    assert len(attached) == 1


def test_a_judge_starts_attached_to_nothing(api, ai_judge):
    assert api.get(judges_url(ai_judge, "books/"), timeout=10).json() == []


def test_a_judge_can_be_detached(api, ai_judge, book):
    api.post(judges_url(ai_judge, "books/"), json={"book_id": book["id"]}, timeout=10)

    response = api.delete(judges_url(ai_judge, f"books/{book['id']}/"), timeout=10)
    assert response.status_code == 204, response.text
    assert api.get(judges_url(ai_judge, "books/"), timeout=10).json() == []


def test_detaching_a_book_that_was_never_attached_is_404(api, ai_judge, book):
    response = api.delete(judges_url(ai_judge, f"books/{book['id']}/"), timeout=10)
    assert response.status_code == 404


def test_detaching_leaves_the_book_itself(api, ai_judge, book):
    api.post(judges_url(ai_judge, "books/"), json={"book_id": book["id"]}, timeout=10)
    api.delete(judges_url(ai_judge, f"books/{book['id']}/"), timeout=10)

    assert api.get(f"{BASE_URL}/books/{book['id']}", timeout=10).status_code == 200


def test_a_judge_cannot_be_attached_to_an_unknown_book(api, ai_judge):
    response = api.post(
        judges_url(ai_judge, "books/"), json={"book_id": 10 ** 9}, timeout=10
    )
    assert response.status_code == 400, response.text


def test_deleting_an_attached_judge_leaves_the_book(api, team, book):
    """The join row goes; the book does not.

    ``books_ai_judges`` carries a foreign key onto ``books`` but none onto
    ``users``, so nothing in MySQL would stop the delete from leaving a book
    pointing at a judge that is gone -- ``delete_ai_judge`` clears it itself.
    """
    judge = api.post(
        judges_url(),
        json={"name": unique("judge"), "llm_key": "sk-x", "team_id": team["id"]},
        timeout=10,
    ).json()
    api.post(judges_url(judge, "books/"), json={"book_id": book["id"]}, timeout=10)

    assert api.delete(judges_url(judge), timeout=10).status_code == 204
    assert api.get(f"{BASE_URL}/books/{book['id']}", timeout=10).status_code == 200


def test_a_stranger_cannot_see_the_judge(member_api, ai_judge):
    assert member_api.get(judges_url(ai_judge), timeout=10).status_code == 404


def test_a_stranger_cannot_change_or_delete_the_judge(member_api, ai_judge):
    url = judges_url(ai_judge)
    assert member_api.put(url, json={"name": "hijacked"}, timeout=10).status_code == 404
    assert member_api.delete(url, timeout=10).status_code == 404


def test_a_stranger_cannot_attach_the_judge_to_anything(member_api, ai_judge, book):
    response = member_api.post(
        judges_url(ai_judge, "books/"), json={"book_id": book["id"]}, timeout=10
    )
    assert response.status_code == 404


def test_a_stranger_does_not_see_the_judge_listed(member_api, ai_judge):
    listed = member_api.get(judges_url(), timeout=10).json()["items"]
    assert ai_judge["id"] not in [row["id"] for row in listed]


# Not covered here: deleting a judge that has already rated something, which
# ``delete_ai_judge`` refuses with 400 to match Rails' ``has_many :judgements,
# dependent: :restrict_with_error``. Reaching it needs a judgement, and
# judgements are not writable over this API -- the same gap noted at the end of
# tests/test_books.py. Verified by hand instead: with one judgement present the
# delete answers 400 and names the count, and the judge is still readable
# afterwards.
