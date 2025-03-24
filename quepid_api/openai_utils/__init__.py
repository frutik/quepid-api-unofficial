import json
import logging
import markdownify as markdown_converter

from pydantic import BaseModel, Field
from typing import Optional, List
from openai import OpenAI

from .prompts import SEARCH_RESULTS_SCRAPPER

logger = logging.getLogger('')


class SearchResult(BaseModel):
    title: str = Field(description='Search result title.')
    image: str = Field(description='Search result image.')


class Search(BaseModel):
    query: str
    page_size: Optional[int] = Field(description='Page size selected. If possible to identify from the content')
    total_results: Optional[int] = Field(description='Total number of results for detected search query. If possible to identify from the content')
    results: List[SearchResult]


ExtractTool = [
    {
        "type": "function",
        "function": {
            "name": "HtmlToSearch",
            "description": 'from provided text of article, please extract all products/models mentioned in it. type of product (tablet, smartphone, etc)',
            "parameters": Search.model_json_schema(),
        },
    }
]


def html_to_search(content, markdownify=False, model='gpt-4-turbo', api_key=None):
    content_type = 'html'
    if markdownify:
        content_type = 'markdown'
        content = markdown_converter.markdownify(
            content,
            autolinks=False,
            heading_style="ATX"
        )
    logger.info(content)
    client = OpenAI(api_key=api_key)
    message = [
        {
            "role": "system",
            "content": SEARCH_RESULTS_SCRAPPER.format(
                content_type=content_type
            )
        },
        {
            "role": "user",
            "content": content
        },
    ]
    logger.info(message)
    completion = client.chat.completions.create(
        messages=message,
        model=model,
        stream=False,
        tools=ExtractTool,
        tool_choice={
            "type": "function",
            "function": {"name": ExtractTool[0]['function']['name']},
        }
    )
    return json.loads(completion.choices[0].message.tool_calls[0].function.arguments)
