import json
import logging

from ninja import Router
from django.db import connections, transaction
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Book, QueryDocPair, Judgement, _as_scale
from typing import List
from ninja.pagination import paginate
from ninja import Schema

from .utils import _by_pk, _member_teams, _team_for_new_row


logger = logging.getLogger(__name__)

router = Router(tags=["Books management"])


class CreateBook(Schema):
    name: str
    #: The team to share the new book with. Omitted, it is resolved from the
    #: caller's memberships (see ``_team_for_new_row``); 0 means "no team".
    team_id: int = None
    support_implicit_judgements: bool = False
    show_rank: bool = False
    description: str = ""
    #: The ratings a judge may give, e.g. [0, 1, 2, 3]. Quepid's own UI copies
    #: this off the scorer you pick when creating a book; nothing picks a scorer
    #: here, so a book made through this API has no scale unless you say so --
    #: and a book with no scale renders no rating buttons at all.
    scale: List[int] = None
    #: What each rating means, e.g. {"0": "Irrelevant", "3": "Exact"}. Keys are
    #: strings, since Rails reads them with ``dig(score.to_s)``.
    scale_with_labels: dict = None


class UpdateBook(Schema):
    name: str = None
    support_implicit_judgements: bool = None
    show_rank: bool = None
    description: str = None
    scale: List[int] = None
    scale_with_labels: dict = None


class CreateQueryDocPair(Schema):
    """One pair to put in a book. Posted in batches -- see create_query_doc_pairs."""
    query_text: str
    doc_id: str
    position: int = None
    #: The document itself, as Quepid should display it while judging. Written
    #: to the TEXT column ``document_fields`` as JSON, the way PopulateBookJob
    #: does with ``pair[:document_fields].to_json``.
    document_fields: dict = None
    information_need: str = None
    notes: str = None
    query_options: dict = None


class QueryDocPairsWritten(Schema):
    created: int
    skipped: int


class CreateJudgement(Schema):
    """One rater's verdict on one pair, addressed the way the pair was posted.

    By ``(query_text, doc_id)`` rather than by pair id, so a caller loading a
    labelled dataset never has to read back the ids this API assigned -- the
    same key ``create_query_doc_pairs`` identifies a pair by.
    """
    query_text: str
    doc_id: str
    #: The rating, which must be one of the book's ``scale`` when it has one.
    #: May be omitted only for an unrateable or judge_later verdict, matching
    #: Rails' ``validates :rating, presence: true, unless: :rating_not_required?``.
    rating: float = None
    #: Why. Written by the LLM judge; free text for a human.
    explanation: str = None
    #: "I can't tell" -- a deliberate non-answer, not a missing one.
    unrateable: bool = False
    #: "Come back to this one."
    judge_later: bool = False


class JudgementsWritten(Schema):
    created: int
    updated: int
    unchanged: int
    #: Rows naming a (query_text, doc_id) this book does not hold. Counted
    #: rather than raised: one stale row should not reject a batch of 500, but
    #: a caller loading ground truth wants to know the labels went nowhere.
    unknown: int


def _dump_scale(scale):
    """A list of ratings, as the comma-joined varchar ``books.scale`` holds.

    Mirrors ``ScaleSerializer.dump``, sorted the way its ``load`` returns it so
    a value written here reads back identically. An empty list is stored as
    NULL, which is what a book Quepid has never given a scale looks like.
    """
    return ','.join(str(value) for value in sorted(scale)) if scale else None


def _scale_is_locked(book, scale):
    """Whether Rails would refuse this scale change. Returns a reason, or None.

    ``Book#scale_cannot_be_changed_if_judgements_exist`` rejects changing the
    *values* once anything has been judged against them, while still allowing
    the labels to change. Enforced here too: without it this API could put a
    book into a state Quepid's own UI considers invalid, and the judgements
    already made would silently be on a different scale from the book.
    """
    if scale is None or _dump_scale(scale) == book.scale:
        return None

    judged = qmodels.Judgements.objects \
        .using('quepid') \
        .filter(query_doc_pair__book_id=book.id) \
        .exists()
    if not judged:
        return None

    return (f'Cannot change the scale of a book that has judgements: they were '
            f'made against {book.scale!r}. Labels can still be changed.')


