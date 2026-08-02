"""``manage.py create_case <dataset> <case name>`` -- an empty case, configured.

The half of the old ``load_dataset`` that wrote a case rather than data. It
creates the case and its try -- and, given ``--endpoint-url``, the search
endpoint too -- from one of the dataset's templates, so a Qdrant case comes out
with the right engine, mapper and DSL instead of needing them typed into
Quepid's UI afterwards.

Then fill it: ``manage.py load_dataset <dataset> <case id>``.
"""
import json
from pathlib import Path

from django.core.management.base import CommandError

from quepid_datasets.base_command import QuepidCommand
from quepid_datasets.datasets import DATASETS


class Command(QuepidCommand):
    help = (
        'Create an empty Quepid case configured for a dataset -- its try\'s query DSL and '
        'field spec, and optionally the search endpoint to run it against.'
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            'dataset',
            choices=sorted(DATASETS),
            help='Dataset the case is for; its templates decide the search configuration.',
        )
        parser.add_argument(
            'case_name',
            help='Name of the case to create. Quepid does not require it to be unique.',
        )
        parser.add_argument(
            '--template',
            help='Search configuration to build the case around -- query DSL, field spec and, '
                 'for a created endpoint, its engine and mapper. Named per dataset: ' + '; '.join(
                     f'{d.name}: {", ".join(sorted(d.templates))} (default {d.default_template})'
                     for d in DATASETS.values()
                 ),
        )
        parser.add_argument(
            '--search-query-file',
            help='File holding a query DSL as JSON, used instead of the template\'s. Must contain '
                 'the #$query## token wherever the query text belongs. The rest of the template '
                 'still applies.',
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
            '--search-engine',
            choices=['solr', 'es', 'opensearch', 'searchapi'],
            help='Engine of the endpoint created by --endpoint-url. Defaults to the '
                 'template\'s, which is what its DSL and mapper are written for.',
        )
        parser.add_argument(
            '--api-method',
            default='POST',
            help='HTTP method of the endpoint created by --endpoint-url. Default: POST.',
        )
        parser.add_argument(
            '--scorer-id',
            type=int,
            help='Scorer for the case, by id.',
        )
        parser.add_argument(
            '--scorer',
            help='Scorer for the case, by name. Defaults to the dataset\'s, which matches '
                 'its rating scale.',
        )
        parser.add_argument(
            '--field-spec',
            help='Quepid field spec for the try. Defaults to the template\'s.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Resolve everything and report what would be written, then stop.',
        )

    def run(self, **options):
        dataset = DATASETS[options['dataset']]
        template_name, template = self._template(dataset, options)
        query_params = self._query_params(template, options)
        scorer_id = self._scorer_id(dataset, options)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'--dry-run: nothing written. Would create a case "{options["case_name"]}" '
                f'from {dataset.name}/{template_name} with scorer_id={scorer_id}, '
                f'field spec "{options["field_spec"] or template.field_spec}" and DSL '
                f'{query_params}.'
            ))
            return

        endpoint_id = self._search_endpoint_id(dataset, template, options)
        case = self.api.post('/case/', {
            'name': options['case_name'],
            'scorer_id': scorer_id,
            'search_endpoint_id': endpoint_id,
            'search_query': query_params,
            'fields_mapping': options['field_spec'] or template.field_spec,
            'nightly': 1,
        })

        self.stdout.write(self.style.SUCCESS(
            f'Created case {case["id"]} "{options["case_name"]}" '
            f'({dataset.name}/{template_name}).'
        ))
        if endpoint_id is None:
            self.stdout.write(self.style.WARNING(
                'It has no search endpoint, so it cannot run yet -- pick one in Quepid, or '
                'pass --search-endpoint-id / --endpoint-url next time.'
            ))
        if needed := dataset.requires.get(template_name):
            self.stdout.write(self.style.WARNING(f'{template_name} needs {needed}'))

        self.stdout.write(f'Fill it: manage.py load_dataset {dataset.name} {case["id"]}')

    def _template(self, dataset, options):
        """The search configuration to build the case around, by name."""
        name = options['template'] or dataset.default_template
        if name not in dataset.templates:
            raise CommandError(
                f'{dataset.name} has no template "{name}". '
                f'Available: {", ".join(sorted(dataset.templates))}.'
            )
        return name, dataset.templates[name]

    def _query_params(self, template, options):
        """The query DSL to store on the try, as the JSON string Quepid holds.

        ``--search-query-file`` replaces the DSL only: the field spec, engine and
        mapper around it still come from the template, since a hand-written DSL
        is usually a variant of one (a reranked WANDS query, say), not a
        different engine.
        """
        dsl = template.dsl
        if file_path := options['search_query_file']:
            try:
                dsl = json.loads(Path(file_path).read_text())
            except (OSError, ValueError) as e:
                raise CommandError(f'Could not read a query DSL from {file_path}: {e}')

        # CreateCase declares search_query as a str: tries.query_params is a
        # varchar(20000) holding the DSL as text.
        return json.dumps(dsl)

    def _scorer_id(self, dataset, options):
        """Resolve the case's scorer: explicit id, explicit name, the dataset's.

        The dataset names one whose scale covers its ratings. Leaving it to the
        API is not an option: ``CreateCase`` defaults ``scorer_id`` to 5, which
        is whichever scorer happens to be fifth in this Quepid.
        """
        if scorer_id := options['scorer_id']:
            return scorer_id

        name = options['scorer'] or dataset.scorer_name
        scorers = self.api.rows('/scorers/')
        for scorer in scorers:
            if scorer['name'] == name:
                return scorer['id']

        raise CommandError(
            f'No scorer named "{name}" at {self.api.base_url}. Run Quepid\'s db:seed for the '
            f'communal scorers, or pass --scorer-id. Found: '
            f'{", ".join(sorted(s["name"] for s in scorers)) or "none"}.'
        )

    def _search_endpoint_id(self, dataset, template, options):
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
            'name': dataset.name,
            'endpoint_url': url,
            # The engine, the mapper and the proxying belong to the template:
            # they are what makes its DSL and its response readable to Quepid.
            'search_engine': options['search_engine'] or template.search_engine,
            'api_method': options['api_method'],
            'mapper_code': template.mapper_code,
            'proxy_requests': template.proxy_requests,
        })
        self.stdout.write(f'Created search endpoint {endpoint["id"]} at {url}.')
        return endpoint['id']
