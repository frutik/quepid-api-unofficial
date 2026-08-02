"""``manage.py create_case <case name>`` -- an empty case, configured.

The half of the old ``load_dataset`` that wrote a case rather than data. It
creates the case and its try -- and, given ``--endpoint-url``, the search
endpoint too -- from flags alone.

It knows nothing about datasets, deliberately. A case is a search
configuration: a query DSL, a field spec, a scorer and somewhere to send the
query. None of that follows from which judgements you are about to load, and
tying the two together made a case for a *dataset* rather than for an index --
so the same WANDS judgements could not be pointed at a differently built index
without inventing a dataset for it. Everything the command needs now arrives as
a flag, and the defaults are Quepid's own rather than any dataset's.

Then fill it: ``manage.py load_dataset <dataset> <case id>``.
"""
import json
from pathlib import Path

from django.core.management.base import CommandError

from quepid_datasets.base_command import QuepidCommand

# Quepid substitutes the query text for this token when it runs a try, so a
# stored DSL carries it verbatim. `#$qOption.<name>##` does the same for a key of
# the query's options -- which is how a per-query vector reaches the engine, and
# what load_dataset's --query-options-file fills in.
QUERY_TOKEN = '#$query##'

# What the notebooks at the repo root post, and the shape of Quepid's own
# Elasticsearch default. `*` rather than named fields because this command has no
# idea what is in your index; --search-fields is how you say.
DEFAULT_SEARCH_FIELDS = ['*']

# Quepid's Elasticsearch default. Anything richer names fields that only some
# index has.
DEFAULT_FIELD_SPEC = 'id:_id'

# Scale 0-3, which is what every reader in quepid_datasets/datasets/ produces.
# Resolved by name against the running Quepid, never passed through as an id:
# CreateCase defaults scorer_id to 5, which is whichever scorer happens to be
# fifth there.
DEFAULT_SCORER = 'nDCG@10'


def multi_match(fields):
    """The plain Elasticsearch query used when no DSL file is given."""
    return {
        'query': {
            'multi_match': {
                'query': QUERY_TOKEN,
                'fields': list(fields),
            }
        }
    }


