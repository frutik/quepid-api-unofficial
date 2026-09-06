from ninja.security import HttpBearer


import quepid.models as qmodels
from common.auth import user_from_token


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        # ninja has already stripped the "Bearer " prefix; the lookup itself
        # lives in common.auth so the MCP endpoint shares this exact path.
        return user_from_token(token)


def _by_pk(cls, pk):
    return cls.objects.\
        using('quepid')\
        .filter(pk=pk)\
        .first()


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
