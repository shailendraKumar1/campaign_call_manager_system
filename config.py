# config.py

import os


class Config:
    # Celery settings
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

    # Database (PostgreSQL)
    POSTGRES_DB = os.environ.get('POSTGRES_DB', 'campaign_db')
    POSTGRES_USER = os.environ.get('POSTGRES_USER', 'campaign_user')
    POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'yourpassword')
    POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')
    
    # Aliases for backward compatibility
    DB_NAME = POSTGRES_DB
    DB_USER = POSTGRES_USER
    DB_PASSWORD = POSTGRES_PASSWORD
    DB_HOST = POSTGRES_HOST
    DB_PORT = POSTGRES_PORT

    # Redis
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1')

    # App-specific
    MAX_CONCURRENT_CALLS = int(os.environ.get('MAX_CONCURRENT_CALLS', '100'))
    MAX_RETRY_ATTEMPTS = int(os.environ.get('MAX_RETRY_ATTEMPTS', '3'))
    RETRY_SCHEDULE_CONFIG_PATH = os.environ.get('RETRY_SCHEDULE_CONFIG_PATH', 'config/retry_config.yaml')
    
    # DLQ settings
    DLQ_RETENTION_DAYS = int(os.environ.get('DLQ_RETENTION_DAYS', '7'))
    
    # Mock service settings
    MOCK_SERVICE_ENABLED = os.environ.get('MOCK_SERVICE_ENABLED', 'true').lower() == 'true'
    MOCK_SERVICE_URL = os.environ.get('MOCK_SERVICE_URL', 'http://localhost:8001')
    EXTERNAL_CALL_SERVICE_URL = os.environ.get('EXTERNAL_CALL_SERVICE_URL', 'http://localhost:8001')
    
    # Mock service call simulation settings
    MOCK_CALL_DELAY_MIN = float(os.environ.get('MOCK_CALL_DELAY_MIN', '1'))
    MOCK_CALL_DELAY_MAX = float(os.environ.get('MOCK_CALL_DELAY_MAX', '10'))
    
    # Mock service call outcomes (status, probability, duration_range)
    # Probabilities should sum to 1.0
    # Format: [(status, probability, (min_duration, max_duration)), ...]
    MOCK_CALL_OUTCOMES = [
        ('PICKED', 0.60, (30, 180)),        # 60% - Call answered (30s to 3min)
        ('DISCONNECTED', 0.25, (1, 10)),    # 25% - Call disconnected (1-10s)
        ('RNR', 0.10, (20, 40)),            # 10% - Ring no response (20-40s)
        ('FAILED', 0.05, (1, 3)),           # 5% - Call failed immediately (1-3s)
    ]
    
    # Concurrency and duplicate prevention
    REDIS_CONCURRENCY_KEY = os.environ.get('REDIS_CONCURRENCY_KEY', 'active_calls_count')
    REDIS_DUPLICATE_PREVENTION_PREFIX = os.environ.get('REDIS_DUPLICATE_PREVENTION_PREFIX', 'call_lock:')
    DUPLICATE_CALL_WINDOW_MINUTES = int(os.environ.get('DUPLICATE_CALL_WINDOW_MINUTES', '5'))
    
    # Metrics and observability
    METRICS_ENABLED = os.environ.get('METRICS_ENABLED', 'true').lower() == 'true'
    METRICS_PORT = int(os.environ.get('METRICS_PORT', '8000'))
    
    # Security
    SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-j75)4j&*x*lz-nr+e54(lw#@=6b^mf&t@1cua(3@uoo2b_=!v-')
    DEBUG = os.environ.get('DJANGO_DEBUG', 'true').lower() == 'true'
    ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    
    # Authentication
    AUTH_ENABLED = os.environ.get('AUTH_ENABLED', 'true').lower() == 'true'
    X_AUTH_TOKEN = os.environ.get('X_AUTH_TOKEN', 'dev-token-12345')
    
    # Scheduler settings
    SCHEDULER_INTERVAL_MINUTES = int(os.environ.get('SCHEDULER_INTERVAL_MINUTES', '10'))
    SCHEDULER_ENABLED = os.environ.get('SCHEDULER_ENABLED', 'true').lower() == 'true'
    
    # Connection Pooling settings
    DB_CONN_MAX_AGE = int(os.environ.get('DB_CONN_MAX_AGE', '600'))  # PostgreSQL persistent connections (seconds)
    DB_CONN_HEALTH_CHECKS = os.environ.get('DB_CONN_HEALTH_CHECKS', 'true').lower() == 'true'
    REDIS_MAX_CONNECTIONS = int(os.environ.get('REDIS_MAX_CONNECTIONS', '50'))  # Redis connection pool size
    CELERY_BROKER_POOL_LIMIT = int(os.environ.get('CELERY_BROKER_POOL_LIMIT', '50'))  # Celery broker pool
