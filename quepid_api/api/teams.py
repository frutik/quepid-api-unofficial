import logging
from ninja import Router
from django.db import connections, transaction
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Book, Case, Team
from typing import List
from ninja.pagination import paginate
from ninja import Schema
from .utils import _member_team, _member_teams

logger = logging.getLogger(__name__)

router = Router(tags=["Teams management"])


class CreateTeam(Schema):
    name: str


class UpdateTeam(Schema):
    name: str


class ShareCase(Schema):
    case_id: int


class ShareBook(Schema):
    book_id: int


def _shared_book_ids(team):
    """Ids of the books shared with a team, read without touching a primary key.

    ``teams_books`` has no primary key -- unlike ``teams_cases`` and
    ``teams_members``, which declare composite ones -- so ``inspectdb`` gives
    ``TeamsBooks`` Django's implicit ``id`` AutoField, naming a column that does
    not exist. Any query selecting or deleting by pk dies on
    ``Unknown column 'teams_books.id'``: that rules out ``.all()``, ``.get()``,
    slicing the model queryset, and ``.delete()``. ``.values()`` and ``.exists()``
    name their columns and are safe, so reads go through here and the delete
    goes through raw SQL.
    """
    return qmodels.TeamsBooks.objects \
        .using('quepid') \
        .filter(team_id=team.id) \
        .values('book_id')


@router.get("/", response=List[Team])
@paginate
def view_teams(request):
    """List the teams the calling user is a member of"""
    return _member_teams(request.auth)
    
    
@router.get("/{id}/", response={200: Team, 404: None})
def view_team(request, id: int):
    # 404 rather than 403 for a team the caller is not in: whether some other
    # user's team exists is not theirs to learn.
    if r := _member_team(request.auth, id):
        return 200, r
    return 404, None
    
    
@router.post("/", response={200: Team, 400: str})
def create_team(request, data: CreateTeam):
    """Create a new team, with the calling user as its first member"""
    try:
        now = timezone.now()
        with transaction.atomic(using='quepid'):
            team = qmodels.Teams.objects.using('quepid').create(
                name=data.name,
                created_at=now,
                updated_at=now
            )
            # Quepid has no owner column on teams -- a team is reachable only
            # through teams_members. Without this row the team exists but is
            # invisible to everyone, including in the UI's Share case dialog.
            qmodels.TeamsMembers.objects.using('quepid').create(
                member=request.auth,
                team=team
            )
        return team
    except Exception as e:
        return 400, str(e)
        
        
@router.get("/{id}/cases/", response={200: List[Case], 404: None})
def view_team_cases(request, id: int):
    """List the cases shared with a team the caller belongs to"""
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    shared = qmodels.TeamsCases.objects \
        .using('quepid') \
        .filter(team_id=team.id) \
        .values('case_id')

    return 200, qmodels.Cases.objects \
        .using('quepid') \
        .filter(id__in=shared) \
        .order_by('id')


@router.post("/{id}/cases/", response={200: Case, 404: None, 400: str})
def share_case_with_team(request, id: int, data: ShareCase):
    """Share one of the caller's own cases with a team they belong to.

    This writes the teams_cases row behind the UI's "Share case" dialog and its
    "Associated Teams" column. Creating a team and a case through the API
    leaves the two unconnected until something links them here.

    Idempotent: sharing an already-shared case is a no-op, not a duplicate-key
    error, since teams_cases is keyed on (case_id, team_id).
    """
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    # Deliberately owner-only: being able to see a case because someone else
    # shared it with you is not a licence to hand it to further teams.
    case = qmodels.Cases.objects \
        .using('quepid') \
        .filter(pk=data.case_id) \
        .filter(owner_id=request.auth.id) \
        .first()
    if not case:
        return 400, 'Unknown case, or not owned by you.'

    already_shared = qmodels.TeamsCases.objects \
        .using('quepid') \
        .filter(team_id=team.id) \
        .filter(case_id=case.id) \
        .exists()
    if not already_shared:
        qmodels.TeamsCases.objects.using('quepid').create(team=team, case=case)
    return 200, case


