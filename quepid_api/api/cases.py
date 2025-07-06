import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Case
from typing import List
from ninja.pagination import paginate
from ninja import Schema
from .utils import _by_pk
from ninja import ModelSchema

logger = logging.getLogger('')

router = Router(tags=["Cases management"])


class CreateCase(Schema):
    name: str
    scorer_id: int = 5
    nightly: int = 1
    book_id: int = None
    search_endpoint_id: int = None
    search_query: str = None

#           "id": 1,
#       "case_name": "Movies Search",
#       "last_try_number": 1,
#       "owner": 1,
#       "archived": 0,
#       "scorer_id": 5,
#       "created_at": "2025-05-10T18:53:42Z",
#       "updated_at": "2025-05-10T18:54:16Z",
#       "book_id": null,
#       "public": null,
#       "options": null,
#       "nightly": null

# First, let's add an UpdateCase schema
class UpdateCase(Schema):
    name: str | None = None
    scorer_id: int | None = None
    book_id: int | None = None
    archived: int | None = None
    public: int | None = None
    options: dict | None = None
    nightly: int | None = None

@router.get("/", response=List[Case])
@paginate
def view_cases(request):
    # @todo check rights?
    return qmodels.Cases.objects.using('quepid').all()


@router.post("/", response={200: Case, 400: str})
def create_case(request, data: CreateCase):
    try:
        now = timezone.now()
        case = qmodels.Cases.objects.using('quepid').create(
            case_name=data.name,
            scorer_id=data.scorer_id,
            created_at=now,
            updated_at=now,
            last_try_number=1,
            nightly=data.nightly,
            archived=0,
            owner=request.auth
        )
        logger.info(case)
        search_endpoint = None
        if search_endpoint_id := data.search_endpoint_id:
            if not (search_endpoint := _by_pk(qmodels.SearchEndpoints, search_endpoint_id)):
                return 400, 'Unknown search endpoint.'
        logger.info([case, search_endpoint])
        qmodels.Tries.objects.using('quepid').create(
            try_number=1,
            case=case,
            query_params=data.search_query or   {},  # Default empty query parameters
            search_endpoint=search_endpoint,  # Will be set later when user configures it
            created_at=now,
            updated_at=now,
            field_spec='id:_id, title: name',
            escape_query=1
        )
        return case
    except Exception as e:
        return 400, str(e)


@router.get("/{id}/", response={200: Case, 404: None})
def view_case(request, id: int):
    if r := _by_pk(qmodels.Cases, id):
        return 200, r
    return 404, None

@router.put("/{id}/", response={200: Case, 404: None, 400: str})
def update_case(request, id: int, data: UpdateCase):
    """Update an existing case"""
    try:
        case = _by_pk(qmodels.Cases, id)
        if not case:
            return 404, None
            
        # Update only provided fields
        if data.name is not None:
            case.case_name = data.name
        if data.scorer_id is not None:
            case.scorer_id = data.scorer_id
        if data.book_id is not None:
            case.book_id = data.book_id
        if data.archived is not None:
            case.archived = data.archived
        if data.public is not None:
            case.public = data.public
        if data.options is not None:
            case.options = data.options
        if data.nightly is not None:
            case.nightly = data.nightly
            
        case.updated_at = timezone.now()
        case.save(using='quepid')
        return 200, case
    except Exception as e:
        return 400, str(e)

@router.delete("/{id}/", response={204: None, 404: None})
def delete_case(request, id: int):
    """Delete an existing case"""
    case = _by_pk(qmodels.Cases, id)
    if not case:
        return 404, None
        
    case.delete(using='quepid')
    return 204, None