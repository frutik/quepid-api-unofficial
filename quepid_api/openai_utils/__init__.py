import json
import logging
import markdownify as markdown_converter

from pydantic import BaseModel, Field
from typing import Optional, List
from openai import OpenAI

logger = logging.getLogger('')


class SearchResult(BaseModel):
    title: str = Field(description='Search result title.')
    image: str = Field(description='Search result image.')


class Search(BaseModel):
    query: str
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
    client = OpenAI(api_key=api_key)
    message = [
        {
            "role": "system",
            "content": f"You are a web scraper, tasked with extracting data from an online search engine. Your objective is to extract the search query as well as the list of ALL search results from provided content of {content_type} page containing all this information. It's also possible that provided content contains no search results. In this case return empty list of results."
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
