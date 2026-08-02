"""The datasets ``load_dataset`` knows how to read.

Getting a corpus *into* a search engine is not this package's job -- see the
notebooks at the repo root, which index WANDS into Elasticsearch, and the
articles linked from ``esci.py``, which embed product images into Qdrant. This
package only fills the Quepid side: queries, judgements, and the search
configuration a case needs to run against that engine.

Layout, and the reason for it:

- ``base.py`` -- what every dataset is made of: ``Dataset``, ``Template``,
  ``DatasetQuery`` and the shared helpers.
- one module per dataset (``wands.py``, ``esci.py``), importing from ``base``.
- this file -- the package's public surface, re-exporting both.

So imports run one way and nothing here is circular. To add a dataset: write
``<name>.py`` with a ``read(path, **options)`` yielding ``DatasetQuery`` and a
``Dataset``, then add it to ``DATASETS`` below. Nothing in the command is
dataset-aware.
"""
from .base import QUERY_TOKEN, Dataset, DatasetQuery, Template, multi_match
from .esci import ESCI
from .wands import WANDS

# Every dataset the notebooks and articles behind this project use. wands.ipynb,
# MMR.ipynb and qwen-reranker.ipynb all build their cases from WANDS; the
# reranked and vector variants differ only in the query DSL, which
# --search-query-file supplies without needing a dataset of their own.
DATASETS = {dataset.name: dataset for dataset in [WANDS, ESCI]}

__all__ = [
    'DATASETS',
    'ESCI',
    'QUERY_TOKEN',
    'WANDS',
    'Dataset',
    'DatasetQuery',
    'Template',
    'multi_match',
]
