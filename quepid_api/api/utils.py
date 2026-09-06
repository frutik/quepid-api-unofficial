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


def _team_for_new_row(user, team_id):
    """Decide which team a new case or book should be shared with.

    Returns ``(team, error)``. An explicit ``team_id`` wins, provided the caller
    is in that team. Otherwise a caller who belongs to exactly one team gets
    that one automatically -- the common case, and the one the UI's sharing
    dialog would otherwise have to be used for. A caller in no team gets an
    unshared case, which is what Quepid does by default anyway. A caller in
    several is asked to say which, because guessing would silently expose the
    row to the wrong people.

    ``team_id = 0`` means "no team, deliberately". Without it, automatic
    association would leave a caller who belongs to a team no way to create an
    unshared row at all, which is a capability Quepid itself has: everything
    starts unshared until somebody shares it.
    """
    teams = _member_teams(user)

    if team_id == 0:
        return None, None

    if team_id is not None:
        team = teams.filter(pk=team_id).first()
        if not team:
            return None, 'Unknown team, or you are not a member of it.'
        return team, None

    candidates = list(teams)
    if len(candidates) > 1:
        listed = ', '.join(f'{t.id} ({t.name})' for t in candidates)
        return None, ('You belong to more than one team -- pass team_id to say '
                      f'which one this belongs to. Yours: {listed}.')

    return (candidates[0] if candidates else None), None