def _reachable_book(user, book_id):
    """A book the caller may write to: their own, or one shared with their team.

    Mirrors Quepid's own ``Book.for_user`` -- ownership or a teams_books row
    reached through a team you are in. Reads elsewhere in this router are still
    unscoped; writes are not, because adding query/doc pairs to a stranger's
    book changes what their judges are asked to rate.
    """
    book = qmodels.Books.objects.using('quepid').filter(pk=book_id).first()
    if not book:
        return None
    if book.owner_id == user.id:
        return book

    shared_with_me = qmodels.TeamsBooks.objects \
        .using('quepid') \
        .filter(book_id=book.id) \
        .filter(team_id__in=_member_teams(user).values('id')) \
        .exists()
    return book if shared_with_me else None


@router.get("/", response=List[Book])
@paginate
def view_books(request):
    return qmodels.Books.objects.using('quepid').all()
    
    
@router.get("/{book_id}", response={200: Book, 404: None})
def view_book(request, book_id: int):
    if r := _by_pk(qmodels.Books, book_id):
        return 200, r
    return 404, None
    
    
@router.post("/", response={200: Book, 400: str})
def create_book(request, data: CreateBook):
    """Create a book, shared with the caller's team on the same terms as a case.

    A book reaches a team through ``teams_books``, exactly as a case does
    through ``teams_cases``, and Quepid's Books list shows the team it belongs
    to -- so a book created without one is as stranded as a case was.
    """
    try:
        now = timezone.now()

        # Resolved before anything is written, so an ambiguous or unusable team
        # is rejected without leaving a half-built book behind.
        team, team_error = _team_for_new_row(request.auth, data.team_id)
        if team_error:
            return 400, team_error

        with transaction.atomic(using='quepid'):
            book = qmodels.Books.objects.using('quepid').create(
                name=data.name,
                support_implicit_judgements=1 if data.support_implicit_judgements else 0,
                show_rank=1 if data.show_rank else 0,
                # books.archived is NOT NULL with a Rails-side default (v8.3.0+).
                # inspectdb gives it no Django default, so Django would send NULL.
                archived=0,
                created_at=now,
                updated_at=now,
                owner_id=request.auth.id,
                scale=_dump_scale(data.scale),
                # TEXT holding JSON (Rails serializes it), like document_fields
                # on a query/doc pair and unlike that row's options column.
                scale_with_labels=(json.dumps(data.scale_with_labels)
                                   if data.scale_with_labels else None),
            )
            if team:
                qmodels.TeamsBooks.objects.using('quepid').create(
                    book_id=book.id,
                    team_id=team.id
                )
        return book
    except Exception as e:
        return 400, str(e)
        
        
@router.patch("/{book_id}", response={200: Book, 404: None, 400: str})
def update_book(request, book_id: int, data: UpdateBook):
    try:
        book = qmodels.Books.objects.using('quepid').filter(id=book_id).first()
        if not book:
            return 404, None
        
        update_fields = {}
        if data.name is not None:
            update_fields['name'] = data.name
        if data.support_implicit_judgements is not None:
            update_fields['support_implicit_judgements'] = 1 if data.support_implicit_judgements else 0
        if data.show_rank is not None:
            update_fields['show_rank'] = 1 if data.show_rank else 0
        if locked := _scale_is_locked(book, data.scale):
            return 400, locked
        if data.scale is not None:
            update_fields['scale'] = _dump_scale(data.scale)
        if data.scale_with_labels is not None:
            update_fields['scale_with_labels'] = json.dumps(data.scale_with_labels)
        
        if update_fields:
            update_fields['updated_at'] = timezone.now()
            qmodels.Books.objects.using('quepid').filter(id=book_id).update(**update_fields)
            return 200, qmodels.Books.objects.using('quepid').get(id=book_id)
        
        return 200, book
    except Exception as e:
        return 400, str(e)
        
        
def _clear_query_doc_pairs(book):
    """Empty a book of its pairs, judgements first. Returns how many pairs went.

    ``judgements.query_doc_pair_id`` is a real foreign key and ``inspectdb``
    reflects every relation as ``DO_NOTHING``, so Django emits no cascade and
    MySQL answers 1451. Rails hits the same wall -- ``Book#really_destroy``
    exists for exactly this reason and deletes the judgements by hand first.
    This is that method, in Django.
    """
    with transaction.atomic(using='quepid'):
        qmodels.Judgements.objects \
            .using('quepid') \
            .filter(query_doc_pair__book_id=book.id) \
            .delete()
        removed, _ = qmodels.QueryDocPairs.objects \
            .using('quepid') \
            .filter(book_id=book.id) \
            .delete()

    return removed


