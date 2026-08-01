from ninja.security import HttpBearer


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
