from ninja import Schema


class MCPRequest(Schema):
    action: str
    params: dict


class ModelContextInfo(Schema):
    schema: str
    name: str
    capabilities: list[str]
    description: str


@api.get("/.well-known/modelcontext", response=ModelContextInfo)
def modelcontext_config(request):
    return {
        "schema": "https://modelcontext.org/schema/v0.1",
        "name": "My Django Ninja API",
        "description": "API for product-related tasks",
        "capabilities": ["invoke"],
    }