@router.delete("/{book_id}/query_doc_pairs/",
               response={200: dict, 404: None, 400: str})
def delete_query_doc_pairs(request, book_id: int):
    """Empty a book of its query/doc pairs, and of the judgements on them.

    This is how to re-import a book whose documents have changed:
    ``create_query_doc_pairs`` skips a pair the book already holds rather than
    updating it, so changed document_fields need the old pair gone first.

    Destructive on purpose, and not reversible -- every judgement anyone has
    made in this book goes with the pairs, because a judgement hangs off a pair.
    """
    try:
        book = _reachable_book(request.auth, book_id)
        if not book:
            return 404, None
        return 200, {"deleted": _clear_query_doc_pairs(book)}
    except Exception as e:
        return 400, str(e)


@router.delete("/{book_id}", response={200: dict, 404: None, 400: str})
def delete_book(request, book_id: int):
    """Delete a book outright, along with everything that hangs off it.

    Unlike ``delete_case``, which only archives, this really removes the row --
    and so has to clear what references it first. ``book.delete()`` on its own
    works only for a book nothing has touched: one query/doc pair, or a book
    somebody has merely *viewed* (which writes book_metadata), is enough for
    MySQL to refuse with 1451. Rails gets that cascade from ``dependent:``
    declarations, which are model-level and invisible to the reflection.
    """
    try:
        book = qmodels.Books.objects.using('quepid').filter(id=book_id).first()
        if not book:
            return 404, None

        with transaction.atomic(using='quepid'):
            _clear_query_doc_pairs(book)
            qmodels.BookMetadata.objects.using('quepid').filter(book_id=book.id).delete()
            qmodels.BooksAiJudges.objects.using('quepid').filter(book_id=book.id).delete()

            # cases.book_id carries no foreign key, so nothing would stop the
            # book going and leaving a case pointing at an id that no longer
            # resolves. Rails says `has_many :cases, dependent: :nullify`; this
            # is that. The case itself stays -- it is a search configuration and
            # outlives the book it was rating against.
            qmodels.Cases.objects \
                .using('quepid') \
                .filter(book_id=book.id) \
                .update(book_id=None, updated_at=timezone.now())

            # Attachments are polymorphic and so have no foreign key either --
            # Book#delete_attachments purges these on destroy. The blobs behind
            # them are left alone: they are shared, and Rails purges them on its
            # own schedule.
            qmodels.ActiveStorageAttachments.objects \
                .using('quepid') \
                .filter(record_type='Book', record_id=book.id) \
                .delete()

            # teams_books carries no primary key, so the ORM cannot delete from
            # it at all -- see teams.py:_shared_book_ids. It carries no foreign
            # key either, so the row would otherwise be left dangling.
            with connections['quepid'].cursor() as cursor:
                cursor.execute(
                    "DELETE FROM teams_books WHERE book_id = %s", [book.id]
                )

            book.delete()
        return 200, {"message": "Book deleted successfully"}
    except Exception as e:
        return 400, str(e)


@router.get("/{book_id}/query_doc_pairs/", response=List[QueryDocPair])
@paginate
def view_query_doc_pairs(request, book_id: int):
    """The book's query/doc pairs -- its queries, one row per document"""
    return qmodels.QueryDocPairs.objects \
        .using('quepid') \
        .filter(book_id=book_id) \
        .order_by('id')


@router.post("/{book_id}/query_doc_pairs/",
             response={200: QueryDocPairsWritten, 404: None, 400: str})
