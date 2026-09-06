import logging

from ninja import Router
from django.db import transaction
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import AiJudge, Book
from typing import List
from ninja.pagination import paginate
from ninja import Schema

from .books import _reachable_book
from .utils import _member_teams, _team_for_new_row


logger = logging.getLogger(__name__)

router = Router(tags=["AI judges management"])


#: What Quepid puts in the box when you click "Create AI Judge" -- copied from
#: ``AiJudgesController::DEFAULT_SYSTEM_PROMPT`` so a judge made here rates the
#: same way as one made in the UI. This, not ``books.scale``, is what tells the
#: LLM to answer 0-3: ``LlmService#make_user_prompt`` sends only the query and
#: the document fields, so every instruction the model gets is in this text.
DEFAULT_SYSTEM_PROMPT = """You are evaluating the results from a search engine. For each query, you will be provided with multiple documents. Your task is to evaluate each document and assign a judgment on a scale of 0 to 3, where:
- 0 indicates the document is irrelevant to the query.
- 1 indicates the document is somewhat relevant to the query.
- 2 indicates the document is mostly relevant to the query.
- 3 indicates the document is perfectly relevant to the query.

For each document, provide:
1. An explanation of the judgment.
2. The judgment value.

The response should be in the following JSON format:
{
  "explanation": "Your detailed reasoning behind the judgment",
  "judgment": <numeric value>
}

Here is an example:
User:
Query: Farm animals

doc1:
  title: All about farm animals
  abstract: This document is all about farm animals
Assistant:
{
  "explanation": "This document appears to perfectly respond to the user's query",
  "judgment": 3
}

User:
Query: Farm animals

doc2:
  title: Somewhat about farm animals
  abstract: This document somewhat talks about farm animals
Assistant:
{
  "explanation": "This document is somewhat relevant to the user's query",
  "judgment": 1
}

User:
Query: Farm animals

doc3:
  title: This document has nothing to do with farm animals
  abstract: We will talk about everything except for farm animals.
Assistant:
{
  "explanation": "This document is not relevant at all to the user's query",
  "judgment": 0
}
"""

#: Also from the controller, its ``new`` action. Sent to the LLM by
#: ``LlmService``, which reads ``llm_service_url`` and ``llm_model`` off here.
DEFAULT_JUDGE_OPTIONS = {
    'llm_provider':    'openai',
    'llm_service_url': 'https://api.openai.com',
    'llm_model':       'gpt-4o',
    'llm_timeout':     30,
    'llm_api_version': '',
}

#: Rails caps the key at 255 even though the column takes 4000, and the prompt
#: at the column width. Checked here because ``managed = False`` means none of
#: those validations run on this side of the wire.
MAX_NAME = 255
MAX_LLM_KEY = 255
MAX_SYSTEM_PROMPT = 4000


class CreateAiJudge(Schema):
    name: str
    #: The LLM provider's API key. Required: it is what makes this row a judge
    #: rather than an ordinary user, so a judge without one cannot exist.
    #: Accepted, never returned -- see the AiJudge schema.
    llm_key: str
    #: Defaults to DEFAULT_SYSTEM_PROMPT, which asks for 0-3 ratings.
    system_prompt: str = None
    #: Merged over DEFAULT_JUDGE_OPTIONS, so passing just {"llm_model": ...}
    #: keeps the rest.
    judge_options: dict = None
    #: The team to put the judge on. Omitted, it is resolved from the caller's
    #: memberships the way a new case or book is (see ``_team_for_new_row``) --
    #: but unlike those, a judge with no team at all is refused: see create.
    team_id: int = None


class UpdateAiJudge(Schema):
    name: str = None
    llm_key: str = None
    system_prompt: str = None
    #: Replaces the stored options wholesale, as Rails' ``judge_options=``
    #: does -- not merged, so a partial dict drops the keys you leave out.
    judge_options: dict = None


class AttachBook(Schema):
    book_id: int


def _judges():
    """Every AI judge there is.

    ``llm_key IS NOT NULL`` is not a heuristic -- it is Quepid's own
    definition, in ``User.only_ai_judges`` and ``User#ai_judge?``. Running
    every query in this router through here is also what keeps it away from
    human accounts: ``users`` is the login table, and a judge row is the only
    kind of row this API has any business writing to it.
    """
    return qmodels.Users.objects \
        .using('quepid') \
        .exclude(llm_key__isnull=True)


