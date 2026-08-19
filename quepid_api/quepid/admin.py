"""Read-only Django admin views over the Quepid database.

Registration is automatic and needs no wiring beyond the host project's own
admin setup: when `django.contrib.admin` is installed, its `AppConfig.ready()`
calls `autodiscover_modules("admin")`, which imports `admin.py` from every
installed app -- including this one, once a host project lists `quepid` in
`INSTALLED_APPS`. That import is what runs the `@admin.register(...)` below, so
"Quepid > Judgements" appears in `/admin/` for any staff user with the
`view_judgements` permission, with no further code on the host side. This
project's own `settings.py` leaves `django.contrib.admin` commented out and
never enables it -- this module exists purely for a host project to pick up.

Every query here is routed explicitly with `.using('quepid')` (see CLAUDE.md,
"The Rails-owned schema"): there is no database router in this project, so a
Django admin default -- `list_filter` on a ForeignKey, `field.get_choices()`, a
related manager reached off the *default* manager -- silently queries the
`default` alias, which is a `startproject` sqlite phantom with no `judgements` or
`users` table. Every FK traversal below goes through `select_related()` on the
same `.using('quepid')` queryset instead of a fresh manager call, and every
custom filter builds its choices from that same queryset.
"""
import json

from django.contrib import admin
from django.utils.html import format_html_join

from . import models as qmodels


def _document_fields(query_doc_pair):
    if query_doc_pair is None or not query_doc_pair.document_fields:
        return {}
    try:
        data = json.loads(query_doc_pair.document_fields)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class JudgeListFilter(admin.SimpleListFilter):
    title = "judged by"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        user_ids = (
            model_admin.get_queryset(request)
            .exclude(user_id__isnull=True)
            .order_by()
            .values_list("user_id", flat=True)
            .distinct()
        )
        users = (
            qmodels.Users.objects
            .using("quepid")
            .filter(id__in=user_ids)
            .order_by("name")
        )
        return [(user.id, user.name or user.email) for user in users]

    def queryset(self, request, queryset):
        if self.value() is None:
            return queryset
        return queryset.filter(user_id=self.value())


@admin.register(qmodels.Judgements)
class JudgementsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "query",
        "document",
        "rating",
        "judged_by",
        "is_unrateable",
        "is_judge_later",
        "created_at",
    )
    list_filter = ("rating", JudgeListFilter, "created_at")
    search_fields = (
        "query_doc_pair__query_text",
        "query_doc_pair__doc_id",
        "explanation",
        "user__name",
        "user__email",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    empty_value_display = "—"

    fields = (
        "query",
        "information_need",
        "document",
        "document_fields_display",
        "rating",
        "is_unrateable",
        "is_judge_later",
        "explanation",
        "judged_by",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def get_queryset(self, request):
        return (
            qmodels.Judgements.objects
            .using("quepid")
            .select_related("user", "query_doc_pair", "query_doc_pair__book")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Query", ordering="query_doc_pair__query_text")
    def query(self, obj):
        pair = obj.query_doc_pair
        return pair.query_text if pair else None

    @admin.display(description="Information need")
    def information_need(self, obj):
        pair = obj.query_doc_pair
        return pair.information_need if pair else None

    @admin.display(description="Document", ordering="query_doc_pair__doc_id")
    def document(self, obj):
        pair = obj.query_doc_pair
        if pair is None:
            return None
        fields = _document_fields(pair)
        for key in ("title", "name"):
            if fields.get(key):
                return fields[key]
        return pair.doc_id

    @admin.display(description="Document fields")
    def document_fields_display(self, obj):
        fields = _document_fields(obj.query_doc_pair)
        if not fields:
            return None
        return format_html_join(
            "",
            "<div><strong>{}</strong>: {}</div>",
            ((key, value) for key, value in fields.items()),
        )

    @admin.display(description="Judged by", ordering="user__name")
    def judged_by(self, obj):
        if obj.user_id is None:
            return None
        return obj.user.name or obj.user.email or f"User #{obj.user_id}"

    @admin.display(description="I Can't Tell", boolean=True)
    def is_unrateable(self, obj):
        return bool(obj.unrateable)

    @admin.display(description="Judge Later", boolean=True)
    def is_judge_later(self, obj):
        return bool(obj.judge_later)
