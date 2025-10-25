# Campaign Call Manager System - Complete Guide

A production-ready Django-based system for managing outbound call campaigns with intelligent retry logic, authentication, comprehensive logging, and event-driven architecture.

## 📋 Table of Contents
- [Features](#features)
- [System Architecture](#system-architecture)
- [Setup Instructions](#setup-instructions)
- [Complete Run Flow](#complete-run-flow)
- [API Testing](#api-testing)
- [Monitoring & Troubleshooting](#monitoring--troubleshooting)

---

## ✨ Features

### Core Functionality
- **Campaign Management** - Create and manage call campaigns
- **Phone Number Management** - Add/import phone numbers to campaigns
- **Call Initiation** - RESTful API for triggering outbound calls
- **Callback Processing** - Handle external service callbacks
- **Status Tracking** - INITIATED, PICKED, DISCONNECTED, RNR, FAILED, RETRYING

### Advanced Features
- **Intelligent Retry System** - YAML-configured retry rules with time slots and day-specific settings
- **X-Auth-Token Authentication** - Header-based token authentication
- **Custom Exception Handling** - Standardized error responses (400, 401, 404, 500, etc.)
- **Comprehensive Logging** - 6 separate rotating log files (app, error, debug, calls, api, kafka)
- **Concurrency Control** - Redis-based duplicate prevention and concurrent call limits
- **Metrics & Monitoring** - Real-time call metrics and system health
- **Event-Driven Architecture** - Kafka-based async processing
- **Dead Letter Queue** - Failed message handling with automatic retry

### Technical Stack
- **Backend**: Django 4.2+ with Django REST Framework
- **Database**: PostgreSQL
- **Cache**: Redis
- **Messaging**: Apache Kafka
- **Scheduler**: Python schedule library
- **Containerization**: Docker & Docker Compose

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLIENT (API REQUEST)                        │
│                  X-Auth-Token: dev-token-12345                  │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                   DJANGO API SERVER (Port 8000)                 │
│  • Authentication Middleware                                    │
│  • Request Logging Middleware                                   │
│  • Custom Exception Handler                                     │
│  • REST API Views                                               │
└────────┬───────────────────────────┬──────────────────┬─────────┘
         ↓                           ↓                  ↓
┌─────────────────┐    ┌──────────────────────┐   ┌────────────┐
│   PostgreSQL    │    │       Redis          │   │   Kafka    │
│   - Campaigns   │    │  - Concurrency       │   │  - Topics  │
│   - CallLogs    │    │  - Cache             │   │  - Events  │
│   - Metrics     │    │  - Locks             │   │  - DLQ     │
└─────────────────┘    └──────────────────────┘   └─────┬──────┘
         ↑                           ↑                   ↓
         │                           │         ┌──────────────────┐
         │                           │         │  Kafka Consumers │
         │                           │         │  (Background)    │
         │                           └─────────┤  - Process calls │
         │                                     │  - Callbacks     │
         └─────────────────────────────────────┴──────────────────┘
                                               
┌─────────────────────────────────────────────────────────────────┐
│              RETRY SCHEDULER (Background Process)               │
│  • Scans for DISCONNECTED/RNR calls every minute                │
│  • Checks retry windows from config/retry_config.yaml          │
│  • Republishes retry events to Kafka                            │
│  • Enforces max retry attempts                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│            MOCK EXTERNAL SERVICE (Port 8001)                    │
│  • Simulates real call service                                  │
│  • Receives call initiation requests                            │
│  • Sends callback webhooks                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

# 🔧 Setup Instructions

## Prerequisites

Ensure the following are installed and running:

- **Python 3.11+**
- **PostgreSQL** (port 5432)
- **Redis** (port 6379)
- **Apache Kafka** (port 9092)
- **Git**

### Install Infrastructure Services

#### Option 1: Using Docker Compose (Recommended)

```bash
# Create docker-compose.yml for infrastructure services only
docker-compose up -d postgres redis kafka
```

#### Option 2: Local Installation (macOS)

```bash
# Install PostgreSQL
brew install postgresql@14
brew services start postgresql@14

# Install Redis
brew install redis
brew services start redis

# Install Kafka
brew install kafka
brew services start kafka
```

#### Option 3: Local Installation (Ubuntu/Debian)

```bash
# PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql

# Redis
sudo apt install redis-server
sudo systemctl start redis

# Kafka
wget https://downloads.apache.org/kafka/3.5.0/kafka_3.5.0-src.tgz
tar -xzf kafka_3.5.0-src.tgz
cd kafka_3.5.0-src
bin/zookeeper-server-start.sh config/zookeeper.properties &
bin/kafka-server-start.sh config/server.properties &
```

---

## Step 1: Clone Repository

```bash
git clone <your-repository-url>
cd campaign_call_manager_system
```

---

## Step 2: Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# OR
.venv\Scripts\activate  # Windows
```

---

## Step 3: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Key dependencies:**
- Django 4.2+
- djangorestframework
- psycopg2-binary (PostgreSQL)
- redis
- kafka-python
- pyyaml
- schedule
- requests

---

## Step 4: Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env file with your settings
nano .env
```

**Required environment variables:**

```bash
# Database Configuration
DB_NAME=campaign_db
DB_USER=campaign_user
DB_PASSWORD=your_secure_password
DB_HOST=localhost
DB_PORT=5432

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_INITIATE_CALL_TOPIC=initiated_call_topic
KAFKA_CALLBACK_TOPIC=callback_topic
KAFKA_DLQ_TOPIC=dlq_topic

# Authentication (for development)
AUTH_ENABLED=True
VALID_TOKENS=dev-token-12345,another-token-67890

# Retry Configuration
SCHEDULER_ENABLED=True
SCHEDULER_INTERVAL_MINUTES=1
MAX_RETRY_ATTEMPTS=3
RETRY_SCHEDULE_CONFIG_PATH=config/retry_config.yaml

# Concurrency Configuration
MAX_CONCURRENT_CALLS=100
DUPLICATE_CALL_WINDOW_MINUTES=5

# External Service Configuration
EXTERNAL_SERVICE_URL=http://localhost:8001/initiate-call
EXTERNAL_SERVICE_TIMEOUT_SECONDS=30
```

---

## Step 5: Setup PostgreSQL Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE campaign_db;
CREATE USER campaign_user WITH PASSWORD 'your_secure_password';
ALTER ROLE campaign_user SET client_encoding TO 'utf8';
ALTER ROLE campaign_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE campaign_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE campaign_db TO campaign_user;

# Exit PostgreSQL
\q
```

---

## Step 6: Create Kafka Topics

```bash
# Create initiated_call_topic
kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic initiated_call_topic \
  --partitions 3 \
  --replication-factor 1

# Create callback_topic
kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic callback_topic \
  --partitions 3 \
  --replication-factor 1

# Create dlq_topic
kafka-topics --create \
  --bootstrap-server localhost:9092 \
  --topic dlq_topic \
  --partitions 1 \
  --replication-factor 1

# Verify topics
kafka-topics --list --bootstrap-server localhost:9092
```

---

## Step 7: Run Database Migrations

```bash
# Apply migrations
python manage.py migrate

# Verify migrations
python manage.py showmigrations
```

---

## Step 8: Create Retry Configuration File

The file `config/retry_config.yaml` should already exist. Verify its contents:

```bash
cat config/retry_config.yaml
```

**Example configuration:**

```yaml
# Global retry rules (apply to all campaigns)
global_rules:
  - name: "Weekday Business Hours"
    days: ["monday", "tuesday", "wednesday", "thursday", "friday"]
    time_slots:
      - start_time: "09:00"
        end_time: "17:00"
        max_attempts: 3
        retry_interval_minutes: 60

# Campaign-specific rules (override global)
campaign_rules:
  - campaign_id: 1
    name: "High Priority Campaign"
    rules:
      - name: "Aggressive Retry"
        days: ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        time_slots:
          - start_time: "00:00"
            end_time: "23:59"
            max_attempts: 5
            retry_interval_minutes: 30

# Default settings
defaults:
  max_attempts: 3
  retry_interval_minutes: 60
  concurrent_call_limit: 100

# Scheduler settings
scheduler:
  check_interval_minutes: 1
  batch_size: 100
  max_concurrent_retries: 50
```

---

## Step 9: Verify Setup

```bash
# Check database connection
python manage.py check --database default

# Check Redis connection
redis-cli ping
# Expected: PONG

# Check Kafka
nc -zv localhost 9092
# Expected: Connection to localhost port 9092 [tcp/*] succeeded!

# Check all system checks
python manage.py check
```

---

# 🚀 Complete Run Flow

## Quick Start - Single Command (Recommended)

### Start All Services at Once

```bash
# Activate virtual environment
source .venv/bin/activate

# Start everything with one command
python manage.py start_all
```

**This starts:**
- ✅ Django API Server (port 8000)
- ✅ Kafka Consumers (2 consumers for call initiation and callbacks)
- ✅ Retry Scheduler (checks for retries every minute)
- ✅ Mock External Service (port 8001)

**To stop:** Press `Ctrl+C`

---

## Manual Start (Individual Services)

If you prefer to start services individually for debugging:

### Terminal 1: Django API Server

```bash
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000
```

### Terminal 2: Kafka Consumers

```bash
source .venv/bin/activate
python manage.py run_consumers
```

### Terminal 3: Retry Scheduler

```bash
source .venv/bin/activate
python manage.py run_scheduler
```

### Terminal 4: Mock External Service (Optional)

```bash
source .venv/bin/activate
python mock_service.py
```

---

## Complete End-to-End Test Flow

### Step 1: Create Campaign

```bash
curl -X POST http://localhost:8000/api/v1/campaigns/ \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: dev-token-12345" \
  -d '{
    "name": "Marketing Campaign Q1",
    "description": "Cold calling for Q1 leads"
  }'
```

**Expected Response:**
```json
{
  "id": 1,
  "name": "Marketing Campaign Q1",
  "description": "Cold calling for Q1 leads",
  "is_active": true,
  "created_at": "2025-01-24T10:30:00Z",
  "updated_at": "2025-01-24T10:30:00Z"
}
```

---

### Step 2: Add Phone Numbers

```bash
curl -X POST http://localhost:8000/api/v1/phone-numbers/ \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: dev-token-12345" \
  -d '{
    "campaign_id": 1,
    "phone_numbers": [
      "+1234567890",
      "+1234567891",
      "+1234567892"
    ]
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "campaign_id": 1,
  "added_count": 3,
  "phone_numbers": ["+1234567890", "+1234567891", "+1234567892"]
}
```

---

### Step 3: Initiate Call

```bash
curl -X POST http://localhost:8000/api/v1/initiate-call/ \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: dev-token-12345" \
  -d '{
    "phone_number": "+1234567890",
    "campaign_id": 1
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "call_id": "call_1_+1234567890_20250124103000",
  "status": "INITIATED",
  "phone_number": "+1234567890",
  "campaign_id": 1,
  "attempt_count": 1,
  "max_attempts": 3
}
```

---

### Step 4: What Happens Next (Behind the Scenes)

```
1. API creates CallLog in PostgreSQL (status: INITIATED)
   ↓
2. API publishes event to Kafka → initiated_call_topic
   ↓
3. Consumer receives message from Kafka
   ↓
4. Consumer calls external service (mock_service.py)
   ↓
5. External service processes call
   ↓
6. External service sends callback webhook to /api/v1/callback/
   ↓
7. Callback API receives status (PICKED, DISCONNECTED, RNR, FAILED)
   ↓
8. Callback API publishes to Kafka → callback_topic
   ↓
9. Callback consumer receives message
   ↓
10. Consumer updates CallLog in database

IF status = PICKED or FAILED:
   → End concurrency tracking
   → Call complete

IF status = DISCONNECTED or RNR:
   → Keep call active for retry
   → Scheduler picks up for retry (every minute)
   → Republishes to Kafka
   → Process repeats until PICKED or max attempts reached
```

---

### Step 5: Monitor Call Status

```bash
# Check metrics
curl -H "X-Auth-Token: dev-token-12345" \
  http://localhost:8000/api/v1/metrics/
```

**Expected Response:**
```json
{
  "current_concurrent_calls": 0,
  "max_concurrent_calls": 100,
  "system_status": "healthy",
  "recent_metrics": [
    {
      "date": "2025-01-24",
      "total_calls_initiated": 3,
      "total_calls_picked": 2,
      "total_calls_disconnected": 1,
      "total_calls_rnr": 0,
      "total_calls_failed": 0,
      "total_retries": 1,
      "peak_concurrent_calls": 3,
      "total_call_duration": 150,
      "avg_call_duration": 75.0
    }
  ]
}
```

---

### Step 6: Test Retry Mechanism

#### Scenario 1: Call Gets DISCONNECTED

```bash
# 1. Initiate call
CALL_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/initiate-call/ \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: dev-token-12345" \
  -d '{"phone_number": "+1555000001", "campaign_id": 1}')

CALL_ID=$(echo $CALL_RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['call_id'])")

# 2. Manually send DISCONNECTED callback (simulating failure)
curl -X PUT http://localhost:8000/api/v1/callback/ \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: dev-token-12345" \
  -d "{
    \"call_id\": \"$CALL_ID\",
    \"status\": \"DISCONNECTED\",
    \"call_duration\": 5
  }"

# 3. Wait 1 minute - scheduler will pick up for retry
echo "Waiting for scheduler to retry (60 seconds)..."
sleep 65

# 4. Check logs to see retry
tail -n 20 logs/app.log | grep -i retry
```

**Expected Log Output:**
```
[INFO] 2025-01-24 10:35:00 calls.scheduler - Retrying call call_1_+1555000001_... (attempt 2)
```

#### Scenario 2: Max Attempts Reached

```bash
# After 3 DISCONNECTED attempts, call marked as FAILED
# Check database
psql -h localhost -U campaign_user -d campaign_db -c \
  "SELECT call_id, status, attempt_count, error_message 
   FROM calls_calllog 
   WHERE phone_number='+1555000001';"

# Expected output:
# status='FAILED', attempt_count=3, error_message='Max retry attempts reached (3)'
```

---

## View Logs in Real-Time

### All Logs

```bash
tail -f logs/app.log
```

### API Requests

```bash
tail -f logs/api.log | grep "Incoming Request"
```

### Call Operations

```bash
tail -f logs/calls.log
```

### Kafka Events

```bash
tail -f logs/kafka.log | grep "Processing"
```

### Errors Only

```bash
tail -f logs/error.log
```

### Retry Activity

```bash
tail -f logs/app.log | grep -i retry
```

---

# 🧪 API Testing

## Available Endpoints

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| `/api/v1/campaigns/` | POST | Yes | Create campaign |
| `/api/v1/campaigns/` | GET | Yes | List all campaigns |
| `/api/v1/campaigns/{id}/` | GET | Yes | Get campaign details |
| `/api/v1/phone-numbers/` | POST | Yes | Add phone numbers |
| `/api/v1/initiate-call/` | POST | Yes | Initiate call |
| `/api/v1/callback/` | PUT | Yes | Process callback |
| `/api/v1/metrics/` | GET | Yes | Get metrics |

## Authentication

All API requests require authentication header:

```bash
-H "X-Auth-Token: dev-token-12345"
```

**Valid tokens** (configured in `.env`):
- `dev-token-12345`
- `another-token-67890`

## Using Postman

Import the provided Postman collection:

1. Open Postman
2. Import `Campaign_Call_Manager.postman_collection.json`
3. Set collection variable `authToken` to `dev-token-12345`
4. Set collection variable `baseUrl` to `http://localhost:8000`
5. Run requests or entire collection

---

## Error Handling Examples

### 401 Unauthorized (Missing Token)

```bash
curl -X GET http://localhost:8000/api/v1/metrics/
```

**Response:**
```json
{
  "error": {
    "code": "unauthorized",
    "message": "Authentication credentials were not provided or are invalid.",
    "details": {}
  }
}
```

### 404 Not Found (Campaign Not Found)

```bash
curl -X GET http://localhost:8000/api/v1/campaigns/999/ \
  -H "X-Auth-Token: dev-token-12345"
```

**Response:**
```json
{
  "error": {
    "code": "not_found",
    "message": "Campaign not found or inactive.",
    "details": {}
  }
}
```

### 400 Bad Request (Invalid Phone Number)

```bash
curl -X POST http://localhost:8000/api/v1/initiate-call/ \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: dev-token-12345" \
  -d '{
    "phone_number": "invalid",
    "campaign_id": 1
  }'
```

**Response:**
```json
{
  "error": {
    "code": "bad_request",
    "message": "Invalid phone number format. Must start with + and contain digits.",
    "details": {}
  }
}
```

---

# 📊 Monitoring & Troubleshooting

## Database Monitoring

### Check Call Status Distribution

```bash
psql -h localhost -U campaign_user -d campaign_db -c \
  "SELECT status, COUNT(*) as count 
   FROM calls_calllog 
   GROUP BY status;"
```

### Check Retry Candidates

```bash
psql -h localhost -U campaign_user -d campaign_db -c \
  "SELECT call_id, phone_number, status, attempt_count, next_retry_at 
   FROM calls_calllog 
   WHERE status IN ('DISCONNECTED', 'RNR') 
   AND attempt_count < max_attempts 
   ORDER BY next_retry_at;"
```

### Check Recent Calls

```bash
psql -h localhost -U campaign_user -d campaign_db -c \
  "SELECT call_id, phone_number, status, attempt_count, created_at 
   FROM calls_calllog 
   ORDER BY created_at DESC 
   LIMIT 10;"
```

---

## Redis Monitoring

```bash
# Check active calls count
redis-cli GET active_calls_count

# Check duplicate call locks
redis-cli KEYS "call_lock:*"

# Monitor Redis in real-time
redis-cli MONITOR
```

---

## Kafka Monitoring

### List Topics

```bash
kafka-topics --list --bootstrap-server localhost:9092
```

### Check Messages in Topics

```bash
# View initiated_call_topic messages
kafka-console-consumer --bootstrap-server localhost:9092 \
  --topic initiated_call_topic \
  --from-beginning \
  --max-messages 10

# View callback_topic messages
kafka-console-consumer --bootstrap-server localhost:9092 \
  --topic callback_topic \
  --from-beginning \
  --max-messages 10
```

### Check Consumer Group Lag

```bash
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --describe --group call_initiation_consumer_group

kafka-consumer-groups --bootstrap-server localhost:9092 \
  --describe --group callback_consumer_group
```

---

## Common Issues & Solutions

### Issue 1: Services Not Starting

**Symptoms:**
- `python manage.py start_all` fails
- Services crash immediately

**Solutions:**

```bash
# Check if ports are in use
lsof -i :8000  # Django
lsof -i :8001  # Mock service
lsof -i :9092  # Kafka
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis

# Kill processes if needed
kill -9 $(lsof -ti:8000)

# Restart infrastructure services
brew services restart postgresql@14
brew services restart redis
brew services restart kafka
```

---

### Issue 2: Consumers Not Processing Messages

**Symptoms:**
- API calls succeed but nothing happens
- No logs in `logs/kafka.log`

**Solutions:**

```bash
# Check if consumers are running
ps aux | grep run_consumers

# Check Kafka connection
nc -zv localhost 9092

# Restart consumers
# Stop start_all (Ctrl+C)
python manage.py start_all
```

---

### Issue 3: Retries Not Happening

**Symptoms:**
- Calls stay in DISCONNECTED/RNR status
- No retry attempts

**Solutions:**

```bash
# Check if scheduler is running
ps aux | grep run_scheduler

# Check next_retry_at field
psql -h localhost -U campaign_user -d campaign_db -c \
  "SELECT call_id, status, next_retry_at, attempt_count 
   FROM calls_calllog 
   WHERE status='DISCONNECTED';"

# Verify retry configuration
cat config/retry_config.yaml

# Check scheduler logs
tail -f logs/app.log | grep -i scheduler

# Manually trigger retry check
python manage.py shell
>>> from calls.scheduler import retry_scheduler
>>> retry_scheduler.retry_failed_calls()
```

---

### Issue 4: Database Connection Errors

**Symptoms:**
- `django.db.utils.OperationalError`
- "could not connect to server"

**Solutions:**

```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Restart PostgreSQL
brew services restart postgresql@14

# Verify database exists
psql -U postgres -c "\l" | grep campaign_db

# Test connection
psql -h localhost -U campaign_user -d campaign_db -c "SELECT 1;"
```

---

### Issue 5: Redis Connection Errors

**Symptoms:**
- `redis.exceptions.ConnectionError`
- Concurrency features not working

**Solutions:**

```bash
# Check Redis is running
redis-cli ping
# Expected: PONG

# Restart Redis
brew services restart redis

# Check Redis logs
tail -f /usr/local/var/log/redis.log

# Verify connection from Python
python -c "import redis; r=redis.Redis(host='localhost', port=6379); print(r.ping())"
```

---

## Useful Commands

### Generate Metrics

```bash
python manage.py generate_metrics --days 7
```

### Cleanup Dead Letter Queue

```bash
python manage.py cleanup_dlq
```

### Check System Health

```bash
python manage.py check
```

### View All Management Commands

```bash
python manage.py help
```

---

## Log Files

| Log File | Content | Location |
|----------|---------|----------|
| `app.log` | General application logs | `logs/app.log` |
| `error.log` | All errors | `logs/error.log` |
| `debug.log` | Debug information | `logs/debug.log` |
| `calls.log` | Call operations | `logs/calls.log` |
| `api.log` | API requests/responses | `logs/api.log` |
| `kafka.log` | Kafka events | `logs/kafka.log` |

**Log Rotation:**
- Max size: 10MB per file
- Backups: 10 files
- Automatic rotation when size exceeded

---

## Performance Tips

### Optimize Kafka

```bash
# Increase partitions for parallel processing
kafka-topics --alter \
  --bootstrap-server localhost:9092 \
  --topic initiated_call_topic \
  --partitions 6
```

### Optimize PostgreSQL

```sql
-- Add indexes for frequently queried columns
CREATE INDEX idx_calllog_status ON calls_calllog(status);
CREATE INDEX idx_calllog_next_retry ON calls_calllog(next_retry_at);
CREATE INDEX idx_calllog_phone ON calls_calllog(phone_number);
```

### Scale Consumers

```bash
# Run multiple consumer instances
python manage.py run_consumers --consumer initiate &
python manage.py run_consumers --consumer initiate &
python manage.py run_consumers --consumer callback &
```

---

## 🎉 Summary

### **Start System:**
```bash
python manage.py start_all
```

### **Test Complete Flow:**
```bash
# Create campaign → Add numbers → Initiate call → Monitor
curl -H "X-Auth-Token: dev-token-12345" http://localhost:8000/api/v1/metrics/
```

### **Monitor:**
```bash
tail -f logs/app.log    # All activity
tail -f logs/kafka.log  # Kafka events
tail -f logs/calls.log  # Call operations
```

### **Stop System:**
```
Ctrl+C
```

---

## ✅ Features Verified

- ✅ Campaign management (create, list, retrieve)
- ✅ Phone number management (add, bulk import)
- ✅ Call initiation via REST API
- ✅ External service integration (mock_service.py)
- ✅ Callback webhook processing
- ✅ Event-driven architecture (Kafka)
- ✅ Async processing (consumers)
- ✅ Retry mechanism (DISCONNECTED/RNR)
- ✅ Time-based retry windows
- ✅ Max attempts enforcement
- ✅ Concurrency control
- ✅ Duplicate call prevention
- ✅ Authentication (X-Auth-Token)
- ✅ Exception handling (400, 401, 404, 500)
- ✅ Comprehensive logging (6 log files)
- ✅ Metrics & monitoring
- ✅ Dead letter queue (DLQ)
- ✅ Health checks
- ✅ Production-ready

---

## 🚀 System Ready!

Your Campaign Call Manager System is **production-ready** with complete setup and run instructions in this single README.md file!

For questions or issues, check the troubleshooting section above or review the logs.

**Happy calling! 📞**