def _my_judges(user):
    """Judges the caller can see: those on a team the caller belongs to.

    A judge has no owner column, so team membership is the only access there
    is -- the same rule ``AiJudgesController#set_ai_judge`` applies when it
    looks one up through ``@team.members.only_ai_judges``.
    """
    on_my_teams = qmodels.TeamsMembers.objects \
        .using('quepid') \
        .filter(team_id__in=_member_teams(user).values('id')) \
        .values('member_id')

    return _judges() \
        .filter(id__in=on_my_teams) \
        .order_by('id')


def _reachable_judge(user, judge_id):
    return _my_judges(user).filter(pk=judge_id).first()


def _invalid(name, llm_key, system_prompt):
    """Whatever Rails would reject about these values, as a message, or None."""
    if name is not None and not name.strip():
        return 'A judge needs a name.'
    if name is not None and len(name) > MAX_NAME:
        return f'Name is longer than {MAX_NAME} characters.'
    if llm_key is not None and not llm_key.strip():
        return 'A judge needs an llm_key -- it is what makes it a judge.'
    if llm_key is not None and len(llm_key) > MAX_LLM_KEY:
        return f'llm_key is longer than {MAX_LLM_KEY} characters.'
    if system_prompt is not None and not system_prompt.strip():
        return 'A judge needs a system_prompt.'
    if system_prompt is not None and len(system_prompt) > MAX_SYSTEM_PROMPT:
        return f'system_prompt is longer than {MAX_SYSTEM_PROMPT} characters.'
    return None


def _store_judge_options(judge, judge_options):
    """Put judge_options back where Rails keeps it: inside the options JSON.

    Mirrors ``User#judge_options=``, which merges the key into ``options``
    rather than replacing the whole column -- anything else Quepid stores
    there stays.
    """
    options = dict(judge.options or {})
    options['judge_options'] = judge_options
    judge.options = options


@router.get("/", response=List[AiJudge])
@paginate
def view_ai_judges(request):
    """List the AI judges on the caller's teams"""
    return _my_judges(request.auth)


@router.get("/{id}/", response={200: AiJudge, 404: None})
def view_ai_judge(request, id: int):
    # 404, not 403, for a judge on someone else's team -- the same reticence
    # view_team shows about teams the caller is not in.
    if judge := _reachable_judge(request.auth, id):
        return 200, judge
    return 404, None


@router.post("/", response={200: AiJudge, 400: str})
def create_ai_judge(request, data: CreateAiJudge):
    """Create an AI judge and put it on one of the caller's teams.

    The row goes in ``users``: an AI judge is a user whose ``llm_key`` is set,
    not a record of its own. Email and password stay null, which Rails allows
    precisely here -- both validations carry ``unless: :ai_judge?`` -- so the
    account this creates cannot be signed in to.
    """
    try:
        # Resolved first, so a judge is never created without somewhere to
        # live. Unlike a case or a book, an unteamed judge is not merely
        # unshared: team membership is the only way anything reaches a judge,
        # so one with no team would be invisible to this API the moment it was
        # created -- unlistable, unreadable, undeletable.
        team, team_error = _team_for_new_row(request.auth, data.team_id)
        if team_error:
            return 400, team_error
        if not team:
            return 400, ('A judge must belong to a team, and you are not in one. '
                         'Create a team first, then pass its team_id.')

        system_prompt = data.system_prompt
        if system_prompt is None:
            system_prompt = DEFAULT_SYSTEM_PROMPT

        if error := _invalid(data.name, data.llm_key, system_prompt):
            return 400, error

        now = timezone.now()
        with transaction.atomic(using='quepid'):
            judge = qmodels.Users.objects.using('quepid').create(
                name=data.name,
                # Written in the clear. Rails declares ``encrypts :llm_key``,
                # but ``config.active_record.encryption.support_unencrypted_data``
                # is true (config/application.rb), so it reads a plaintext
                # value back unchanged rather than failing to decrypt it.
                llm_key=data.llm_key,
                system_prompt=system_prompt,
                options={'judge_options': {**DEFAULT_JUDGE_OPTIONS,
                                           **(data.judge_options or {})}},
                created_at=now,
                updated_at=now,
                # NOT NULL without a Django-side default, so they have to be
                # named here. num_logins mirrors User#set_defaults; the rest of
                # what that callback does is a default scorer, which the
                # DefaultScorerExistsValidator explicitly allows to be blank
                # and which a judge -- who never opens a case -- never uses.
                email_marketing=0,
                completed_case_wizard=0,
                num_logins=0,
            )
            qmodels.TeamsMembers.objects.using('quepid').create(
                member=judge,
                team=team
            )
        return judge
    except Exception as e:
        return 400, str(e)


