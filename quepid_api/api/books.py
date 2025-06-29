import logging

from ninja import Router
from django.utils import timezone
import quepid.models as qmodels
from quepid.schemas import Book
from typing import List
from ninja.pagination import paginate
from ninja import Schema

from .utils import _by_pk


logger = logging.getLogger('')

router = Router(tags=["Books management"])


class CreateBook(Schema):
    name: str
    scorer_id: int
    selection_strategy_id: int
    support_implicit_judgements: bool = False
    show_rank: bool = False
    description: str = ""


class UpdateBook(Schema):
    name: str = None
    scorer_id: int = None
    selection_strategy_id: int = None
    support_implicit_judgements: bool = None
    show_rank: bool = None
    description: str = None


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
    try:
        now = timezone.now()
        return qmodels.Books.objects.using('quepid').create(
            name=data.name,
            scorer_id=data.scorer_id,
            selection_strategy_id=data.selection_strategy_id,
            support_implicit_judgements=1 if data.support_implicit_judgements else 0,
            show_rank=1 if data.show_rank else 0,
            created_at=now,
            updated_at=now,
            owner_id=request.auth
        )
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
        if data.scorer_id is not None:
            update_fields['scorer_id'] = data.scorer_id
        if data.selection_strategy_id is not None:
            update_fields['selection_strategy_id'] = data.selection_strategy_id
        if data.support_implicit_judgements is not None:
            update_fields['support_implicit_judgements'] = 1 if data.support_implicit_judgements else 0
        if data.show_rank is not None:
            update_fields['show_rank'] = 1 if data.show_rank else 0
        
        if update_fields:
            update_fields['updated_at'] = timezone.now()
            qmodels.Books.objects.using('quepid').filter(id=book_id).update(**update_fields)
            return 200, qmodels.Books.objects.using('quepid').get(id=book_id)
        
        return 200, book
    except Exception as e:
        return 400, str(e)


@router.delete("/{book_id}", response={200: dict, 404: None, 400: str})
def delete_book(request, book_id: int):
    try:
        book = qmodels.Books.objects.using('quepid').filter(id=book_id).first()
        if not book:
            return 404, None
        
        book.delete()
        return 200, {"message": "Book deleted successfully"}
    except Exception as e:
        return 400, str(e) 