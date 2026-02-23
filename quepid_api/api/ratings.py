import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Rating
from typing import List
from ninja.pagination import paginate
from ninja import Schema

from .utils import _by_pk


logger = logging.getLogger(__name__)

router = Router(tags=["Ratings management"])


class CreateRating(Schema):
    doc_id: str
    rating: int


@router.get("/query/{query_id}/rating/", response=List[Rating])
@paginate
def view_ratings(request, query_id: int):
    return qmodels.Ratings.objects\
        .using('quepid')\
        .filter(query_id=query_id)


@router.post("/query/{query_id}/rating/", response={200: Rating, 400: str})
def create_rating(request, query_id: int, data: CreateRating):
    try:
        if not (query := _by_pk(qmodels.Queries, query_id)):
            return 400, 'Unknown query.'
        logger.info(query)
        now = timezone.now()
        return qmodels.Ratings.objects\
            .using('quepid')\
            .create(
            query=query,
            doc_id=data.doc_id,
            rating=data.rating,
            created_at=now,
            updated_at=now
        )
    except Exception as e:
        return 400, str(e)


@router.delete("/query/{query_id}/rating/{doc_id}", response={200: dict, 404: None})
def delete_rating(request, query_id: int, doc_id: str):
    rating = qmodels.Ratings.objects\
        .using('quepid')\
        .filter(query_id=query_id)\
        .filter(doc_id=doc_id)\
        .first()
    if not rating:
        return 404, None
    try:
        rating.delete()
    except Exception as e:
        return 400, str(e)
    return 200, {"message": "Rating deleted successfully"}
