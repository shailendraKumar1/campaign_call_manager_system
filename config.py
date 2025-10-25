# config.py

import os


class Config:
    # Kafka settings
    KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(",")
    KAFKA_INITIATE_CALL_TOPIC = os.environ.get('KAFKA_INITIATE_CALL_TOPIC', 'initiated_call_topic')
    KAFKA_CALLBACK_TOPIC = os.environ.get('KAFKA_CALLBACK_TOPIC', 'callback_topic')
    KAFKA_DLQ_TOPIC = os.environ.get('KAFKA_DLQ_TOPIC', 'dlq_topic')

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
    SCHEDULER_INTERVAL_MINUTES = int(os.environ.get('SCHEDULER_INTERVAL_MINUTES', '1'))
    SCHEDULER_ENABLED = os.environ.get('SCHEDULER_ENABLED', 'true').lower() == 'true'
