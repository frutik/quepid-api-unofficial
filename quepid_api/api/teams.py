import logging
from ninja import Router
from django.db import transaction
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Team
from typing import List
from ninja.pagination import paginate
from ninja import Schema
from .utils import _by_pk

logger = logging.getLogger(__name__)

router = Router(tags=["Teams management"])


class CreateTeam(Schema):
    name: str


class UpdateTeam(Schema):
    name: str


@router.get("/", response=List[Team])
@paginate
def view_teams(request):
    return qmodels.Teams.objects \
        .using('quepid') \
        .all()
    
    
@router.get("/{id}/", response={200: Team, 404: None})
def view_team(request, id: int):
    if r := _by_pk(qmodels.Teams, id):
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
        team = _by_pk(qmodels.Teams, id)
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
    team = _by_pk(qmodels.Teams, id)
    if not team:
        return 404, None

    # teams_members, teams_cases and teams_scorers hold FKs onto teams, and the
    # reflected models use DO_NOTHING, so Django will not cascade for us.
    with transaction.atomic(using='quepid'):
        for join in (qmodels.TeamsMembers, qmodels.TeamsCases, qmodels.TeamsScorers):
            join.objects.using('quepid').filter(team_id=team.id).delete()
        team.delete(using='quepid')
    return 204, None
