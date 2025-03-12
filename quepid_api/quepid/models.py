# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class ActiveStorageAttachments(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    record_type = models.CharField(max_length=255)
    record_id = models.BigIntegerField()
    blob = models.ForeignKey('ActiveStorageBlobs', models.DO_NOTHING)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'active_storage_attachments'
        unique_together = (('record_type', 'record_id', 'name', 'blob'),)


class ActiveStorageBlobs(models.Model):
    id = models.BigAutoField(primary_key=True)
    key = models.CharField(unique=True, max_length=255)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True, null=True)
    metadata = models.TextField(blank=True, null=True)
    service_name = models.CharField(max_length=255)
    byte_size = models.BigIntegerField()
    checksum = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'active_storage_blobs'


class ActiveStorageDbFiles(models.Model):
    id = models.BigAutoField(primary_key=True)
    ref = models.CharField(unique=True, max_length=255)
    data = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'active_storage_db_files'


class ActiveStorageVariantRecords(models.Model):
    id = models.BigAutoField(primary_key=True)
    blob = models.ForeignKey(ActiveStorageBlobs, models.DO_NOTHING)
    variation_digest = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'active_storage_variant_records'
        unique_together = (('blob', 'variation_digest'),)


class AhoyEvents(models.Model):
    id = models.BigAutoField(primary_key=True)
    visit_id = models.BigIntegerField(blank=True, null=True)
    user_id = models.BigIntegerField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    properties = models.JSONField(blank=True, null=True)
    time = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ahoy_events'


