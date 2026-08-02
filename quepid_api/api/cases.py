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

logger = logging.getLogger(__name__)

router = Router(tags=["Cases management"])


class CreateCase(Schema):
    name: str
    scorer_id: int = 5
    nightly: int = 1
    book_id: int = None
    search_endpoint_id: int = None
    search_query: str = None
    fields_mapping: str = 'id:_id, title: name'

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
    fields_mapping: str = 'id:_id, title: name'


@router.get("/", response=List[Case])
@paginate
def view_cases(request, archived: bool = False):
    """List cases, hiding archived ones unless `?archived=true` is passed.

    `DELETE /case/{id}/` is a soft delete (see `delete_case`), so without this
    filter every case ever "deleted" through this API would stay in the list.

    The default branch **excludes 1** rather than filtering on 0. `cases.archived`
    is `t.boolean "archived"` in Rails -- nullable, no default -- so a case
    Quepid wrote itself can be NULL, and NULL is a distinct third state from 0
    that still means "not archived". `.filter(archived=0)` would silently hide
    those rows.
    """
    # @todo check rights?
    cases = qmodels.Cases.objects \
        .using('quepid')

    if archived:
        return cases \
            .filter(archived=1)

    return cases \
        .exclude(archived=1)
    
    
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
            query_params=data.search_query or {},
            search_endpoint=search_endpoint,
            created_at=now,
            updated_at=now,
            number_of_rows=30,
            field_spec=data.fields_mapping,
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
    """Archive an existing case. This is a soft delete -- the row survives.

    A hard delete is not available to us. Rails owns the cascade: `Case` in
    `app/models/case.rb` declares `dependent: :destroy` for tries, queries,
    ratings, scores, snapshots, annotations and metadata. `inspectdb` reflects
    every relation as `DO_NOTHING`, so Django emits no cascade of its own and
    MySQL refuses the delete outright:

        IntegrityError (1451, 'Cannot delete or update a parent row: a foreign
        key constraint fails (`db`.`tries`, CONSTRAINT `tries_ibfk_1` ...)')

    Since `create_case` always writes a try alongside the case, that made every
    case created through this API undeletable through this API.

    Archiving is what Quepid's own UI does with a case you are done with, so the
    row stays fetchable with `archived = 1` and `PUT /case/{id}/` can set it
    back to 0. Re-archiving an archived case is a no-op, not an error.
    """
    case = _by_pk(qmodels.Cases, id)
    if not case:
        return 404, None

    case.archived = 1
    case.updated_at = timezone.now()
    case.save(using='quepid')
    return 204, None
