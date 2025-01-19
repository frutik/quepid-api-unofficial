from ninja import NinjaAPI

from ninja import Schema
from ninja import ModelSchema
from ninja.security import HttpBearer

import quepid.models as qmodels


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        return qmodels.ApiKeys.check_token(
            bearer=request.headers.get('Authorization', 'Bearer 123')
        )


api = NinjaAPI(
    title="Quepid Custom API",
    version="v1.1.0",
    auth=AuthBearer()
)


class CreateQuery(Schema):
    query_text: str
    case: int
    query_options: dict = {}


class Scorer(ModelSchema):
    class Meta:
        model = qmodels.Scorers
        fields = "__all__"


class Case(ModelSchema):
    class Meta:
        model = qmodels.Cases
        fields = "__all__"


class Query(ModelSchema):
    query_options: dict = {}
    class Meta:
        model = qmodels.Queries
        fields = "__all__"
        exclude = ['options', ]


@api.get("/scorer/{id}/", response={200: Scorer, 404: None}, tags=['Scorers management'])
def view_scorer(request, id: int):
    if q := qmodels.Cases.objects.none():
        return 200, {}
    return 404, None


@api.get("/case/{id}/", response={200: Case, 404: None}, tags=['Cases management'])
def view_case(request, id: int):
    if q := qmodels.Cases.objects.none():
        return 200, {}
    return 404, None


# @api.post("/case", tags=['Cases management'])
# def create_case(request, data: CreateQuery):
#     return {"result": a + b}
#
#
# @api.patch("/case", tags=['Cases management'])
# def update_case(request, a: int, b: int):
#     return {"result": a + b}


@api.get("/query/{id}/", response={200: Query, 404: None}, tags=['Query management'])
def view_query(request, id: int):
    if q := qmodels.Queries.objects.none():
        return 200, {}
    return 404, None


@api.post("/query", response={200: Query, 400: None}, tags=['Query management'])
def create_query(request, data: CreateQuery):
    return 400, None


@api.patch("/query/{query_id}/", tags=['Query management'])
def update_query(request, id: int):
    return {}