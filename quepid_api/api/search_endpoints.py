import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import SearchEndpoint
from typing import List
from ninja.pagination import paginate
from ninja import Schema

logger = logging.getLogger('')

router = Router(tags=["Search Endpoints management"])


@router.get("/search-endpoint/", response=List[SearchEndpoint])
@paginate
def view_search_endpoints(request):
    # @todo check rights?
    return qmodels.SearchEndpoints.objects\
        .using('quepid')\
        .all()
