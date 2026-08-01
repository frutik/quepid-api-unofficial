import os

bind = f"0.0.0.0:{os.getenv('GUNICORN_PORT', '8000')}"
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("GUNICORN_WORKERS", 1))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))