def create_query_doc_pairs(request, book_id: int, data: List[CreateQueryDocPair]):
    """Add query/doc pairs to a book in bulk, which is how a book gets queries.

    Quepid normally fills a book from a case run, via PopulateBookJob. This is
    the other direction: loading pairs you already have -- a labelled dataset,
    say -- so the book holds ground truth rather than one engine's results.

    Identity is ``(query_text, doc_id)``, matching the ``find_or_create_by`` that
    PopulateBookJob uses, so a pair the book already holds is skipped rather
    than duplicated and re-posting a batch is a no-op. Skipped pairs are not
    updated: to change a pair's document_fields, delete it and post it again.

    Takes a JSON array, because a dataset is tens of thousands of pairs and one
    request each would be unusable. Batch on the client to keep bodies sane.
    """
    try:
        book = _reachable_book(request.auth, book_id)
        if not book:
            return 404, None

        now = timezone.now()

        existing = set(
            qmodels.QueryDocPairs.objects
            .using('quepid')
            .filter(book_id=book.id)
            .values_list('query_text', 'doc_id')
        )

        fresh, seen = [], set()
        for pair in data:
            # `seen` catches duplicates within the batch itself, which `existing`
            # cannot: nothing is written until the bulk_create below.
            key = (pair.query_text, pair.doc_id)
            if key in existing or key in seen:
                continue
            seen.add(key)
            fresh.append(qmodels.QueryDocPairs(
                book_id=book.id,
                query_text=pair.query_text,
                doc_id=pair.doc_id,
                position=pair.position,
                # TEXT, not json, unlike options just below -- Rails dumps it on
                # the way in, so passing the dict itself would store its repr.
                document_fields=(json.dumps(pair.document_fields)
                                 if pair.document_fields else None),
                information_need=pair.information_need,
                notes=pair.notes,
                options=pair.query_options or None,
                created_at=now,
                updated_at=now,
            ))

        with transaction.atomic(using='quepid'):
            qmodels.QueryDocPairs.objects \
                .using('quepid') \
                .bulk_create(fresh, batch_size=500)

        return 200, {"created": len(fresh), "skipped": len(data) - len(fresh)}
    except Exception as e:
        return 400, str(e)


def _judge_for_write(user, user_id):
    """Whose judgements these are. Returns ``(user_id, error)``.

    Omitted, they are the caller's own. ``user_id = 0`` writes them
    anonymously, which Quepid supports (``judgements.user_id`` is nullable, and
    ``Book#assign_anonymous`` exists to attribute them later) and which is the
    honest option for labels that came out of a dataset rather than a person.

    Naming anybody else is refused. Judgements are attributable opinions --
    that is the whole reason the table is keyed on the rater -- and writing
    them under someone else's name should require their token, not merely
    knowing their id. To load a dataset under an identity of its own, make an
    account for it and use its key.
    """
    if user_id is None:
        return user.id, None
    if user_id == 0:
        return None, None
    if user_id == user.id:
        return user.id, None
    return None, ('Judgements can only be written as yourself (omit user_id) or '
                  'anonymously (user_id=0).')


@router.get("/{book_id}/judgements/", response=List[Judgement])
@paginate
def view_judgements(request, book_id: int, user_id: int = None):
    """The judgements made in a book, optionally just one rater's.

    ``user_id=0`` selects the anonymous ones.
    """
    judgements = qmodels.Judgements.objects \
        .using('quepid') \
        .filter(query_doc_pair__book_id=book_id)

    if user_id is not None:
        judgements = judgements.filter(user_id=user_id or None)

    return judgements.order_by('id')


@router.post("/{book_id}/judgements/",
             response={200: JudgementsWritten, 404: None, 400: str})
