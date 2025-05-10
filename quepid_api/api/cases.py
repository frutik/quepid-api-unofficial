import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Case
from typing import List
from ninja.pagination import paginate
from ninja import Schema
from .utils import _by_pk

logger = logging.getLogger('')

router = Router(tags=["Cases management"])


class CreateCase(Schema):
    name: str
    scorer_id: int
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


@router.get("/", response=List[Case])
@paginate
def view_cases(request):
    # @todo check rights?
    return qmodels.Cases.objects.using('quepid').all()


@router.post("/", response={200: Case, 400: str})
def create_case(request, data: CreateCase):
    try:
        now = timezone.now()
        return qmodels.Cases.objects.using('quepid').create(
            case_name=data.name,
            scorer_id=data.scorer_id,
            created_at=now,
            updated_at=now,
            owner=request.auth
        )
    except Exception as e:
        return 400, str(e)


@router.get("/{id}/", response={200: Case, 404: None})
def view_case(request, id: int):
    if r := _by_pk(qmodels.Cases, id):
        return 200, r
    return 404, None


# @api.patch("/case", tags=['Cases management'])
# def update_case(request, a: int, b: int):
#     return {"result": a + b}
