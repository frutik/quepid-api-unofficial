"""What every dataset in this package is made of.

A dataset here is judgements and nothing else: a list of query strings and, for
each one, its documents rated on a 0-3 scale, plus where those files come from.

There is deliberately no search configuration in here. Which DSL, field spec,
engine and endpoint a case runs is ``create_case``'s business, supplied as
flags: the same judgements are worth running against indexes built in ways this
package cannot anticipate, so a dataset that also decided how to search would
only be right for the one index it was written against.

These definitions live here rather than in ``__init__`` so that the dependency
runs one way: ``wands`` and ``esci`` import from ``base``, and ``__init__``
imports from all three to publish them. Putting them in ``__init__`` instead
makes the package and its dataset modules import each other, which happens to
work and stops working the moment the order changes.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DatasetQuery:
    """One query and its judgements, already in Quepid's terms."""

    text: str
    # doc_id -> rating. doc_id is the id *the dataset* uses -- an ASIN, a product
    # id -- as a string, because `ratings.doc_id` is a varchar(500). It only
    # scores anything if the search engine returns the same id; when it does not
    # (Qdrant point ids, say) the command's --doc-id-map translates it.
    ratings: dict


@dataclass(frozen=True)
class Dataset:
    """A dataset: its files, and how to read judgements out of them."""

    name: str
    description: str
    # filename -> URL. Downloaded into TMP_DIR on first use and read from there
    # afterwards, so no command has to be told where a dataset lives. Mind which
    # GitHub URL form an LFS repository needs -- see fetch.py.
    files: dict
    # read(directory) -> iterable of DatasetQuery, over the files above.
    read: Callable
