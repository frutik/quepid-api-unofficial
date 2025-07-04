from ninja import ModelSchema

from .models import *


class SearchEndpoint(ModelSchema):
    class Meta:
        model = SearchEndpoints
        fields = "__all__"


class Scorer(ModelSchema):
    class Meta:
        model = Scorers
        fields = "__all__"


class Case(ModelSchema):
    class Meta:
        model = Cases
        fields = "__all__"


class Query(ModelSchema):
    query_options: dict = {}
    class Meta:
        model = Queries
        fields = "__all__"
        exclude = ['options', ]


class Book(ModelSchema):
    class Meta:
        model = Books
        fields = "__all__"