class Command(QuepidCommand):
    help = (
        'Create an empty Quepid case -- its try\'s query DSL and field spec, and optionally '
        'the search endpoint to run it against. Fill it with `manage.py load_dataset`.'
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            'case_name',
            help='Name of the case to create. Quepid does not require it to be unique.',
        )
        parser.add_argument(
            '--search-query-file',
            help='File holding the try\'s query DSL as JSON. Must contain the '
                 f'{QUERY_TOKEN} token wherever the query text belongs -- Quepid substitutes '
                 'each query for it. Without this, a multi_match over --search-fields.',
        )
        parser.add_argument(
            '--search-fields',
            metavar='FIELDS',
            help='Comma-separated fields for the default multi_match DSL, boosts included, e.g. '
                 f'`--search-fields "name^2,description"`. Default: {",".join(DEFAULT_SEARCH_FIELDS)}. '
                 'Not usable with --search-query-file, which replaces the DSL outright.',
        )
        parser.add_argument(
            '--field-spec',
            default=DEFAULT_FIELD_SPEC,
            help='Quepid field spec for the try -- how a search hit becomes a displayable '
                 f'document, e.g. `id:_id, title:name`. Default: {DEFAULT_FIELD_SPEC}.',
        )
        parser.add_argument(
            '--search-endpoint-id',
            type=int,
            help='Existing search endpoint to point the case at.',
        )
        parser.add_argument(
            '--endpoint-url',
            help='Create a search endpoint at this URL instead, and point the case at it. '
                 'Must be reachable from Quepid, not from you -- e.g. '
                 'http://quepid-api-elasticsearch:9200/wands/_search.',
        )
        parser.add_argument(
            '--endpoint-name',
            help='Name of the endpoint created by --endpoint-url. Defaults to the case name.',
        )
        parser.add_argument(
            '--search-engine',
            choices=['solr', 'es', 'opensearch', 'searchapi'],
            default='es',
            help='Engine of the endpoint created by --endpoint-url. Default: es. Use searchapi '
                 'with --mapper-code-file for an engine Quepid cannot read by itself.',
        )
        parser.add_argument(
            '--api-method',
            default='POST',
            help='HTTP method of the endpoint created by --endpoint-url. Default: POST.',
        )
        parser.add_argument(
            '--mapper-code-file',
            help='File of JavaScript mapping a non-Solr/ES response into documents Quepid can '
                 'show -- `docsMapper` and `numberOfResultsMapper`. Only meaningful with '
                 '--search-engine searchapi.',
        )
        parser.add_argument(
            '--proxy-requests',
            type=int,
            choices=[0, 1],
            default=1,
            help='1 has Quepid make the search request server-side, so the engine only has to '
                 'be reachable from Quepid. 0 has the browser call it directly. Default: 1.',
        )
        parser.add_argument(
            '--scorer-id',
            type=int,
            help='Scorer for the case, by id.',
        )
        parser.add_argument(
            '--scorer',
            default=DEFAULT_SCORER,
            help=f'Scorer for the case, by name. Default: {DEFAULT_SCORER}, whose 0-3 scale '
                 'covers the ratings every dataset here produces.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Resolve everything and report what would be written, then stop.',
        )

    def run(self, **options):
        query_params = self._query_params(options)
        scorer_id = self._scorer_id(options)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'--dry-run: nothing written. Would create a case "{options["case_name"]}" '
                f'with scorer_id={scorer_id}, field spec "{options["field_spec"]}" and DSL '
                f'{query_params}.'
            ))
            return

        endpoint_id = self._search_endpoint_id(options)
        case = self.api.post('/case/', {
            'name': options['case_name'],
            'scorer_id': scorer_id,
            'search_endpoint_id': endpoint_id,
            'search_query': query_params,
            'fields_mapping': options['field_spec'],
            'nightly': 1,
        })

        self.stdout.write(self.style.SUCCESS(
            f'Created case {case["id"]} "{options["case_name"]}".'
        ))
        if endpoint_id is None:
            self.stdout.write(self.style.WARNING(
                'It has no search endpoint, so it cannot run yet -- pick one in Quepid, or '
                'pass --search-endpoint-id / --endpoint-url next time.'
            ))

        self.stdout.write(f'Fill it: manage.py load_dataset <dataset> {case["id"]}')

    def _query_params(self, options):
        """The query DSL to store on the try, as the JSON string Quepid holds.

        Either a file or the default multi_match, never a mix: a hand-written DSL
        that reranks or vector-searches has nowhere to put a field list, so
        silently ignoring --search-fields alongside one would be a lie.
        """
        file_path = options['search_query_file']
        if file_path and options['search_fields']:
            raise CommandError(
                '--search-fields only builds the default DSL, which --search-query-file '
                'replaces. Pass one or the other.'
            )

        if file_path:
            try:
                dsl = json.loads(Path(file_path).read_text())
            except (OSError, ValueError) as e:
                raise CommandError(f'Could not read a query DSL from {file_path}: {e}')
            if QUERY_TOKEN not in json.dumps(dsl):
                # Not fatal -- a DSL can be driven entirely by #$qOption.<name>##,
                # as the Qdrant setup is -- but a missing token usually means the
                # same query runs for all 480 rows.
                self.stdout.write(self.style.WARNING(
                    f'{file_path} contains no {QUERY_TOKEN}, so every query will run the '
                    f'same search unless it uses #$qOption.<name>## instead.'
                ))
        elif fields := options['search_fields']:
            names = [f.strip() for f in fields.split(',') if f.strip()]
            if not names:
                raise CommandError(f'--search-fields "{fields}" names no fields.')
            dsl = multi_match(names)
        else:
            dsl = multi_match(DEFAULT_SEARCH_FIELDS)

        # CreateCase declares search_query as a str: tries.query_params is a
        # varchar(20000) holding the DSL as text.
        return json.dumps(dsl)

    def _scorer_id(self, options):
        """Resolve the case's scorer: explicit id, else the name, resolved.

        Leaving it to the API is not an option: ``CreateCase`` defaults
        ``scorer_id`` to 5, which is whichever scorer happens to be fifth in this
        Quepid.
        """
        if scorer_id := options['scorer_id']:
            return scorer_id

        name = options['scorer']
        scorers = self.api.rows('/scorers/')
        for scorer in scorers:
            if scorer['name'] == name:
                return scorer['id']

        raise CommandError(
            f'No scorer named "{name}" at {self.api.base_url}. Run Quepid\'s db:seed for the '
            f'communal scorers, or pass --scorer-id. Found: '
            f'{", ".join(sorted(s["name"] for s in scorers)) or "none"}.'
        )

    def _search_endpoint_id(self, options):
        """The endpoint the case's try points at, existing or newly created."""
        if endpoint_id := options['search_endpoint_id']:
            # Cheap existence check, so a typo fails before the case exists
            # rather than as a bare 400 from create_case.
            response = self.api.request('GET', f'/search_endpoints/{endpoint_id}/')
            if response.status_code == 404:
                raise CommandError(
                    f'No search endpoint with id {endpoint_id} at {self.api.base_url}.'
                )
            if response.status_code != 200:
                raise CommandError(
                    f'GET {self.api.base_url}/search_endpoints/{endpoint_id}/ -> '
                    f'{response.status_code}: {response.text[:500]}'
                )
            return endpoint_id

        if not (url := options['endpoint_url']):
            return None

        endpoint = self.api.post('/search_endpoints/', {
            'name': options['endpoint_name'] or options['case_name'],
            'endpoint_url': url,
            'search_engine': options['search_engine'],
            'api_method': options['api_method'],
            'mapper_code': self._mapper_code(options),
            'proxy_requests': options['proxy_requests'],
        })
        self.stdout.write(f'Created search endpoint {endpoint["id"]} at {url}.')
        return endpoint['id']

    def _mapper_code(self, options):
        """The response mapper for a searchapi endpoint, read from its file."""
        if not (file_path := options['mapper_code_file']):
            return None

        try:
            return Path(file_path).read_text()
        except OSError as e:
            raise CommandError(f'Could not read mapper code from {file_path}: {e}')
