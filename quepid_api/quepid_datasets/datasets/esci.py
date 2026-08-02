"""Amazon ESCI: shopping queries judged Exact/Substitute/Complement/Irrelevant.

https://github.com/amazon-science/esci-data -- this reads
``shopping_queries_dataset_examples.parquet``, which is queries and judgements
only. The product metadata (titles, images) is a separate ESCI-S download and a
corpus concern, like WANDS' ``product.csv``.

These judgements are what these two articles score, embedding the product images
with CLIP and searching them with an embedding of the query text:

- part 1: https://frutik.medium.com/how-to-evaluate-image-search-in-qdrant-using-quepid-and-the-hacks-it-takes-part-1-f8167ec5cba3
- part 2: https://frutik.medium.com/how-to-evaluate-image-search-in-qdrant-using-quepid-and-the-hacks-it-takes-part-2-hacks-39ed553cd97a

The case that setup needs is built with ``create_case`` flags -- a ``searchapi``
endpoint, ``quepid_datasets/mappers/qdrant.js`` as its ``--mapper-code-file``,
and a ``#$qOption.clip##`` DSL; see the README. Nothing about it belongs to this
dataset: the same ASINs are equally worth running against a plain text index.
"""
from .base import Dataset, DatasetQuery

# esci-data keeps its parquet in Git LFS, so this has to be the github.com/raw
# form -- raw.githubusercontent.com serves the 133-byte pointer (see fetch.py).
EXAMPLES = 'shopping_queries_dataset_examples.parquet'
EXAMPLES_URL = (
    'https://github.com/amazon-science/esci-data/raw/main/shopping_queries_dataset/' + EXAMPLES
)

# The four ESCI labels, as gains on the same 0-3 scale the seeded Quepid scorers
# use: Exact, Substitute, Complement, Irrelevant.
RATINGS = {
    'E': 3,
    'S': 2,
    'C': 1,
    'I': 0,
}

# The slice that gets loaded: the US part of the "small" version's test split --
# 8956 queries and 181701 judgements of the 2.6M rows in the file. That is the
# subset ESCI defines for the ranking task, and the only one whose size is
# comparable to a hand-built Quepid case. Another locale is a one-line edit here.
LOCALE = 'us'
SPLIT = 'test'
SMALL_VERSION = 1


def read(path):
    """Yield ESCI queries with their E/S/C/I judgements, keyed by ASIN.

    pyarrow is imported here rather than at module scope so that ``wands`` keeps
    working, and ``manage.py`` keeps starting, where it is not installed.
    """
    try:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError:
        raise RuntimeError(
            'esci is a parquet dataset and pyarrow is not installed here: pip install pyarrow'
        )

    source = path / EXAMPLES
    if not source.is_file():
        raise FileNotFoundError(source)

    table = pq.read_table(
        source,
        columns=['query', 'product_id', 'product_locale', 'esci_label', 'small_version', 'split'],
    )
    table = table.filter(pc.equal(table['product_locale'], LOCALE))
    table = table.filter(pc.equal(table['split'], SPLIT))
    table = table.filter(pc.equal(table['small_version'], SMALL_VERSION))

    if not table.num_rows:
        raise ValueError(
            f'No rows in {source} for locale {LOCALE}, split {SPLIT}, '
            f'small_version {SMALL_VERSION}.'
        )

    # Judgements for one query are scattered through the file, so group them.
    # Sorting first means a whole query is finished before the next one starts,
    # which is what lets --limit stop early instead of reading 2.6M rows first.
    table = table.sort_by('query')
    queries = table.column('query').to_pylist()
    products = table.column('product_id').to_pylist()
    labels = table.column('esci_label').to_pylist()

    current = None
    ratings = {}
    for query, product_id, label in zip(queries, products, labels):
        if query != current:
            if current is not None:
                yield DatasetQuery(text=current, ratings=ratings)
            current, ratings = query, {}
        rating = RATINGS.get(label)
        if rating is not None:
            # Same rule as WANDS: one rating per doc_id, most generous wins.
            ratings[product_id] = max(rating, ratings.get(product_id, rating))

    if current is not None:
        yield DatasetQuery(text=current, ratings=ratings)


ESCI = Dataset(
    name='esci',
    description='Amazon ESCI shopping queries with Exact/Substitute/Complement/Irrelevant '
                'judgements, keyed by ASIN. The US small-version test split: 8956 queries, '
                '181701 judgements.',
    files={EXAMPLES: EXAMPLES_URL},
    read=read,
)