def create_judgements(request, book_id: int, data: List[CreateJudgement],
                      user_id: int = None):
    """Load judgements into a book in bulk -- ground truth you already have.

    Nothing else writes this table: Quepid fills it from its judging screen,
    its bulk-judge page, or ``RunJudgeJudyJob``, all of which rate one pair at
    a time. This is the bulk door, for a dataset that arrives already labelled.

    Loading labels does **not** shut an AI judge out of the same pairs.
    ``SelectionStrategy`` offers a rater any pair *they* have not rated that
    has fewer than three judgements in total, so a human label and each judge's
    verdict coexist -- which is what makes them comparable. Mind that ceiling
    of three, though: one loaded label plus two AI judges fills a pair, and a
    fourth rater is offered nothing.

    Re-running is safe. Identity is ``(rater, pair)``, matching the table's
    unique index, so a second post of the same rows updates the ratings rather
    than duplicating them. The exception is anonymous judgements: MySQL treats
    NULLs as distinct, and Rails skips its own uniqueness check when the rater
    is nil, so this endpoint matches on the first anonymous judgement it finds
    for a pair.
    """
    try:
        book = _reachable_book(request.auth, book_id)
        if not book:
            return 404, None

        judge_id, error = _judge_for_write(request.auth, user_id)
        if error:
            return 400, error

        # Checked against the book's own scale, which Rails does not do -- and
        # the reason it matters is visual rather than relational: the judging
        # screen builds its buttons by mapping over book.scale, so a rating
        # outside it is a row nobody can see or change by hand afterwards.
        allowed = _as_scale(book.scale)
        for row in data:
            if row.rating is None:
                if not (row.unrateable or row.judge_later):
                    return 400, (f'{row.query_text!r}/{row.doc_id}: a judgement '
                                 f'needs a rating unless it is unrateable or '
                                 f'judge_later.')
            elif allowed and row.rating not in allowed:
                return 400, (f'{row.query_text!r}/{row.doc_id}: rating '
                             f'{row.rating} is not on this book\'s scale '
                             f'{allowed}.')

        # Resolved by doc_id alone and matched exactly in Python: filtering on
        # both columns would ask MySQL for every combination of the batch's
        # query_texts and doc_ids, not the pairs actually named.
        wanted = {(row.query_text, row.doc_id) for row in data}
        pairs = {}
        for pair in qmodels.QueryDocPairs.objects \
                .using('quepid') \
                .filter(book_id=book.id) \
                .filter(doc_id__in={row.doc_id for row in data}) \
                .values('id', 'query_text', 'doc_id'):
            key = (pair['query_text'], pair['doc_id'])
            if key in wanted:
                pairs[key] = pair['id']

        existing = {}
        for judgement in qmodels.Judgements.objects \
                .using('quepid') \
                .filter(query_doc_pair_id__in=pairs.values()) \
                .filter(user_id=judge_id):
            existing.setdefault(judgement.query_doc_pair_id, judgement)

        now = timezone.now()
        fresh, changed, unchanged, unknown, seen = [], [], 0, 0, set()

        for row in data:
            key = (row.query_text, row.doc_id)
            if key not in pairs:
                unknown += 1
                continue
            # A batch naming the same pair twice would otherwise write two rows
            # for one rater, which the unique index forbids.
            if key in seen:
                continue
            seen.add(key)

            verdict = (row.rating, row.explanation,
                       int(row.unrateable), int(row.judge_later))

            if judgement := existing.get(pairs[key]):
                if (judgement.rating, judgement.explanation,
                        judgement.unrateable, judgement.judge_later) == verdict:
                    unchanged += 1
                    continue
                (judgement.rating, judgement.explanation,
                 judgement.unrateable, judgement.judge_later) = verdict
                judgement.updated_at = now
                changed.append(judgement)
            else:
                fresh.append(qmodels.Judgements(
                    query_doc_pair_id=pairs[key],
                    user_id=judge_id,
                    rating=row.rating,
                    explanation=row.explanation,
                    # Written as 0 rather than left NULL: Rails defaults both to
                    # false, and its ``rateable`` scope is
                    # ``where(unrateable: false).where(judge_later: false)`` --
                    # which NULL does not satisfy, so a NULL here would quietly
                    # drop the judgement out of every count that scope feeds.
                    unrateable=int(row.unrateable),
                    judge_later=int(row.judge_later),
                    created_at=now,
                    updated_at=now,
                ))

        with transaction.atomic(using='quepid'):
            qmodels.Judgements.objects \
                .using('quepid') \
                .bulk_create(fresh, batch_size=500)
            if changed:
                qmodels.Judgements.objects \
                    .using('quepid') \
                    .bulk_update(changed,
                                 ['rating', 'explanation', 'unrateable',
                                  'judge_later', 'updated_at'],
                                 batch_size=500)

        return 200, {"created": len(fresh), "updated": len(changed),
                     "unchanged": unchanged, "unknown": unknown}
    except Exception as e:
        return 400, str(e)


@router.delete("/{book_id}/judgements/", response={200: dict, 404: None, 400: str})
def delete_judgements(request, book_id: int, user_id: int = None):
    """Clear judgements from a book, leaving its query/doc pairs in place.

    Scoped to one rater with ``user_id`` (``0`` for the anonymous ones), which
    is the useful form: it re-opens the book to that rater without discarding
    anybody else's work. Passing no ``user_id`` clears **every** judgement in
    the book, everyone's, which is not reversible.

    Unlike ``delete_query_doc_pairs`` this keeps the pairs, so the book still
    knows what there is to judge.
    """
    try:
        book = _reachable_book(request.auth, book_id)
        if not book:
            return 404, None

        judgements = qmodels.Judgements.objects \
            .using('quepid') \
            .filter(query_doc_pair__book_id=book.id)

        if user_id is not None:
            judgements = judgements.filter(user_id=user_id or None)

        deleted, _ = judgements.delete()
        return 200, {"deleted": deleted}
    except Exception as e:
        return 400, str(e)
