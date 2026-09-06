import logging
from ninja import Router
from django.db import transaction
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Team
from typing import List
from ninja.pagination import paginate
from ninja import Schema

logger = logging.getLogger(__name__)

router = Router(tags=["Teams management"])


class CreateTeam(Schema):
    name: str


class UpdateTeam(Schema):
    name: str


def _member_teams(user):
    """Teams the caller belongs to.

    Quepid has no owner column on teams, so a row in teams_members is the only
    notion of access to a team there is -- the same rule the MCP layer applies
    in ``quepid_mcp.mcp._team_ids``. Ordered so ``@paginate`` gets a stable
    sequence to slice.
    """
    member_of = qmodels.TeamsMembers.objects \
        .using('quepid') \
        .filter(member_id=user.id) \
        .values('team_id')

    return qmodels.Teams.objects \
        .using('quepid') \
        .filter(id__in=member_of) \
        .order_by('id')


def _member_team(user, id):
    """One team, but only if the caller is a member of it."""
    return _member_teams(user).filter(pk=id).first()


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
        team.delete(using='quepid')
    return 204, None
