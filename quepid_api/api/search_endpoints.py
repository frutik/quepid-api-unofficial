import logging
from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import SearchEndpoint
from typing import List, Literal
from ninja.pagination import paginate
from ninja import Schema
from .utils import _by_pk

logger = logging.getLogger('')

router = Router(tags=["Search Endpoints management"])

SearchEngineType = Literal["solr", "es", "opensearch", "searchapi"]


class CreateSearchEndpoint(Schema):
    name: str
    endpoint_url: str
    search_engine: SearchEngineType
    proxy_requests: int = 0
    custom_headers: dict | None = None
    api_method: str | None = None


class UpdateSearchEndpoint(Schema):
    name: str
    endpoint_url: str
    search_engine: SearchEngineType
    custom_headers: dict | None = None
    api_method: str


@router.get("/", response=List[SearchEndpoint])
@paginate
def view_search_endpoints(request):
    return qmodels.SearchEndpoints.objects \
        .using('quepid') \
        .all()
    
    
@router.post("/", response={200: SearchEndpoint, 400: str})
def create_search_endpoint(request, data: CreateSearchEndpoint):
    try:
        now = timezone.now()
        return qmodels.SearchEndpoints.objects.using('quepid').create(
            name=data.name,
            endpoint_url=data.endpoint_url,
            archived=0,
            search_engine=data.search_engine,  # No need for .value conversion
            custom_headers=data.custom_headers,
            api_method=data.api_method,
            proxy_requests=data.proxy_requests,
            created_at=now,
            updated_at=now,
            owner=request.auth
        )
    except Exception as e:
        return 400, str(e)
        
        
@router.get("/{id}/", response={200: SearchEndpoint, 404: None})
def view_search_endpoint(request, id: int):
    if r := _by_pk(qmodels.SearchEndpoints, id):
        return 200, r
    return 404, None
    
    
@router.put("/{id}/", response={200: SearchEndpoint, 404: None, 400: str})
def update_search_endpoint(request, id: int, data: UpdateSearchEndpoint):
    """Update an existing search endpoint"""
    try:
        endpoint = _by_pk(qmodels.SearchEndpoints, id)
        if not endpoint:
            return 404, None

        # Update only provided fields
        if data.name is not None:
            endpoint.name = data.name
        if data.endpoint_url is not None:
            endpoint.endpoint_url = data.endpoint_url
        if data.search_engine is not None:
            endpoint.search_engine = data.search_engine  # No need for .value conversion
        if data.custom_headers is not None:
            endpoint.custom_headers = data.custom_headers
        if data.api_method is not None:
            endpoint.api_method = data.api_method

        endpoint.updated_at = timezone.now()
        endpoint.save(using='quepid')
        return 200, endpoint
    except Exception as e:
        return 400, str(e)
        
        
@router.delete("/{id}/", response={204: None, 404: None})
def delete_search_endpoint(request, id: int):
    """Delete an existing search endpoint"""
    endpoint = _by_pk(qmodels.SearchEndpoints, id)
    if not endpoint:
        return 404, None

    endpoint.delete(using='quepid')
    return 204, None
