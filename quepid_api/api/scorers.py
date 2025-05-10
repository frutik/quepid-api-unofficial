import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Scorer
from typing import List
from ninja.pagination import paginate
from ninja import Schema
from .utils import _by_pk

logger = logging.getLogger('')

router = Router(tags=["Scorers management"])


@router.get("/{id}/", response=List[Scorer])
@paginate
def view_scorers(request):
    return qmodels.Scorers.objects\
        .using('quepid')\
        .all()


@router.get("/{id}/", response={200: Scorer, 404: None})
def view_scorer(request, id: int):
    if r := _by_pk(qmodels.Scorers, id):
        return 200, r
    return 404, None
