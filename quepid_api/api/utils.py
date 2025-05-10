from ninja.security import HttpBearer


import quepid.models as qmodels


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        bearer = request.headers\
            .get('Authorization', 'Bearer 123')
        try:
            api_key = qmodels.ApiKeys.objects\
                .using('quepid')\
                .get(token_digest=bearer.split()[1])
            return qmodels.Users.objects\
                .using('quepid')\
                .get(pk=api_key.user_id)
        except:
            pass


def _by_pk(cls, pk):
    return cls.objects.\
        using('quepid')\
        .filter(pk=pk)\
        .first()
