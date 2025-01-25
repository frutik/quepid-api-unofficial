import os
import logging

from ninja import NinjaAPI
from ninja import File
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja import Schema, ModelSchema
from ninja.security import HttpBearer

from playwright.sync_api import sync_playwright

from openai_utils import html_to_search
import quepid.models as qmodels
from quepid.schemas import *


def _by_pk(cls, pk):
    return cls.objects.using('quepid').filter(pk=pk).first()


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        return qmodels.ApiKeys.check_token(
            bearer=request.headers.get('Authorization', 'Bearer 123')
        )


logger = logging.getLogger('')

api = NinjaAPI(
    title="Quepid Custom API",
    version=os.getenv('APP_VERSION', 'vX.X.X'),
    # auth=AuthBearer()
)


class CreateQuery(Schema):
    query_text: str
    case: int
    query_options: dict = {}


class QuepidParams(Schema):
    case: str = 'Case Name'


class OpenAiParams(Schema):
    model: str = 'gpt-4o'
    markdownify: bool = True
    max_characters: int = None


class SiteParams(Schema):
    user_agent: str = "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko)"
    timeout: int = 180000
    accept_cookies: str = None


class UrlToCaseParams(Schema):
    openai: OpenAiParams
    web: SiteParams
    quepid: QuepidParams


class HtmlToCaseParams(Schema):
    openai: OpenAiParams
    quepid: QuepidParams


@api.get("/scorer/{id}/", response={200: Scorer, 404: None}, tags=['Scorers management'])
def view_scorer(request, id: int):
    if r := _by_pk(qmodels.Scorers, id):
        return 200, r
    return 404, None


@api.get("/case/{id}/", response={200: Case, 404: None}, tags=['Cases management'])
def view_case(request, id: int):
    if r := _by_pk(qmodels.Cases, id):
        return 200, r
    return 404, None


# @api.post("/case", tags=['Cases management'])
# def create_case(request, data: CreateQuery):
#     return {"result": a + b}
#
#
# @api.patch("/case", tags=['Cases management'])
# def update_case(request, a: int, b: int):
#     return {"result": a + b}


@api.get("/query/{id}/", response={200: Query, 404: None}, tags=['Query management'])
def view_query(request, id: int):
    logger.info(request.auth)
    if r := _by_pk(qmodels.Queries, id):
        return 200, r
    return 404, None


@api.post("/query", response={200: Query, 400: None}, tags=['Query management'])
def create_query(request, data: CreateQuery):
    return 400, None


@api.patch("/query/{id}/", response={200: Query, 400: None}, tags=['Query management'])
def update_query(request, id: int):
    return 400, None


@api.post("/toolbox/url_to_case/", tags=['Toolbox'])
def url_to_case(request, url: str, openai_key: str, params: UrlToCaseParams):
    with sync_playwright() as p:
        logger.info('Launching browser')
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=params.web.user_agent)
        page = context.new_page()
        page.set_default_timeout(params.web.timeout)
        logger.info('Opening url')
        page.goto(url)
        if accept_cookies := params.web.accept_cookies:
            try:
                page.click(f"text={accept_cookies}", timeout=5000)
                logger.info('Accepted cookies!')
            except:
                logger.info('No cookie consent dialog found')
        logger.info('Getting content')
        html = page.content()
        browser.close()
    logger.info('Parsing')
    # add tiktoken and check tokens number vs context size
    if max_characters := params.openai.max_characters:
        html = html[0:max_characters]
    search_results = html_to_search(
        html,
        api_key=openai_key,
        markdownify=params.openai.markdownify,
        model=params.openai.model
    )
    if case_name := params.quepid.case:
        # store to case
        pass
    return search_results


@api.post("/toolbox/html_to_case/", tags=['Toolbox'])
def html_to_case(request, openai_key: str, params: HtmlToCaseParams, html: UploadedFile = File(...)):
    html = html.read().decode('utf-8')
    if max_characters := params.openai.max_characters:
        html = html[0:max_characters]
    search_results = html_to_search(
        html,
        api_key=openai_key,
        markdownify=params.openai.markdownify,
        model=params.openai.model
    )
    if case_name := params.quepid.case:
        # store to case
        pass
    return search_results