@router.delete("/{id}/cases/{case_id}/", response={204: None, 404: None})
def unshare_case_from_team(request, id: int, case_id: int):
    """Stop sharing a case with a team, leaving the case itself untouched"""
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    deleted, _ = qmodels.TeamsCases.objects \
        .using('quepid') \
        .filter(team_id=team.id) \
        .filter(case_id=case_id) \
        .delete()
    return (204, None) if deleted else (404, None)


@router.get("/{id}/books/", response={200: List[Book], 404: None})
def view_team_books(request, id: int):
    """List the books shared with a team the caller belongs to"""
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    return 200, qmodels.Books.objects \
        .using('quepid') \
        .filter(id__in=_shared_book_ids(team)) \
        .order_by('id')


@router.post("/{id}/books/", response={200: Book, 404: None, 400: str})
def share_book_with_team(request, id: int, data: ShareBook):
    """Share one of the caller's own books with a team they belong to.

    Idempotent, like the case equivalent -- though for a different reason:
    ``teams_books`` carries no unique key at all, so a re-share would silently
    duplicate the row rather than fail.
    """
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    book = qmodels.Books.objects \
        .using('quepid') \
        .filter(pk=data.book_id) \
        .filter(owner_id=request.auth.id) \
        .first()
    if not book:
        return 400, 'Unknown book, or not owned by you.'

    already_shared = qmodels.TeamsBooks.objects \
        .using('quepid') \
        .filter(team_id=team.id) \
        .filter(book_id=book.id) \
        .exists()
    if not already_shared:
        qmodels.TeamsBooks.objects.using('quepid').create(
            book_id=book.id,
            team_id=team.id
        )
    return 200, book


@router.delete("/{id}/books/{book_id}/", response={204: None, 404: None})
def unshare_book_from_team(request, id: int, book_id: int):
    """Stop sharing a book with a team, leaving the book itself untouched"""
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    if not qmodels.TeamsBooks.objects \
            .using('quepid') \
            .filter(team_id=team.id) \
            .filter(book_id=book_id) \
            .exists():
        return 404, None

    # Raw SQL, unlike the teams_cases equivalent: see _shared_book_ids.
    with connections['quepid'].cursor() as cursor:
        cursor.execute(
            'DELETE FROM teams_books WHERE team_id = %s AND book_id = %s',
            [team.id, book_id],
        )
    return 204, None


@router.put("/{id}/", response={200: Team, 404: None, 400: str})
def update_team(request, id: int, data: UpdateTeam):
    """Update an existing team"""
    try:
        team = _member_team(request.auth, id)
        if not team:
            return 404, None

        team.name = data.name
        team.updated_at = timezone.now()
        team.save(using='quepid')
        return 200, team
    except Exception as e:
        return 400, str(e)
        
        
@router.delete("/{id}/", response={204: None, 404: None})
def delete_team(request, id: int):
    """Delete an existing team"""
    team = _member_team(request.auth, id)
    if not team:
        return 404, None

    # teams_members, teams_cases and teams_scorers hold FKs onto teams, and the
    # reflected models use DO_NOTHING, so Django will not cascade for us.
    with transaction.atomic(using='quepid'):
        for join in (qmodels.TeamsMembers, qmodels.TeamsCases, qmodels.TeamsScorers):
            join.objects.using('quepid').filter(team_id=team.id).delete()
        # teams_books has no FK to block the delete, but leaving its rows behind
        # would hand a later team the books of a deleted one. Raw SQL because it
        # has no primary key either -- see _shared_book_ids.
        with connections['quepid'].cursor() as cursor:
            cursor.execute('DELETE FROM teams_books WHERE team_id = %s', [team.id])
        team.delete(using='quepid')
    return 204, None
