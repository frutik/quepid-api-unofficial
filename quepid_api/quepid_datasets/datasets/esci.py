"""Amazon ESCI: shopping queries judged Exact/Substitute/Complement/Irrelevant.

https://github.com/amazon-science/esci-data -- this reads
``shopping_queries_dataset_examples.parquet``, which is queries and judgements
only. The product metadata (titles, images) is a separate ESCI-S download and a
corpus concern, like WANDS' ``product.csv``.

The qdrant-image template below rebuilds the case from these two articles, which
embed the product images with CLIP and search them with an embedding of the
query text:

- part 1: https://frutik.medium.com/how-to-evaluate-image-search-in-qdrant-using-quepid-and-the-hacks-it-takes-part-1-f8167ec5cba3
- part 2: https://frutik.medium.com/how-to-evaluate-image-search-in-qdrant-using-quepid-and-the-hacks-it-takes-part-2-hacks-39ed553cd97a
"""
from .base import Dataset, DatasetQuery, Template, multi_match

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

# Quepid cannot read a Qdrant response, so search_engine="searchapi" hands it to
# this JavaScript instead. Verbatim from part 2, which is also where `thumb`
# comes from: Quepid renders it as the result's thumbnail, which is the whole
# point of judging an image search.
QDRANT_MAPPER = """numberOfResultsMapper = function(data){
  return data.result.length;
};

docsMapper = function(data){
  let docs = [];
  for (let doc of data.result) {
    docs.push ({
      id: doc.id,
      thumb: doc.payload.image,
      title: doc.payload.title,
    });
  }
  return docs;
};"""


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
    scorer_name='nDCG@10',
    templates={
        # Assumes a text index whose document ids are ASINs, with a `title`
        # field -- the natural way to index the ESCI-S metadata, and what makes
        # the judgements above line up with search results as they are.
        'es-title': Template(
            dsl=multi_match(['title']),
            field_spec='id:_id, title:title',
        ),
        # The setup from the articles: CLIP image embeddings in Qdrant, searched
        # with a text embedding of the query. Quepid has no idea how to talk to
        # Qdrant, hence searchapi + a mapper; the vector arrives per query
        # through the options, not through the DSL.
        'qdrant-image': Template(
            dsl={'vector': '#$qOption.clip##', 'limit': 30, 'with_payload': True},
            field_spec='id,title,thumb:thumb',
            search_engine='searchapi',
            mapper_code=QDRANT_MAPPER,
            # The browser calls Qdrant directly in the articles' setup.
            proxy_requests=0,
        ),
    },
    default_template='es-title',
    read=read,
    requires={
        'qdrant-image': (
            '--query-options-file, holding the CLIP vector per query as '
            '{"query text": {"clip": [...]}}, and normally --doc-id-map, since Qdrant '
            'point ids are assigned at index time and are not ASINs. See the articles '
            'in quepid_datasets/datasets/esci.py'
        ),
    },
)
