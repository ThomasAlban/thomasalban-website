"""One small SQLite service behind the local nginx proxy."""

bind = '127.0.0.1:8000'
workers = 1
threads = 4
worker_class = 'gthread'
timeout = 60
graceful_timeout = 25
# Django alone interprets the scheme header overwritten by local nginx.
forwarded_allow_ips = ''
secure_scheme_headers = {}
accesslog = None  # nginx logs without query strings.
errorlog = '-'
capture_output = True
