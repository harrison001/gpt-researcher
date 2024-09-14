import os
import multiprocessing

# Define necessary configuration variables for Gunicorn
bind = "0.0.0.0:8097"

# Calculate number of workers based on CPU count
workers = (2 * multiprocessing.cpu_count()) + 1

# Set log level
loglevel = "info"

# Enable reload based on environment variable
reload = os.getenv("FASTAPI_RELOAD", "false").lower() == "true"

# Optional: Add other Gunicorn settings as needed
# For example, to enable access logging, you can add:
# accesslog = "-"