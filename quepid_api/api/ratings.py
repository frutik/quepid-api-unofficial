import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Rating
from typing import List
from ninja.pagination import paginate
from ninja import Schema

from .utils import _by_pk


logger = logging.getLogger('')

router = Router(tags=["Queries management"])


class CreateRating(Schema):
    doc_id: str
    rating: int


@router.get("/query/{query_id}/rating/", response=List[Rating])
@paginate
def view_ratings(request, query_id: int):
    return qmodels.Ratings.objects\
        .using('quepid')\
        .filter(query_id=query_id)


# @router.get("/{query_id}/{query_id}", response={200: Query, 404: None})
# def view_query(request, case_id: int, query_id: int):
#     if r := _by_pk(qmodels.Queries, query_id):
#         return 200, r
#     return 404, None


@router.post("/query/{query_id}/rating/", response={200: Rating, 400: str})
def create_rating(request, query_id: int, data: CreateRating):
    try:
        if not (query := _by_pk(qmodels.Queries, query_id)):
            return 400, 'Unknown query.'
        logger.info(query)
        now = timezone.now()
        return qmodels.Ratings.objects.using('quepid').create(
            query=query,
            doc_id=data.doc_id,
            rating=data.rating,
            created_at=now,
            updated_at=now
        )
    except Exception as e:
        return 400, str(e)


# @router.patch("/{case_id}/{query_id}", response={200: Query, 404: None, 400: str})
# def update_query(request, case_id: int, query_id: int, data: UpdateQuery):
#     try:
#         query = qmodels.Queries.objects.using('quepid').filter(id=query_id, case_id=case_id).first()
#         if not query:
#             return 404, None
#
#         update_fields = {}
#         if data.query_text is not None:
#             update_fields['query_text'] = data.query_text
#         if data.notes is not None:
#             update_fields['notes'] = data.notes
#         if data.information_need is not None:
#             update_fields['information_need'] = data.information_need
#         if data.query_options is not None:
#             update_fields['options'] = str(data.query_options)
#
#         if update_fields:
#             update_fields['updated_at'] = timezone.now()
#             qmodels.Queries.objects.using('quepid').filter(id=query_id).update(**update_fields)
#             return 200, qmodels.Queries.objects.using('quepid').get(id=query_id)
#
#         return 200, query
#     except Exception as e:
#         return 400, str(e)


@router.delete("/query/{query_id}/rating/{doc_id}", response={200: dict, 404: None, 400: str})
def delete_rating(request, query_id: int, doc_id: str):
    try:
        rating = qmodels.Ratings.objects.using('quepid')\
            .filter(query_id=query_id)\
            .filter(doc_id=doc_id)\
            .first()
        if not rating:
            return 404, None
        rating.delete()
        return 200, {"message": "Rating deleted successfully"}
    except Exception as e:
        return 400, str(e)
    #         return 404, None
    #     rating.delete()
    #     return 200, {"message": "Rating deleted successfully"}
    # except Exception as e:
    #     return 400, str(e)
