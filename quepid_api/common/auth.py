"""Bearer-token lookup against Quepid's own api_keys table.

Single source of truth for every API surface in this project: the ninja API
reaches it through ``api.utils.AuthBearer``, the MCP server through
``quepid_mcp.auth.QuepidTokenAuthentication``. Tokens are issued by Quepid
itself (``thor user:add_api_key``), never by this project.

Lives in ``common`` rather than in the ``quepid`` app because that app is kept
to the inspectdb reflection of Quepid's schema and nothing else. Deliberately
free of DRF and of any MCP import, so neither API surface depends on the other.
"""
import logging

import quepid.models as qmodels

logger = logging.getLogger(__name__)


def user_from_token(token):
    """Resolve a Quepid API token to its Users row, or None if it is unknown."""
    api_key = qmodels.ApiKeys.objects \
        .using('quepid') \
        .filter(token_digest=token) \
        .first()

    if api_key is None:
        return None

    return qmodels.Users.objects \
        .using('quepid') \
        .filter(pk=api_key.user_id) \
        .first()
