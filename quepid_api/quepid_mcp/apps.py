from django.apps import AppConfig


class QuepidMcpConfig(AppConfig):
    """The MCP server surface over the Quepid schema.

    Holds no models of its own -- it publishes quepid.models read-only.
    django-mcp-server autodiscovers this app's mcp.py at startup, which is the
    only reason the app needs to be in INSTALLED_APPS.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quepid_mcp'
