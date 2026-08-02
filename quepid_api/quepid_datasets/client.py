"""A thin client for this project's own REST API.

Every command in this app talks to the API over HTTP rather than to the database
(see ``load_dataset`` for why), so the session, the token and the reading of a
failed response live here instead of three times over.

Deliberately free of Django: the only thing it knows about a management command
is that ``ApiError`` should read well on a terminal.
"""
import threading

import requests

# django-ninja's default pagination caps a list response, so paging is the only
# way to see everything. Big enough that no realistic Quepid needs many rounds.
PAGE_SIZE = 500


class ApiError(Exception):
    """Anything that stopped a request from producing what was asked for."""


class QuepidApi:
    """An authenticated session against one deployment of this API."""

    def __init__(self, base_url, token, timeout=30.0):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout
        self._local = threading.local()

    @property
    def session(self):
        """A ``requests`` session, one per thread.

        ``load_dataset`` posts ratings from a pool; a session each keeps their
        connection pools and keep-alive connections independent.
        """
        if not hasattr(self._local, 'session'):
            session = requests.Session()
            session.headers['Authorization'] = f'Bearer {self.token}'
            self._local.session = session
        return self._local.session

    def request(self, method, path, **kwargs):
        """The raw response, for callers that treat some status codes as data."""
        url = f'{self.base_url}{path}'
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise ApiError(f'{method} {url} failed: {e}')

        # Auth is global on the NinjaAPI instance, so a 401 means the token, not
        # the endpoint. Never worth retrying or counting as a row failure.
        if response.status_code == 401:
            raise ApiError(
                f'Token rejected by {self.base_url} -- check --api-token / QUEPID_API_TOKEN.'
            )
        return response

    def get(self, path, **params):
        response = self.request('GET', path, params=params)
        if response.status_code != 200:
            raise ApiError(
                f'GET {self.base_url}{path} -> {response.status_code}: {response.text[:500]}'
            )
        return response.json()

    def post(self, path, payload):
        """POST and return the created row, or fail with the API's own reason.

        Every router answers a rejected write with 400 and a bare string (the
        house style in CLAUDE.md), so the body is the whole diagnosis.
        """
        response = self.request('POST', path, json=payload)
        if response.status_code != 200:
            raise ApiError(
                f'POST {self.base_url}{path} -> {response.status_code}: {response.text[:500]}\n'
                f'payload: {payload}'
            )
        return response.json()

    def count(self, path, **params):
        """How many rows a paginated endpoint holds, without fetching them."""
        return self.get(path, limit=1, **params)['count']

    def rows(self, path, limit=None, **params):
        """Rows of a paginated endpoint, following offsets until ``limit``."""
        rows = []
        while True:
            wanted = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(rows))
            page = self.get(path, limit=wanted, offset=len(rows), **params)
            rows.extend(page['items'])
            if len(rows) >= page['count'] or not page['items']:
                return rows
            if limit is not None and len(rows) >= limit:
                return rows[:limit]
