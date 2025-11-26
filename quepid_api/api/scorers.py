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

class CreateScorer(Schema):
    name: str

class UpdateScorer(Schema):
    name: str


@router.get("/", response=List[Scorer])
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
    
    
@router.post("/", response={200: Scorer, 400: str})
def create_scorer(request, data: CreateScorer):
    try:
        now = timezone.now()
        scorer = qmodels.Scorers.objects.using('quepid').create(
            name=data.name,
            created_at=now,
            updated_at=now
        )
        return 200, scorer
    except Exception as e:
        return 400, str(e)
        
        
@router.put("/{id}/", response={200: Scorer, 404: None, 400: str})
def update_scorer(request, id: int, data: UpdateScorer):
    try:
        scorer = _by_pk(qmodels.Scorers, id)
        if not scorer:
            return 404, None
        scorer.name = data.name
        scorer.updated_at = timezone.now()
        scorer.save(using='quepid')
        return 200, scorer
    except Exception as e:
        return 400, str(e)
        
        
@router.delete("/{id}/", response={204: None, 404: None})
def delete_scorer(request, id: int):
    scorer = _by_pk(qmodels.Scorers, id)
    if not scorer:
        return 404, None
    scorer.delete(using='quepid')
    return 204, None
    
    
