"""What every command in this app shares: how to reach the API, and how to fail.

Not under ``management/commands/`` on purpose -- Django imports every module
there as a command, and this is a base class, not one.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from quepid_datasets.client import ApiError, QuepidApi

DEFAULT_API_URL = os.getenv('QUEPID_API_URL', 'http://localhost:8081/api')


class QuepidCommand(BaseCommand):
    """A command that talks to this project's REST API.

    Subclasses implement ``run(**options)`` and use ``self.api``. Every
    ``ApiError`` raised in there becomes a ``CommandError``, so no handler needs
    to catch one just to exit cleanly -- and a ``CommandError`` raised
    deliberately (with more context than the client could know) passes through
    untouched.

    Subclasses adding arguments must call ``super().add_arguments(parser)``.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '--api-url',
            default=DEFAULT_API_URL,
            help=f'Base URL of this API. Default: {DEFAULT_API_URL} (QUEPID_API_URL).',
        )
        parser.add_argument(
            '--api-token',
            help='Quepid API token. Defaults to QUEPID_API_TOKEN. Anything created is owned '
                 'by whoever the token belongs to.',
        )
        parser.add_argument(
            '--timeout',
            type=float,
            default=30.0,
            help='Per-request timeout in seconds. Default: 30.',
        )

    def handle(self, *args, **options):
        token = options['api_token'] or os.getenv('QUEPID_API_TOKEN')
        if not token:
            raise CommandError(
                'No API token. Pass --api-token or set QUEPID_API_TOKEN -- mint one with '
                '`thor user:add_api_key <email>` in Quepid.'
            )

        self.api = QuepidApi(options['api_url'], token, options['timeout'])
        try:
            self.run(**options)
        except ApiError as e:
            raise CommandError(str(e))

    def run(self, **options):
        raise NotImplementedError
