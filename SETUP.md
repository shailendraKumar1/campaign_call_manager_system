# Setup Guide - Campaign Call Manager System

Complete installation and setup instructions for both local development and Docker deployment.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [Docker Setup (Recommended)](#docker-setup-recommended)
4. [Environment Variables](#environment-variables)
5. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### For Local Development
- Python 3.10+
- PostgreSQL 14+
- Redis 7.0+

### For Docker Deployment
- Docker 20.10+
- Docker Compose 2.0+

---

## Local Development Setup

### 1. Install Dependencies (macOS)

```bash
# Install PostgreSQL and Redis
brew install postgresql@14 redis

# Start services
brew services start postgresql@14
brew services start redis
```

### 2. Setup Project

```bash
# Clone repository
git clone <repo-url>
cd campaign_call_manager_system

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE campaign_db;
CREATE USER campaign_user WITH PASSWORD 'campaign_pass';
GRANT ALL PRIVILEGES ON DATABASE campaign_db TO campaign_user;
\q
```

### 4. Setup Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

### 5. Run Migrations

```bash
python manage.py migrate
```

### 6. Start Services

```bash
# Start all services (Django + Celery + Mock Service)
python manage.py start_all

# OR start individually:
# Terminal 1: Django server
python manage.py runserver

# Terminal 2: Celery worker
celery -A campaign_call_manager_system worker --loglevel=info --concurrency=4

# Terminal 3: Celery Beat
celery -A campaign_call_manager_system beat --loglevel=info

# Terminal 4: Mock service
python mock_service.py
```

### 7. Verify Installation

```bash
# Test API
curl -H "X-Auth-Token: dev-token-12345" \
  http://localhost:8000/api/v1/metrics/

# Expected response: {"current_concurrent_calls":0,...}
```

---

## Docker Setup (Recommended)

### Quick Start

```bash
# 1. Clone repository
git clone <repo-url>
cd campaign_call_manager_system

# 2. Build and start all services
docker-compose up --build -d

# 3. Check service status
docker-compose ps

# 4. View logs
docker-compose logs -f
```

### Container Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    DOCKER COMPOSE SERVICES                      │
└─────────────────────────────────────────────────────────────────┘

Service             Container Name           Port Mapping
─────────────────────────────────────────────────────────────────
web                 campaign_web             8000:8000
postgres            campaign_postgres        5433:5432
redis               campaign_redis           6380:6379
celery_worker       campaign_celery_worker   (internal)
celery_beat         campaign_celery_beat     (internal)
mock-service        campaign_mock_service    8001:8001
```

### Port Mappings

| Service | Internal Port | External Port | Purpose |
|---------|---------------|---------------|---------|
| Django API | 8000 | 8000 | HTTP API |
| PostgreSQL | 5432 | 5433 | Database (avoids local conflict) |
| Redis | 6379 | 6380 | Cache/Broker (avoids local conflict) |
| Mock Service | 8001 | 8001 | External service simulator |

### Service Health Checks

All services include health checks:
- **PostgreSQL**: `pg_isready` every 10s
- **Redis**: `redis-cli ping` every 10s
- **Web**: Django health endpoint every 30s
- **Mock Service**: `/health` endpoint every 30s

### Docker Commands

**Start all services:**
```bash
docker-compose up -d
```

**Stop all services:**
```bash
docker-compose down
```

**Stop and remove volumes (clean slate):**
```bash
docker-compose down -v
```

**View logs (all services):**
```bash
docker-compose logs -f
```

**View logs (specific service):**
```bash
docker-compose logs -f celery_worker
docker-compose logs -f web
docker-compose logs -f celery_beat
```

**Restart a service:**
```bash
docker-compose restart celery_worker
```

**Scale Celery workers:**
```bash
docker-compose up -d --scale celery_worker=8
```

**Execute commands in container:**
```bash
# Django shell
docker-compose exec web python manage.py shell

# Database migrations
docker-compose exec web python manage.py migrate

# Create superuser
docker-compose exec web python manage.py createsuperuser

# Access PostgreSQL
docker-compose exec postgres psql -U campaign_user -d campaign_db
```

### Test Docker Setup

```bash
# 1. Verify all containers are running
docker-compose ps

# 2. Test API health
curl http://localhost:8000/admin/login/

# 3. Test metrics endpoint
curl -H "X-Auth-Token: dev-token-12345" \
  http://localhost:8000/api/v1/metrics/

# 4. Create a campaign
curl -X POST http://localhost:8000/api/v1/campaigns/ \
  -H "X-Auth-Token: dev-token-12345" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Campaign", "description": "Docker test"}'

# 5. Initiate a call
curl -X POST http://localhost:8000/api/v1/initiate-call/ \
  -H "X-Auth-Token: dev-token-12345" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+1234567890", "campaign_id": 1}'
```

---

## Environment Variables

### Local Development (.env file)

```bash
# Database
POSTGRES_DB=campaign_db
POSTGRES_USER=campaign_user
POSTGRES_PASSWORD=campaign_pass
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis
REDIS_URL=redis://localhost:6379/0

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Application
X_AUTH_TOKEN=dev-token-12345
MAX_CONCURRENT_CALLS=100
DB_CONN_MAX_AGE=600
REDIS_MAX_CONNECTIONS=50

# Django
DJANGO_DEBUG=true
DJANGO_SECRET_KEY=your-secret-key-here

# Mock Service
MOCK_SERVICE_ENABLED=true
EXTERNAL_CALL_SERVICE_URL=http://localhost:8001
```

### Docker Environment (docker-compose.yml)

```yaml
environment:
  - POSTGRES_DB=campaign_db
  - POSTGRES_USER=campaign_user
  - POSTGRES_PASSWORD=yourpassword
  - POSTGRES_HOST=postgres
  - REDIS_URL=redis://redis:6379/0
  - CELERY_BROKER_URL=redis://redis:6379/1
  - CELERY_RESULT_BACKEND=redis://redis:6379/2
  - MAX_CONCURRENT_CALLS=100
  - X_AUTH_TOKEN=dev-token-12345
```

### Production Deployment

For production, modify `docker-compose.yml`:

1. **Change passwords**:
   ```yaml
   POSTGRES_PASSWORD: <strong-password>
   X_AUTH_TOKEN: <secure-token>
   ```

2. **Set DEBUG to false**:
   ```yaml
   DJANGO_DEBUG: false
   ```

3. **Use external volumes**:
   ```yaml
   volumes:
     - /data/postgres:/var/lib/postgresql/data
     - /data/redis:/data
   ```

4. **Add resource limits**:
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 2G
   ```

---

## Troubleshooting

### Local Development Issues

**PostgreSQL connection failed:**
```bash
# Check if PostgreSQL is running
brew services list | grep postgresql

# Restart PostgreSQL
brew services restart postgresql@14

# Test connection
psql -U campaign_user -d campaign_db
```

**Redis connection failed:**
```bash
# Check if Redis is running
brew services list | grep redis

# Restart Redis
brew services restart redis

# Test connection
redis-cli ping
```

**Port already in use:**
```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>
```

### Docker Issues

**Container keeps restarting:**
```bash
# Check logs
docker-compose logs celery_beat --tail=50

# Check container status
docker-compose ps
```

**Port already in use:**
```bash
# Change port in docker-compose.yml
ports:
  - "8080:8000"  # Use 8080 instead of 8000
```

**Database not accessible:**
```bash
# Check PostgreSQL is healthy
docker-compose ps postgres

# Connect to database
docker-compose exec postgres psql -U campaign_user -d campaign_db
```

**Reset everything:**
```bash
# Nuclear option - removes all containers, volumes, and images
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d
```

**Permission denied errors:**
```bash
# Fix permissions on log directory
chmod -R 755 logs/
```

### Common Errors

**"django_celery_beat" not installed:**
```bash
pip install django-celery-beat>=2.5.0
```

**"No module named 'calls'":**
```bash
# Ensure you're in the project root directory
cd campaign_call_manager_system

# Reinstall dependencies
pip install -r requirements.txt
```

**Migration errors:**
```bash
# Reset migrations (WARNING: This will delete data)
python manage.py migrate --run-syncdb

# Or for Docker
docker-compose exec web python manage.py migrate --run-syncdb
```

---

## Docker vs Local Development

| Feature | Docker | Local |
|---------|--------|-------|
| Setup Time | 5 minutes | 15-20 minutes |
| Dependencies | Included | Manual install |
| Isolation | Complete | Shared system |
| Port Conflicts | Configurable | May conflict |
| Best For | Production, CI/CD | Active development |

**Recommendation**: Use Docker for production and testing, local setup for active development.

---

## Next Steps

After setup, refer to:
- **README.md** - System architecture and requirements
- **WORKFLOW_DOCUMENTATION.md** - Detailed workflow and API usage
- **Postman Collection** - Ready-to-use API tests

---

**🎉 Setup Complete!** Your Campaign Call Manager System is ready to use.
