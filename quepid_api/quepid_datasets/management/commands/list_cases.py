"""``manage.py list_cases`` -- which cases exist, and which one to load into.

``load_dataset`` takes a case id, so something has to tell you what the ids are.
This is that, over the same REST API: ``GET /case/``, newest first, with the
query count that says whether a case has been filled already.
"""
from quepid_datasets.base_command import QuepidCommand

# Names are free text and get long; the id is what the other commands need.
NAME_WIDTH = 44


class Command(QuepidCommand):
    help = 'List Quepid cases -- id, name, queries -- to find one to load a dataset into.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--archived',
            action='store_true',
            help='List archived cases instead of active ones. DELETE /api/case/{id}/ is a soft '
                 'delete, so this is where deleted cases went.',
        )
        parser.add_argument(
            '--search',
            help='Only cases whose name contains this text, case-insensitively.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='How many to show, newest first. Default: 50. 0 for all.',
        )
        parser.add_argument(
            '--no-counts',
            action='store_false',
            dest='counts',
            help='Skip the query count, which costs one request per case listed.',
        )

    def run(self, **options):
        # Spelled out rather than passing a Python bool: requests would send
        # "True", and what the endpoint's `archived: bool` makes of that is
        # pydantic's business, not something worth depending on.
        cases = self.api.rows('/case/', archived='true' if options['archived'] else 'false')

        if search := options['search']:
            cases = [c for c in cases if search.lower() in (c.get('case_name') or '').lower()]

        # Newest first: the case you just created is the one you are looking for.
        # The API returns them in whatever order MySQL felt like.
        cases.sort(key=lambda case: case['id'], reverse=True)
        shown = cases[:options['limit']] if options['limit'] else cases

        if not shown:
            self.stdout.write(
                'No archived cases.' if options['archived'] else
                'No cases. Create one with `manage.py create_case`.'
            )
            return

        header = f'{"ID":>6}  {"NAME":<{NAME_WIDTH}}  {"SCORER":>6}  {"TRIES":>5}'
        if options['counts']:
            header += f'  {"QUERIES":>7}'
        self.stdout.write(header)

        for case in shown:
            name = case.get('case_name') or ''
            if len(name) > NAME_WIDTH:
                name = name[:NAME_WIDTH - 1] + '…'
            row = (
                f'{case["id"]:>6}  {name:<{NAME_WIDTH}}  '
                f'{case.get("scorer_id") or "-":>6}  {case.get("last_try_number") or "-":>5}'
            )
            if options['counts']:
                queries = self.api.count(f'/query/{case["id"]}/')
                row += f'  {queries:>7}'
            self.stdout.write(row)

        self.stdout.write(
            f'{len(shown)} of {len(cases)} '
            + ('archived cases.' if options['archived'] else 'cases.')
        )
