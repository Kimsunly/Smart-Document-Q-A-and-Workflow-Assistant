# Celery configuration for Windows compatibility
from kombu import Exchange, Queue

broker_url = 'redis://localhost:6379/0'
result_backend = 'redis://localhost:6379/0'

# Use thread pool on Windows (fork not supported)
worker_pool = 'threads'
worker_prefetch_multiplier = 1
worker_max_tasks_per_child = 1000

# Serialization
accept_content = ['json']
task_serializer = 'json'
result_serializer = 'json'

# Timezone
timezone = 'UTC'
enable_utc = True

# Task configuration
task_track_started = True
task_time_limit = 30 * 60  # 30 minutes hard limit
task_soft_time_limit = 25 * 60  # 25 minutes soft limit
