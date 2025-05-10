import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Query
from typing import List
from ninja.pagination import paginate
from ninja import Schema

from .utils import _by_pk


logger = logging.getLogger('')

router = Router(tags=["Queries management"])


class CreateQuery(Schema):
    query_text: str
    case: int
    query_options: dict = {}


@router.get("/{case_id}/", response=List[Query])
@paginate
def view_queries(request, case_id: int):
    return qmodels.Queries.objects\
        .using('quepid')\
        .filter(case_id=case_id)


@router.get("/{case_id}/{query_id}", response={200: Query, 404: None})
def view_query(request, case_id: int, query_id: int):
    if r := _by_pk(qmodels.Queries, query_id):
        return 200, r
    return 404, None
