from ninja import ModelSchema

from .models import *

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
