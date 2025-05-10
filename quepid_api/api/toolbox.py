import logging

from ninja import Router
from ninja import File
from ninja.files import UploadedFile
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Case
from typing import List
from ninja.pagination import paginate
from ninja import Schema

logger = logging.getLogger('')

router = Router(tags=["Toolbox"])


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


@router.post("/url_to_case/", tags=['Toolbox'])
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


@router.post("/html_to_case/", tags=['Toolbox'])
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
