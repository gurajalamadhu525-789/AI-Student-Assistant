import os

port = os.environ.get("PORT", "5002")
bind = f"0.0.0.0:{port}"
timeout = 120
workers = 2
