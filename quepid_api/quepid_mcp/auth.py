"""DRF authentication for the MCP endpoint.

Wired in through ``settings.DJANGO_MCP_AUTHENTICATION_CLASSES``, which makes
django-mcp-server apply IsAuthenticated to the endpoint automatically -- so the
server is closed by default rather than relying on a URL-prefix check.

Accepts exactly the same tokens as the ninja API: the lookup itself lives in
``common.auth`` and is shared, only the DRF plumbing is here.
"""
import logging

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from common.auth import user_from_token

logger = logging.getLogger(__name__)


class QuepidPrincipal:
    """Adapts a Quepid ``Users`` row to what DRF permission classes expect.

    ``Users`` is not a django.contrib.auth user, but DRF's IsAuthenticated
    duck-types on ``is_authenticated``. That flag lives here rather than on the
    model because quepid/models.py must stay pure inspectdb output -- no auth
    concerns may leak into the reflected schema.

    Every other attribute (``id``, ``administrator``, ...) delegates to the
    wrapped row, so scoping code in mcp.py can treat this as the user.
    """

    is_authenticated = True
    is_anonymous = False

    def __init__(self, quepid_user):
        self.quepid_user = quepid_user

    def __getattr__(self, name):
        # Only reached for attributes not found on the wrapper itself.
        return getattr(self.quepid_user, name)

    def __str__(self):
        return str(self.quepid_user)


class QuepidTokenAuthentication(BaseAuthentication):
    """DRF authentication accepting the same tokens as the ninja API.

    Returning None (rather than raising) when the header is absent or malformed
    lets DRF fall through to IsAuthenticated, which produces a 401 carrying the
    WWW-Authenticate header built by authenticate_header below.
    """

    keyword = 'Bearer'

    def authenticate(self, request):
        parts = request.headers.get('Authorization', '').split()

        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        user = user_from_token(parts[1])

        if user is None:
            raise AuthenticationFailed('Invalid API token.')

        # The ninja API uses the bare Users row (it assigns it straight to an
        # owner FK); only DRF needs the wrapper.
        return QuepidPrincipal(user), parts[1]

    def authenticate_header(self, request):
        return self.keyword
