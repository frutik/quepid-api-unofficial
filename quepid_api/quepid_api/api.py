import os
import logging

from ninja import NinjaAPI
from ninja import Schema, ModelSchema
from ninja.security import HttpBearer

import quepid.models as qmodels
from quepid.schemas import *


def _by_pk(cls, pk):
    return cls.objects.using('quepid').filter(pk=pk).first()


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        return qmodels.ApiKeys.check_token(
            bearer=request.headers.get('Authorization', 'Bearer 123')
        )


logger = logging.getLogger('')

api = NinjaAPI(
    title="Quepid Custom API",
    version=os.getenv('APP_VERSION', 'vX.X.X'),
    auth=AuthBearer()
)


class CreateQuery(Schema):
    query_text: str
    case: int
    query_options: dict = {}


@api.get("/scorer/{id}/", response={200: Scorer, 404: None}, tags=['Scorers management'])
def view_scorer(request, id: int):
    if r := _by_pk(qmodels.Scorers, id):
        return 200, r
    return 404, None


@api.get("/case/{id}/", response={200: Case, 404: None}, tags=['Cases management'])
def view_case(request, id: int):
    if r := _by_pk(qmodels.Cases, id):
        return 200, r
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
    logger.info(request.auth)
    if r := _by_pk(qmodels.Queries, id):
        return 200, r
    return 404, None


@api.post("/query", response={200: Query, 400: None}, tags=['Query management'])
def create_query(request, data: CreateQuery):
    return 400, None


@api.patch("/query/{id}/", response={200: Query, 400: None}, tags=['Query management'])
def update_query(request, id: int):
    return 400, None
