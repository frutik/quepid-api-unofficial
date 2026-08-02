"""What every dataset in this package is made of.

A dataset here is whatever a Quepid case needs to be worth opening: a list of
query strings, the judgements for each one on a 0-3 scale, and one or more
*templates* -- a search configuration (query DSL, field spec, engine, response
mapper) that makes the case runnable against an engine holding that dataset's
corpus.

These definitions live here rather than in ``__init__`` so that the dependency
runs one way: ``wands`` and ``esci`` import from ``base``, and ``__init__``
imports from all three to publish them. Putting them in ``__init__`` instead
makes the package and its dataset modules import each other, which happens to
work and stops working the moment the order changes.
"""
from dataclasses import dataclass, field
from typing import Callable

# Quepid substitutes the query text for this token when it runs a try, so a
# stored query DSL carries it verbatim. `#$qOption.<name>##` does the same for a
# key of the query's options -- which is how a per-query vector reaches the
# engine (see the ESCI qdrant-image template).
QUERY_TOKEN = '#$query##'


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
class Template:
    """A search configuration: the query DSL plus what serving it requires.

    Separate from the dataset because the same judgements are worth running
    against different engines -- ESCI's are used against both a text index and a
    Qdrant collection of image embeddings, which agree on nothing else.
    """

    dsl: dict
    # Quepid field spec: how to turn a search hit into a displayable document.
    field_spec: str
    search_engine: str = 'es'
    # JavaScript that maps a non-Solr/ES response, for search_engine="searchapi".
    mapper_code: str = None
    # 1 lets Quepid make the request server-side, so the engine only has to be
    # reachable from Quepid. 0 has the browser call it directly.
    proxy_requests: int = 1


@dataclass(frozen=True)
class Dataset:
    """A dataset and the case defaults that go with it."""

    name: str
    description: str
    # filename -> URL. Downloaded into TMP_DIR on first use and read from there
    # afterwards, so no command has to be told where a dataset lives. Mind which
    # GitHub URL form an LFS repository needs -- see fetch.py.
    files: dict
    # Scorer to use when neither --scorer nor --scorer-id is given. Must have a
    # scale covering the ratings the reader produces.
    scorer_name: str
    templates: dict
    default_template: str
    # read(directory) -> iterable of DatasetQuery, over the files above.
    read: Callable
    # Extra files the templates below need, keyed by the flag that supplies
    # them. Printed when a template is chosen, since a case built without them
    # scores nothing.
    requires: dict = field(default_factory=dict)


def multi_match(fields):
    """The plain Elasticsearch query both text templates are built from."""
    return {
        'query': {
            'multi_match': {
                'query': QUERY_TOKEN,
                'fields': fields,
            }
        }
    }
