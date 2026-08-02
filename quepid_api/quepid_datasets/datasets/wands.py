"""Wayfair WANDS: 480 product queries with Exact/Partial/Irrelevant judgements.

https://github.com/wayfair/WANDS/tree/main/dataset -- three TSVs, of which this
downloads two: ``query.csv`` and ``label.csv``. ``product.csv`` is the corpus (90
MB of it), which belongs in a search engine, not in Quepid; wands.ipynb at the
repo root indexes it into Elasticsearch under the mapping the templates below
assume.
"""
import csv
from collections import defaultdict

from .base import Dataset, DatasetQuery, Template, multi_match

# Not an LFS repository, so the plain raw host serves the bytes (see fetch.py).
FILES = 'https://raw.githubusercontent.com/wayfair/WANDS/main/dataset/'

# WANDS ships three labels; Quepid wants numbers on the case scorer's scale.
# 0/2/3 is the mapping the notebooks at the repo root use, so cases loaded here
# score the same as the ones in wands.ipynb.
RATINGS = {
    'Exact': 3,
    'Partial': 2,
    'Irrelevant': 0,
}


def _read_tsv(path):
    """Rows of a WANDS TSV as dicts.

    ``QUOTE_NONE`` because these files are plain tab-separated text, not CSV:
    three of the 480 queries contain a bare double quote (``48" bathroom
    vanity``), which the default quoting would swallow along with the rest of
    the line.
    """
    if not path.is_file():
        raise FileNotFoundError(path)

    with path.open(newline='', encoding='utf-8') as handle:
        yield from csv.DictReader(handle, delimiter='\t', quoting=csv.QUOTE_NONE)


def read(path):
    """Yield WANDS queries in dataset order, each with its product judgements.

    ``label.csv`` is 233k rows and is read into memory whole -- it is ~6 MB of
    text and there is no order guarantee that would let us stream it alongside
    ``query.csv``.
    """
    ratings = defaultdict(dict)
    for row in _read_tsv(path / 'label.csv'):
        rating = RATINGS.get(row['label'])
        if rating is None:
            continue
        for_query = ratings[row['query_id']]
        doc_id = row['product_id']
        # 1467 (query, product) pairs are listed twice, 14 of them with
        # different labels. A Quepid query holds one rating per doc_id, so the
        # most generous label wins -- picking by file order would be arbitrary.
        for_query[doc_id] = max(rating, for_query.get(doc_id, rating))

    for row in _read_tsv(path / 'query.csv'):
        yield DatasetQuery(
            text=row['query'],
            ratings=ratings.get(row['query_id'], {}),
        )


WANDS = Dataset(
    name='wands',
    description='Wayfair WANDS: 480 product queries, 233k Exact/Partial/Irrelevant judgements.',
    files={
        'query.csv': FILES + 'query.csv',
        'label.csv': FILES + 'label.csv',
    },
    # Scale 0-3, which is what RATINGS produces.
    scorer_name='nDCG@10',
    templates={
        # Both match the mapping the notebooks index products under: an ES _id
        # per product, with `name` and `description` as text fields.
        'baseline': Template(dsl=multi_match(['name', 'description']), field_spec='id:_id, title:name'),
        'boosted': Template(dsl=multi_match(['name^2', 'description']), field_spec='id:_id, title:name'),
    },
    default_template='baseline',
    read=read,
)
