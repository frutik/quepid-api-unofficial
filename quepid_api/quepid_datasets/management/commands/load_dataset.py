"""``manage.py load_dataset <dataset> <case id>`` -- fill a case with a dataset.

wands.ipynb posts 480 queries and ~233k ratings into a case through this
project's REST API; the ESCI articles linked from
``quepid_datasets/datasets/esci.py`` do the same for a Qdrant collection of
image embeddings. So does this command, request for request: it is an API
*client*, not another writer against the `quepid` alias, and it touches no model
in this project.

That is the point. Every load is a few hundred thousand calls through nginx,
gunicorn, django-ninja and the ORM against a real Rails-owned schema -- the same
path ``tests/`` exercises, at a volume the test suite will never reach. A column
that moved under ``quepid/models.py`` shows up here as a 400 with the reason in
the body, which is why failures are reported with their response text rather
than counted.

The case has to exist: make one with ``manage.py create_case``, or in Quepid,
and find its id with ``manage.py list_cases``. Keeping creation out of here means
a dataset can be loaded into a case configured any way at all, and that reloading
never quietly makes a second case.

Nothing here says where a dataset's files are, either. It takes a name; the files
come from GitHub on first use and from ``TMP_DIR`` afterwards (``fetch.py``).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import islice
from pathlib import Path

from django.core.management.base import CommandError

from quepid_datasets import fetch
from quepid_datasets.base_command import QuepidCommand
from quepid_datasets.client import ApiError
from quepid_datasets.datasets import DATASETS

# Failed rating posts kept for the error message. The rest are only counted --
# a broken schema fails identically 233k times.
FAILURE_SAMPLES = 5


class Command(QuepidCommand):
    help = (
        'Load a relevance dataset -- its queries and judgements -- into an existing Quepid '
        'case, over this project\'s REST API. Needs a running API and a Quepid-issued token, '
        'not database credentials.'
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            'dataset',
            choices=sorted(DATASETS),
            help='Dataset to load. ' + ' '.join(
                f'{d.name}: {d.description}' for d in DATASETS.values()
            ),
        )
        parser.add_argument(
            'case_id',
            type=int,
            help='Case to load into. It must already exist -- see create_case and list_cases.',
        )

        parser.add_argument(
            '--query-options-file',
            help='JSON object mapping query text to that query\'s options, e.g. '
                 '{"laptop stand": {"clip": [0.1, ...]}}. A DSL reaches them as '
                 '#$qOption.clip##, which is how a per-query vector gets to the engine. '
                 'Queries not listed are created without options.',
        )
        parser.add_argument(
            '--doc-id-map',
            help='JSON object mapping the dataset\'s document ids to the ids the search engine '
                 'returns, e.g. {"B07XYZ": 41} for a Qdrant point id. Judgements for unmapped '
                 'documents are dropped and counted.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Load only the first N queries. Useful for a smoke test.',
        )
        parser.add_argument(
            '--skip-ratings',
            action='store_true',
            help='Create the queries but none of their judgements.',
        )
        parser.add_argument(
            '--append',
            action='store_true',
            help='Load even though the case already has queries. Without it, a case that is '
                 'not empty is refused -- reloading otherwise duplicates every query.',
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=8,
            help='Concurrent rating posts. Default: 8. Use 1 to keep the load strictly '
                 'sequential, as the notebooks do.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Resolve everything and report what would be written, then stop.',
        )

    def run(self, **options):
        dataset = DATASETS[options['dataset']]
        case_id = options['case_id']

        case = self._case(case_id, options)
        query_options = self._json_map(options['query_options_file'], '--query-options-file')
        doc_ids = self._json_map(options['doc_id_map'], '--doc-id-map')

        # Read the whole dataset before writing anything: a failed download or a
        # malformed file should fail before the case is half-filled.
        queries = self._read(dataset, options['limit'])
        queries = self._remap(queries, doc_ids)
        judgements = sum(len(q.ratings) for q in queries)
        self.stdout.write(
            f'{len(queries)} queries, {judgements} judgements'
            + (' (ratings will be skipped)' if options['skip_ratings'] else '')
        )

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'--dry-run: nothing written. Would post {len(queries)} queries and '
                f'{0 if options["skip_ratings"] else judgements} ratings to case {case_id} '
                f'"{case.get("case_name")}".'
            ))
            return

        # A failure from here leaves rows behind: HTTP writes are not one
        # transaction, and there is no bulk endpoint to make them one.
        try:
            created = self._load_queries(case_id, queries, query_options)

            failures = []
            if not options['skip_ratings']:
                failures = self._load_ratings(created, options['workers'])
        except ApiError as e:
            raise CommandError(
                f'{e}\nCase {case_id} is half-loaded -- clear it in Quepid, or reload with '
                f'--append once the cause is fixed.'
            )

        self._verify(case_id, created, options['skip_ratings'])

        if failures:
            raise CommandError(
                f'{len(failures)} of {judgements} ratings failed on case {case_id}. '
                f'First failures:\n  ' + '\n  '.join(failures[:FAILURE_SAMPLES])
            )

        self.stdout.write(self.style.SUCCESS(
            f'Case {case_id}: {len(created)} queries, '
            f'{0 if options["skip_ratings"] else judgements} ratings.'
        ))

    # -- what is being loaded into ------------------------------------------

    def _case(self, case_id, options):
        """The case, refusing one that already holds queries.

        Loading a dataset twice is the expensive mistake here: nothing about a
        query is unique, so the second run doubles every query and every
        judgement rather than updating anything.
        """
        response = self.api.request('GET', f'/case/{case_id}/')
        if response.status_code == 404:
            raise CommandError(
                f'No case {case_id} at {self.api.base_url}. Create one with '
                f'`manage.py create_case`, or list them with `manage.py list_cases`.'
            )
        if response.status_code != 200:
            raise ApiError(
                f'GET {self.api.base_url}/case/{case_id}/ -> '
                f'{response.status_code}: {response.text[:500]}'
            )
        case = response.json()
        self.stdout.write(f'Loading into case {case_id} "{case.get("case_name")}".')

        existing = self.api.count(f'/query/{case_id}/')
        if existing and not options['append']:
            raise CommandError(
                f'Case {case_id} "{case.get("case_name")}" already has {existing} queries. '
                f'Pass --append to add to them, or load into a fresh case.'
            )
        if existing:
            self.stdout.write(self.style.WARNING(
                f'--append: it already has {existing} queries.'
            ))
        return case

    # -- resolving the inputs -----------------------------------------------

    def _json_map(self, file_path, flag):
        """Read one of the JSON lookup files, or return an empty mapping."""
        if not file_path:
            return {}

        try:
            mapping = json.loads(Path(file_path).read_text())
        except (OSError, ValueError) as e:
            raise CommandError(f'Could not read {flag} from {file_path}: {e}')

        if not isinstance(mapping, dict):
            raise CommandError(
                f'{flag} must hold a JSON object, {file_path} holds a {type(mapping).__name__}.'
            )
        return mapping

    def _remap(self, queries, doc_ids):
        """Translate dataset document ids into the ids the engine returns.

        A judgement whose document is not in the map cannot score anything -- no
        result will ever carry that id -- so it is dropped rather than posted.
        Reported, because a map that covers almost nothing is a mistake worth
        seeing before 100k pointless requests.
        """
        if not doc_ids:
            return queries

        remapped = []
        kept = dropped = 0
        for query in queries:
            ratings = {}
            for doc_id, rating in query.ratings.items():
                if doc_id in doc_ids:
                    ratings[str(doc_ids[doc_id])] = rating
                    kept += 1
                else:
                    dropped += 1
            remapped.append(replace(query, ratings=ratings))

        message = f'--doc-id-map: {kept} judgements mapped, {dropped} dropped as unmapped.'
        self.stdout.write(self.style.WARNING(message) if dropped else message)
        return remapped

    def _read(self, dataset, limit):
        """The dataset's queries, downloading its files if this is the first run.

        Cached under TMP_DIR, so the 51 MB ESCI parquet is fetched once. A file
        that is somehow unreadable is a cache to delete, which is why the path is
        in the error rather than only in ``fetch.py``.
        """
        try:
            path = fetch.ensure(dataset, self.stdout.write)
        except fetch.FetchError as e:
            raise CommandError(str(e))

        self.stdout.write(f'Reading {dataset.name} from {path} ...')
        try:
            return list(islice(dataset.read(path), limit))
        except FileNotFoundError as e:
            raise CommandError(f'{e} is missing. Delete {path} and run again to re-download.')
        except KeyError as e:
            raise CommandError(f'Unexpected dataset format under {path}: no column {e}.')
        except (ValueError, RuntimeError) as e:
            raise CommandError(f'{dataset.name}: {e}')

    # -- the load itself ----------------------------------------------------

    def _load_queries(self, case_id, queries, query_options):
        """POST every query, returning (query_id, ratings) for the rating pass.

        Sequential on purpose: the ratings are keyed by the ids these responses
        hand back, and 480 requests is not what makes a load slow.
        """
        created = []
        matched = 0
        for position, dataset_query in enumerate(queries, start=1):
            payload = {'query_text': dataset_query.text}
            if options := query_options.get(dataset_query.text):
                # queries.options is a JSON column; a DSL reads a key back out
                # of it as #$qOption.<key>##, which is how a per-query vector
                # reaches the engine.
                payload['query_options'] = options
                matched += 1

            row = self.api.post(f'/query/{case_id}/', payload)
            created.append((row['id'], dataset_query.ratings))

            if position % 50 == 0 or position == len(queries):
                self.stdout.write(f'  {position}/{len(queries)} queries')

        if query_options:
            message = f'--query-options-file: options attached to {matched}/{len(queries)} queries.'
            self.stdout.write(
                self.style.WARNING(message) if matched < len(queries) else message
            )
        return created

    def _load_ratings(self, created, workers):
        """POST every judgement, returning a description of each one that failed.

        One request per judgement, because that is the only rating endpoint this
        API has. Failures are collected rather than raised so that a schema
        change shows up as "233448 failed, here is the first reason" instead of
        stopping on the first one with nothing loaded.
        """
        posts = [
            (query_id, doc_id, rating)
            for query_id, ratings in created
            for doc_id, rating in ratings.items()
        ]
        if not posts:
            return []

        failures = []
        done = 0

        def post(item):
            query_id, doc_id, rating = item
            response = self.api.request(
                'POST',
                f'/rating/query/{query_id}/rating/',
                json={'doc_id': str(doc_id), 'rating': rating},
            )
            if response.status_code != 200:
                return (
                    f'query {query_id} doc {doc_id} -> '
                    f'{response.status_code}: {response.text[:200]}'
                )
            return None

        # Results are consumed here, on the main thread, so the counters below
        # need no lock -- only `post` itself runs in the pool.
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            for failure in pool.map(post, posts):
                done += 1
                if failure is not None:
                    failures.append(failure)
                if done % 5000 == 0 or done == len(posts):
                    self.stdout.write(
                        f'  {done}/{len(posts)} ratings'
                        + (f' ({len(failures)} failed)' if failures else '')
                    )

        return failures

    def _verify(self, case_id, created, skip_ratings):
        """Read the case back and check the API agrees about what was written.

        A write that returns 200 and a read that disagrees with it is exactly the
        kind of drift this command is well placed to catch, so the counts are
        checked rather than assumed. Reported as warnings: the rows are already
        there, and the operator decides what a mismatch means.
        """
        if not created:
            return

        # Spot-check one query's ratings rather than all of them: a per-query
        # count is a request each, and a systematic rating failure would already
        # be in the failure list.
        if not skip_ratings:
            query_id, ratings = created[0]
            counted = self.api.count(f'/rating/query/{query_id}/rating/')
            if counted != len(ratings):
                self.stdout.write(self.style.WARNING(
                    f'Query {query_id} reports {counted} ratings, {len(ratings)} were sent.'
                ))
