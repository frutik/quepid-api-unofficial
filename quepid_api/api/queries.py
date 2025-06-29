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


class UpdateQuery(Schema):
    query_text: str = None
    notes: str = None
    information_need: str = None
    query_options: dict = None


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


@router.post("/{case_id}/", response={200: Query, 400: str})
def create_query(request, case_id: int, data: CreateQuery):
    try:
        now = timezone.now()
        return qmodels.Queries.objects.using('quepid').create(
            query_text=data.query_text,
            case_id=case_id,
            notes=data.query_options.get('notes', ''),
            information_need=data.query_options.get('information_need', ''),
            options=str(data.query_options) if data.query_options else None,
            created_at=now,
            updated_at=now
        )
    except Exception as e:
        return 400, str(e)


@router.patch("/{case_id}/{query_id}", response={200: Query, 404: None, 400: str})
def update_query(request, case_id: int, query_id: int, data: UpdateQuery):
    try:
        query = qmodels.Queries.objects.using('quepid').filter(id=query_id, case_id=case_id).first()
        if not query:
            return 404, None
        
        update_fields = {}
        if data.query_text is not None:
            update_fields['query_text'] = data.query_text
        if data.notes is not None:
            update_fields['notes'] = data.notes
        if data.information_need is not None:
            update_fields['information_need'] = data.information_need
        if data.query_options is not None:
            update_fields['options'] = str(data.query_options)
        
        if update_fields:
            update_fields['updated_at'] = timezone.now()
            qmodels.Queries.objects.using('quepid').filter(id=query_id).update(**update_fields)
            return 200, qmodels.Queries.objects.using('quepid').get(id=query_id)
        
        return 200, query
    except Exception as e:
        return 400, str(e)


@router.delete("/{case_id}/{query_id}", response={200: dict, 404: None, 400: str})
def delete_query(request, case_id: int, query_id: int):
    try:
        query = qmodels.Queries.objects.using('quepid').filter(id=query_id, case_id=case_id).first()
        if not query:
            return 404, None
        
        query.delete()
        return 200, {"message": "Query deleted successfully"}
    except Exception as e:
        return 400, str(e)