class AhoyVisits(models.Model):
    id = models.BigAutoField(primary_key=True)
    visit_token = models.CharField(unique=True, max_length=255, blank=True, null=True)
    visitor_token = models.CharField(max_length=255, blank=True, null=True)
    user_id = models.BigIntegerField(blank=True, null=True)
    ip = models.CharField(max_length=255, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    referrer = models.TextField(blank=True, null=True)
    referring_domain = models.CharField(max_length=255, blank=True, null=True)
    landing_page = models.TextField(blank=True, null=True)
    browser = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    device_type = models.CharField(max_length=255, blank=True, null=True)
    country = models.CharField(max_length=255, blank=True, null=True)
    region = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    utm_source = models.CharField(max_length=255, blank=True, null=True)
    utm_medium = models.CharField(max_length=255, blank=True, null=True)
    utm_term = models.CharField(max_length=255, blank=True, null=True)
    utm_content = models.CharField(max_length=255, blank=True, null=True)
    utm_campaign = models.CharField(max_length=255, blank=True, null=True)
    app_version = models.CharField(max_length=255, blank=True, null=True)
    os_version = models.CharField(max_length=255, blank=True, null=True)
    platform = models.CharField(max_length=255, blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ahoy_visits'


class Annotations(models.Model):
    message = models.TextField(blank=True, null=True)
    source = models.CharField(max_length=255, blank=True, null=True)
    user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'annotations'


class AnnouncementViewed(models.Model):
    id = models.BigAutoField(primary_key=True)
    announcement_id = models.IntegerField(blank=True, null=True)
    user_id = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'announcement_viewed'


class Announcements(models.Model):
    id = models.BigAutoField(primary_key=True)
    text = models.TextField(db_collation='utf8mb4_unicode_ci', blank=True, null=True)
    author_id = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    live = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'announcements'


class ApiKeys(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.IntegerField(blank=True, null=True)
    token_digest = models.CharField(max_length=255)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_keys'


class ArInternalMetadata(models.Model):
    key = models.CharField(primary_key=True, max_length=255)
    value = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ar_internal_metadata'


class BlazerAudits(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(blank=True, null=True)
    query_id = models.BigIntegerField(blank=True, null=True)
    statement = models.TextField(blank=True, null=True)
    data_source = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'blazer_audits'


class BlazerChecks(models.Model):
    id = models.BigAutoField(primary_key=True)
    creator_id = models.BigIntegerField(blank=True, null=True)
    query_id = models.BigIntegerField(blank=True, null=True)
    state = models.CharField(max_length=255, blank=True, null=True)
    schedule = models.CharField(max_length=255, blank=True, null=True)
    emails = models.TextField(blank=True, null=True)
    slack_channels = models.TextField(blank=True, null=True)
    check_type = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'blazer_checks'


class BlazerDashboardQueries(models.Model):
    id = models.BigAutoField(primary_key=True)
    dashboard_id = models.BigIntegerField(blank=True, null=True)
    query_id = models.BigIntegerField(blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'blazer_dashboard_queries'


class BlazerDashboards(models.Model):
    id = models.BigAutoField(primary_key=True)
    creator_id = models.BigIntegerField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'blazer_dashboards'


class BlazerQueries(models.Model):
    id = models.BigAutoField(primary_key=True)
    creator_id = models.BigIntegerField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    statement = models.TextField(blank=True, null=True)
    data_source = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'blazer_queries'


class BookMetadata(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.IntegerField(blank=True, null=True)
    book = models.ForeignKey('Books', models.DO_NOTHING)
    last_viewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'book_metadata'


class Books(models.Model):
    id = models.BigAutoField(primary_key=True)
    scorer_id = models.IntegerField(blank=True, null=True)
    selection_strategy = models.ForeignKey('SelectionStrategies', models.DO_NOTHING)
    name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    support_implicit_judgements = models.IntegerField(blank=True, null=True)
    show_rank = models.IntegerField(blank=True, null=True)
    owner_id = models.IntegerField(blank=True, null=True)
    export_job = models.CharField(max_length=255, blank=True, null=True)
    import_job = models.CharField(max_length=255, blank=True, null=True)
    populate_job = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'books'


class BooksAiJudges(models.Model):
    id = models.BigAutoField(primary_key=True)
    book = models.ForeignKey(Books, models.DO_NOTHING)
    user_id = models.BigIntegerField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'books_ai_judges'
        unique_together = (('book', 'user_id'),)


class CaseMetadata(models.Model):
    user = models.ForeignKey('Users', models.DO_NOTHING)
    case = models.ForeignKey('Cases', models.DO_NOTHING)
    last_viewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'case_metadata'


class CaseScores(models.Model):
    case = models.ForeignKey('Cases', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    try_id = models.IntegerField(blank=True, null=True)
    score = models.FloatField(blank=True, null=True)
    all_rated = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    queries = models.TextField(blank=True, null=True)
    annotation = models.OneToOneField(Annotations, models.DO_NOTHING, blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    scorer_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'case_scores'


class Cases(models.Model):
    case_name = models.CharField(max_length=191, blank=True, null=True)
    last_try_number = models.IntegerField(blank=True, null=True)
    owner = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    archived = models.IntegerField(blank=True, null=True)
    scorer_id = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    book_id = models.IntegerField(blank=True, null=True)
    public = models.IntegerField(blank=True, null=True)
    options = models.JSONField(blank=True, null=True)
    nightly = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cases'


class CuratorVariables(models.Model):
    name = models.CharField(max_length=500, blank=True, null=True)
    value = models.FloatField(blank=True, null=True)
    try_id = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'curator_variables'


class Judgements(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.IntegerField(blank=True, null=True)
    rating = models.FloatField(blank=True, null=True)
    query_doc_pair = models.ForeignKey('QueryDocPairs', models.DO_NOTHING)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    unrateable = models.IntegerField(blank=True, null=True)
    judge_later = models.IntegerField(blank=True, null=True)
    explanation = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'judgements'
        unique_together = (('user_id', 'query_doc_pair'),)


class Queries(models.Model):
    arranged_next = models.BigIntegerField(blank=True, null=True)
    arranged_at = models.BigIntegerField(blank=True, null=True)
    query_text = models.CharField(max_length=2048, db_collation='utf8mb4_bin', blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    case = models.ForeignKey(Cases, models.DO_NOTHING, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    options = models.TextField(db_collation='utf8mb3_bin', blank=True, null=True)
    information_need = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'queries'


class QueryDocPairs(models.Model):
    id = models.BigAutoField(primary_key=True)
    query_text = models.CharField(max_length=2048, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    document_fields = models.TextField(db_collation='utf8mb4_0900_ai_ci', blank=True, null=True)
    book = models.ForeignKey(Books, models.DO_NOTHING)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    doc_id = models.CharField(max_length=500, blank=True, null=True)
    information_need = models.CharField(max_length=255, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    options = models.TextField(db_collation='utf8mb3_bin', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'query_doc_pairs'


class Ratings(models.Model):
    doc_id = models.CharField(max_length=500, blank=True, null=True)
    rating = models.FloatField(blank=True, null=True)
    query = models.ForeignKey(Queries, models.DO_NOTHING, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    user_id = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ratings'


class SchemaMigrations(models.Model):
    version = models.CharField(primary_key=True, max_length=255)

    class Meta:
        managed = False
        db_table = 'schema_migrations'


class Scorers(models.Model):
    code = models.TextField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    owner_id = models.IntegerField(blank=True, null=True)
    scale = models.CharField(max_length=255, blank=True, null=True)
    show_scale_labels = models.IntegerField(blank=True, null=True)
    scale_with_labels = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    communal = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'scorers'


class SearchEndpoints(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    owner_id = models.IntegerField(blank=True, null=True)
    search_engine = models.CharField(max_length=50, blank=True, null=True)
    endpoint_url = models.CharField(max_length=500, blank=True, null=True)
    api_method = models.CharField(max_length=255, blank=True, null=True)
    custom_headers = models.CharField(max_length=6000, blank=True, null=True)
    archived = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    basic_auth_credential = models.CharField(max_length=255, blank=True, null=True)
    mapper_code = models.TextField(blank=True, null=True)
    proxy_requests = models.IntegerField(blank=True, null=True)
    options = models.JSONField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'search_endpoints'


class SelectionStrategies(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    description = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'selection_strategies'


class SnapshotDocs(models.Model):
    doc_id = models.CharField(max_length=500, blank=True, null=True)
    position = models.IntegerField(blank=True, null=True)
    snapshot_query = models.ForeignKey('SnapshotQueries', models.DO_NOTHING, blank=True, null=True)
    explain = models.TextField(db_collation='utf8mb4_0900_ai_ci', blank=True, null=True)
    rated_only = models.IntegerField(blank=True, null=True)
    fields = models.TextField(db_collation='utf8mb4_0900_ai_ci', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'snapshot_docs'


class SnapshotQueries(models.Model):
    query = models.ForeignKey(Queries, models.DO_NOTHING, blank=True, null=True)
    snapshot = models.ForeignKey('Snapshots', models.DO_NOTHING, blank=True, null=True)
    score = models.FloatField(blank=True, null=True)
    all_rated = models.IntegerField(blank=True, null=True)
    number_of_results = models.IntegerField(blank=True, null=True)
    response_status = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'snapshot_queries'


class Snapshots(models.Model):
    name = models.CharField(max_length=250, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    case = models.ForeignKey(Cases, models.DO_NOTHING, blank=True, null=True)
    updated_at = models.DateTimeField()
    try_id = models.BigIntegerField(blank=True, null=True)
    scorer_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'snapshots'


class SolidCableMessages(models.Model):
    id = models.BigAutoField(primary_key=True)
    channel = models.CharField(max_length=1024)
    payload = models.TextField()
    created_at = models.DateTimeField()
    channel_hash = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = 'solid_cable_messages'


class SolidQueueBlockedExecutions(models.Model):
    id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField('SolidQueueJobs', models.DO_NOTHING)
    queue_name = models.CharField(max_length=255)
    priority = models.IntegerField()
    concurrency_key = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_blocked_executions'


class SolidQueueClaimedExecutions(models.Model):
    id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField('SolidQueueJobs', models.DO_NOTHING)
    process_id = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_claimed_executions'


class SolidQueueFailedExecutions(models.Model):
    id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField('SolidQueueJobs', models.DO_NOTHING)
    error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_failed_executions'


class SolidQueueJobs(models.Model):
    id = models.BigAutoField(primary_key=True)
    queue_name = models.CharField(max_length=255)
    class_name = models.CharField(max_length=255)
    arguments = models.TextField(blank=True, null=True)
    priority = models.IntegerField()
    active_job_id = models.CharField(max_length=255, blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    concurrency_key = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_jobs'


class SolidQueuePauses(models.Model):
    id = models.BigAutoField(primary_key=True)
    queue_name = models.CharField(unique=True, max_length=255)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_pauses'


class SolidQueueProcesses(models.Model):
    id = models.BigAutoField(primary_key=True)
    kind = models.CharField(max_length=255)
    last_heartbeat_at = models.DateTimeField()
    supervisor_id = models.BigIntegerField(blank=True, null=True)
    pid = models.IntegerField()
    hostname = models.CharField(max_length=255, blank=True, null=True)
    metadata = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'solid_queue_processes'
        unique_together = (('name', 'supervisor_id'),)


class SolidQueueReadyExecutions(models.Model):
    id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField(SolidQueueJobs, models.DO_NOTHING)
    queue_name = models.CharField(max_length=255)
    priority = models.IntegerField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_ready_executions'


class SolidQueueRecurringExecutions(models.Model):
    id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField(SolidQueueJobs, models.DO_NOTHING)
    task_key = models.CharField(max_length=255)
    run_at = models.DateTimeField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_recurring_executions'
        unique_together = (('task_key', 'run_at'),)


class SolidQueueRecurringTasks(models.Model):
    id = models.BigAutoField(primary_key=True)
    key = models.CharField(unique=True, max_length=255)
    schedule = models.CharField(max_length=255)
    command = models.CharField(max_length=2048, blank=True, null=True)
    class_name = models.CharField(max_length=255, blank=True, null=True)
    arguments = models.TextField(blank=True, null=True)
    queue_name = models.CharField(max_length=255, blank=True, null=True)
    priority = models.IntegerField(blank=True, null=True)
    static = models.IntegerField()
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_recurring_tasks'


class SolidQueueScheduledExecutions(models.Model):
    id = models.BigAutoField(primary_key=True)
    job = models.OneToOneField(SolidQueueJobs, models.DO_NOTHING)
    queue_name = models.CharField(max_length=255)
    priority = models.IntegerField()
    scheduled_at = models.DateTimeField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_scheduled_executions'


class SolidQueueSemaphores(models.Model):
    id = models.BigAutoField(primary_key=True)
    key = models.CharField(unique=True, max_length=255)
    value = models.IntegerField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'solid_queue_semaphores'


class Teams(models.Model):
    name = models.CharField(max_length=255, db_collation='utf8mb3_bin', blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'teams'


class TeamsBooks(models.Model):
    book_id = models.BigIntegerField()
    team_id = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = 'teams_books'


class TeamsCases(models.Model):
    case = models.OneToOneField(Cases, models.DO_NOTHING, primary_key=True)  # The composite primary key (case_id, team_id) found, that is not supported. The first column is selected.
    team = models.ForeignKey(Teams, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'teams_cases'
        unique_together = (('case', 'team'),)


class TeamsMembers(models.Model):
    member = models.OneToOneField('Users', models.DO_NOTHING, primary_key=True)  # The composite primary key (member_id, team_id) found, that is not supported. The first column is selected.
    team = models.ForeignKey(Teams, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'teams_members'
        unique_together = (('member', 'team'),)


class TeamsScorers(models.Model):
    scorer = models.OneToOneField(Scorers, models.DO_NOTHING, primary_key=True)  # The composite primary key (scorer_id, team_id) found, that is not supported. The first column is selected.
    team = models.ForeignKey(Teams, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'teams_scorers'
        unique_together = (('scorer', 'team'),)


class TeamsSearchEndpoints(models.Model):
    search_endpoint_id = models.BigIntegerField()
    team_id = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = 'teams_search_endpoints'


class Tries(models.Model):
    try_number = models.IntegerField(blank=True, null=True)
    query_params = models.CharField(max_length=20000, blank=True, null=True)
    case = models.ForeignKey(Cases, models.DO_NOTHING, blank=True, null=True)
    field_spec = models.CharField(max_length=500, blank=True, null=True)
    name = models.CharField(max_length=50, blank=True, null=True)
    escape_query = models.IntegerField(blank=True, null=True)
    number_of_rows = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    ancestry = models.CharField(max_length=3072, blank=True, null=True)
    search_endpoint_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tries'


class Users(models.Model):
    email = models.CharField(unique=True, max_length=80, blank=True, null=True)
    password = models.CharField(max_length=120, blank=True, null=True)
    agreed_time = models.DateTimeField(blank=True, null=True)
    agreed = models.IntegerField(blank=True, null=True)
    num_logins = models.IntegerField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    administrator = models.IntegerField(blank=True, null=True)
    reset_password_token = models.CharField(unique=True, max_length=255, blank=True, null=True)
    reset_password_sent_at = models.DateTimeField(blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    locked = models.IntegerField(blank=True, null=True)
    locked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    default_scorer = models.ForeignKey(Scorers, models.DO_NOTHING, blank=True, null=True)
    email_marketing = models.IntegerField()
    invitation_token = models.CharField(unique=True, max_length=255, blank=True, null=True)
    invitation_created_at = models.DateTimeField(blank=True, null=True)
    invitation_sent_at = models.DateTimeField(blank=True, null=True)
    invitation_accepted_at = models.DateTimeField(blank=True, null=True)
    invitation_limit = models.IntegerField(blank=True, null=True)
    invited_by = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True)
    invitations_count = models.IntegerField(blank=True, null=True)
    completed_case_wizard = models.IntegerField()
    stored_raw_invitation_token = models.CharField(max_length=255, blank=True, null=True)
    profile_pic = models.CharField(max_length=4000, blank=True, null=True)
    system_prompt = models.CharField(max_length=4000, blank=True, null=True)
    openai_key = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'users'


class WebRequests(models.Model):
    id = models.BigAutoField(primary_key=True)
    snapshot_query = models.OneToOneField(SnapshotQueries, models.DO_NOTHING, blank=True, null=True)
    request = models.TextField(blank=True, null=True)
    response_status = models.IntegerField(blank=True, null=True)
    integer = models.IntegerField(blank=True, null=True)
    response = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'web_requests'
