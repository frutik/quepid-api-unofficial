import os

from ninja import NinjaAPI

from api.utils import AuthBearer

from api.scorers import router as scorers_router
from api.search_endpoints import router as search_endpoints_router
from api.cases import router as cases_router
from api.queries import router as queries_router
from api.books import router as books_router
# from api.toolbox import router as toolbox_router

api = NinjaAPI(
    title="Quepid Custom API",
    version=os.getenv('APP_VERSION', 'vX.X.X'),
    auth=AuthBearer()
)

api.add_router("/scorers", scorers_router)
api.add_router("/search_endpoints", search_endpoints_router)
api.add_router("/case", cases_router)
api.add_router("/query", queries_router)
api.add_router("/books", books_router)
# api.add_router("/toolbox", toolbox_router)


# @api.get("/.well-known/modelcontext", response=ModelContextInfo)
# def modelcontext_config(request):
#     return {
#         "schema": "https://modelcontext.org/schema/v0.1",
#         "name": "My Django Ninja API",
#         "description": "API for product-related tasks",
#         "capabilities": ["invoke"],
#     }