@router.put("/{id}/", response={200: AiJudge, 404: None, 400: str})
def update_ai_judge(request, id: int, data: UpdateAiJudge):
    """Update an AI judge. Its team membership is not changed here."""
    try:
        judge = _reachable_judge(request.auth, id)
        if not judge:
            return 404, None

        if error := _invalid(data.name, data.llm_key, data.system_prompt):
            return 400, error

        if data.name is not None:
            judge.name = data.name
        if data.llm_key is not None:
            judge.llm_key = data.llm_key
        if data.system_prompt is not None:
            judge.system_prompt = data.system_prompt
        if data.judge_options is not None:
            _store_judge_options(judge, data.judge_options)

        judge.updated_at = timezone.now()
        judge.save(using='quepid')
        return 200, judge
    except Exception as e:
        return 400, str(e)


@router.delete("/{id}/", response={204: None, 404: None, 400: str})
def delete_ai_judge(request, id: int):
    """Delete an AI judge, unless it has already rated something.

    A real delete, not the archiving ``DELETE /case/{id}/`` does -- Rails
    destroys the row too. The refusal mirrors ``has_many :judgements,
    dependent: :restrict_with_error``: nothing in MySQL protects those rows,
    since ``judgements.user_id`` carries no foreign key, so deleting a judge
    that has worked would silently orphan every rating it produced.
    """
    judge = _reachable_judge(request.auth, id)
    if not judge:
        return 404, None

    judged = qmodels.Judgements.objects \
        .using('quepid') \
        .filter(user_id=judge.id) \
        .count()
    if judged:
        return 400, (f'This judge has made {judged} judgement(s), which would be '
                     f'orphaned. Delete them, or the books holding them, first.')

    with transaction.atomic(using='quepid'):
        # teams_members holds a real FK onto users, so MySQL refuses the delete
        # until this row is gone. books_ai_judges has an FK to books only, but
        # leaving its rows behind would point a book at a judge that no longer
        # exists.
        qmodels.TeamsMembers.objects.using('quepid').filter(member_id=judge.id).delete()
        qmodels.BooksAiJudges.objects.using('quepid').filter(user_id=judge.id).delete()
        judge.delete(using='quepid')
    return 204, None


@router.get("/{id}/books/", response={200: List[Book], 404: None})
def view_ai_judge_books(request, id: int):
    """List the books this judge is attached to"""
    judge = _reachable_judge(request.auth, id)
    if not judge:
        return 404, None

    attached = qmodels.BooksAiJudges.objects \
        .using('quepid') \
        .filter(user_id=judge.id) \
        .values('book_id')

    return 200, qmodels.Books.objects \
        .using('quepid') \
        .filter(id__in=attached) \
        .order_by('id')


@router.post("/{id}/books/", response={200: Book, 404: None, 400: str})
def attach_ai_judge_to_book(request, id: int, data: AttachBook):
    """Attach a judge to a book, so it can be asked to judge that book.

    Being on the same team is not enough: Quepid's own "Run Judge Judy" reads
    ``@book.ai_judges``, which is this join table, so a judge that is not
    attached here cannot be picked for the book at all.

    Idempotent -- ``books_ai_judges`` is uniquely indexed on (book_id, user_id),
    so a second attach is a no-op rather than a duplicate-key error.
    """
    judge = _reachable_judge(request.auth, id)
    if not judge:
        return 404, None

    book = _reachable_book(request.auth, data.book_id)
    if not book:
        return 400, 'Unknown book, or not yours to use.'

    already_attached = qmodels.BooksAiJudges.objects \
        .using('quepid') \
        .filter(book_id=book.id) \
        .filter(user_id=judge.id) \
        .exists()
    if not already_attached:
        now = timezone.now()
        qmodels.BooksAiJudges.objects.using('quepid').create(
            book_id=book.id,
            user_id=judge.id,
            created_at=now,
            updated_at=now
        )
    return 200, book


@router.delete("/{id}/books/{book_id}/", response={204: None, 404: None})
def detach_ai_judge_from_book(request, id: int, book_id: int):
    """Detach a judge from a book. Judgements it already made are kept."""
    judge = _reachable_judge(request.auth, id)
    if not judge:
        return 404, None

    deleted, _ = qmodels.BooksAiJudges.objects \
        .using('quepid') \
        .filter(book_id=book_id) \
        .filter(user_id=judge.id) \
        .delete()
    return (204, None) if deleted else (404, None)
