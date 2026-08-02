"""The datasets ``load_dataset`` knows how to read.

Getting a corpus *into* a search engine is not this package's job -- see the
notebooks at the repo root, which index WANDS into Elasticsearch, and the
articles linked from ``esci.py``, which embed product images into Qdrant.
Deciding how to *search* it is not this package's job either: that is
``create_case``'s flags. This package supplies one thing, queries and their
judgements.

Layout, and the reason for it:

- ``base.py`` -- what every dataset is made of: ``Dataset`` and ``DatasetQuery``.
- one module per dataset (``wands.py``, ``esci.py``), importing from ``base``.
- this file -- the package's public surface, re-exporting both.

So imports run one way and nothing here is circular. To add a dataset: write
``<name>.py`` with a ``read(path)`` yielding ``DatasetQuery`` and a ``Dataset``,
then add it to ``DATASETS`` below. Nothing in the commands is dataset-aware.
"""
from .base import Dataset, DatasetQuery
from .esci import ESCI
from .wands import WANDS

# Every dataset the notebooks and articles behind this project use. wands.ipynb,
# MMR.ipynb and qwen-reranker.ipynb all build their cases from WANDS; the
# reranked and vector variants differ only in the query DSL, which
# `create_case --search-query-file` supplies without needing a dataset of their
# own.
DATASETS = {dataset.name: dataset for dataset in [WANDS, ESCI]}

__all__ = [
    'DATASETS',
    'ESCI',
    'WANDS',
    'Dataset',
    'DatasetQuery',
]
