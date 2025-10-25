# API Call Flow - Complete Sequence Diagram

## 📞 What Happens When You Execute This cURL Command

```bash
curl --location 'http://localhost:8000/api/v1/initiate-call/' \
--header 'Content-Type: application/json' \
--header 'X-Auth-Token: dev-token-12345' \
--data '{
    "phone_number": "+918840265502",
    "campaign_id": 3
}'
```

---

## 🔄 Complete Sequence Diagram

```
Client        Middleware      Django View     Kafka Topic    Consumer       Mock Service    Callback
  |               |               |               |              |                |             |
  | 1. POST       |               |               |              |                |             |
  |   initiate    |               |               |              |                |             |
  |   call        |               |               |              |                |             |
  |-------------->|               |               |              |                |             |
  |               |               |               |              |                |             |
  |               | 2. Validate   |               |              |                |             |
  |               |    Token      |               |              |                |             |
  |               |    (Auth)     |               |              |                |             |
  |               |-------------->|               |              |                |             |
  |               |               |               |              |                |             |
  |               |               | 3. Validate   |              |                |             |
  |               |               |    Phone &    |              |                |             |
  |               |               |    Campaign   |              |                |             |
  |               |               |               |              |                |             |
  |               |               | 4. Check      |              |                |             |
  |               |               |    Concurrency|              |                |             |
  |               |               |    (Redis)    |              |                |             |
  |               |               |               |              |                |             |
  |               |               | 5. Create     |              |                |             |
  |               |               |    CallLog    |              |                |             |
  |               |               |    (PostgreSQL)|             |                |             |
  |               |               |               |              |                |             |
  |               |               | 6. Track      |              |                |             |
  |               |               |    Metrics    |              |                |             |
  |               |               |    (Redis)    |              |                |             |
  |               |               |               |              |                |             |
  |               |               | 7. Publish    |              |                |             |
  |               |               |    Event      |              |                |             |
  |               |               |-------------->|              |                |             |
  |               |               |               |              |                |             |
  |               |               | 8. Return     |              |                |             |
  |               |               |    201        |              |                |             |
  |<------------------------------|               |              |                |             |
  | Response:                     |               |              |                |             |
  | {call_id,                     |               |              |                |             |
  |  status:                      |               |              |                |             |
  |  INITIATED}                   |               |              |                |             |
  |                               |               |              |                |             |
  |                               |               | 9. Poll      |                |             |
  |                               |               |<-------------|                |             |
  |                               |               |              |                |             |
  |                               |               |              | 10. Process    |             |
  |                               |               |              |     Initiation |             |
  |                               |               |              |                |             |
  |                               |               |              | 11. HTTP POST  |             |
  |                               |               |              |     External   |             |
  |                               |               |              |     Service    |             |
  |                               |               |              |--------------->|             |
  |                               |               |              |                |             |
  |                               |               |              |                | 12. Generate|
  |                               |               |              |                |     ext_id  |
  |                               |               |              |                |             |
  |                               |               |              |                | 13. Start   |
  |                               |               |              |                |     Simulation
  |                               |               |              |                |     (Thread)|
  |                               |               |              |                |             |
  |                               |               |              |                | 14. Return  |
  |                               |               |              |<---------------|     Success |
  |                               |               |              |                |             |
  |                               |               |              | 15. Update     |             |
  |                               |               |              |     CallLog    |             |
  |                               |               |              |     ext_id     |             |
  |                               |               |              |                |             |
  |                               |               |              |                | [Wait 1-10s]|
  |                               |               |              |                |             |
  |                               |               |              |                | 16. Callback|
  |                               |               |              |                |     Webhook |
  |                               |<----------------------------------------------|             |
  |                               |               |              |                |             |
  |                               | 17. Process   |              |                |             |
  |                               |     Callback  |              |                |             |
  |                               |     (View)    |              |                |             |
  |                               |               |              |                |             |
  |                               | 18. Update    |              |                |             |
  |                               |     CallLog   |              |                |             |
  |                               |     Status    |              |                |             |
  |                               |               |              |                |             |
  |                               | 19. Publish   |              |                |             |
  |                               |     Callback  |              |                |             |
  |                               |     Event     |              |                |             |
  |                               |-------------->|              |                |             |
  |                               |               |              |                |             |
  |                               |               | 20. Consumer |                |             |
  |                               |               |     Processes|                |             |
  |                               |               |<-------------|                |             |
  |                               |               |              |                |             |
  |                               |               |              | 21. Final      |             |
  |                               |               |              |     Status     |             |
  |                               |               |              |     Update     |             |
```

---

## 📝 Step-by-Step Explanation

### **Phase 1: API Request (Synchronous - ~100ms)**

#### Step 1-2: Authentication
- **File**: `calls/middleware.py` - AuthTokenMiddleware
- **Action**: Validates `X-Auth-Token: dev-token-12345`
- **Result**: ✓ Token valid, proceed OR ✗ 401 Unauthorized

#### Step 3: Validation
- **File**: `calls/views.py:45-70` - InitiateCallView
- **Checks**:
  - Phone number format valid? (must start with +)
  - Campaign exists and is active?
- **Result**: ✓ Valid OR ✗ 400/404 error

#### Step 4: Concurrency Check
- **File**: `calls/utils.py` - ConcurrencyManager
- **Checks**:
  - Current concurrent calls < 100?
  - Duplicate call in last 5 minutes?
- **Uses**: Redis
- **Result**: ✓ Can proceed OR ✗ 409 Conflict

#### Step 5: Create Database Record
- **File**: `calls/views.py:72`
- **Action**: Create `CallLog` in PostgreSQL
```python
call_log = CallLog.objects.create(
    call_id="call_3_+918840265502_1761367864_df2201b3",
    phone_number="+918840265502",
    campaign_id=3,
    status='INITIATED',
    attempt_count=1
)
```

#### Step 6: Track Metrics
- **File**: `calls/utils.py` - MetricsManager
- **Action**: Update Redis metrics
  - Increment `total_calls_initiated`
  - Update `active_calls_count`

#### Step 7: Publish to Kafka
- **File**: `calls/publisher.py:68-90`
- **Topic**: `initiated_call_topic`
- **Message**:
```json
{
  "call_id": "call_3_+918840265502_1761367864_df2201b3",
  "phone_number": "+918840265502",
  "campaign_id": 3,
  "campaign_name": "Workflow Test Campaign"
}
```

#### Step 8: Return Response
- **HTTP Status**: 201 Created
- **Response**:
```json
{
  "success": true,
  "call_id": "call_3_+918840265502_1761367864_df2201b3",
  "status": "INITIATED",
  "phone_number": "+918840265502",
  "campaign_id": 3
}
```

**⚡ API request completes here! Client receives response immediately.**

---

### **Phase 2: Background Processing (Asynchronous)**

#### Step 9-10: Consumer Processes Event
- **File**: `calls/consumer.py:88-124`
- **Action**: Consumer polls Kafka and receives message
```python
def process_call_initiation(self, data):
    call_log = CallLog.objects.get(call_id=data['call_id'])
    call_log.status = 'PROCESSING'
    call_log.save()
```

#### Step 11: Call External Service
- **File**: `calls/consumer.py:172-202`
- **Action**: HTTP POST to mock service
```python
response = requests.post(
    "http://localhost:8001/api/initiate-call",
    json={
        'call_id': call_log.call_id,
        'phone_number': call_log.phone_number,
        'campaign_id': call_log.campaign.id
    }
)
```

#### Step 12-14: Mock Service Processing
- **File**: `mock_service.py:123-167`
- **Actions**:
  1. Generate `external_call_id`: `"ext_abc123"`
  2. Store call info
  3. Start background thread for simulation
  4. Return success immediately

#### Step 15: Update External ID
```python
call_log.external_call_id = "ext_abc123"
call_log.status = 'INITIATED'
call_log.save()
```

---

### **Phase 3: Call Simulation & Callback**

#### Step 16: Mock Service Simulates Call
- **File**: `mock_service.py:52-106`
- **Delay**: 1-10 seconds (random)
- **Outcomes**:
  - 60% → `PICKED` (10-120 sec duration)
  - 25% → `DISCONNECTED` (2-10 sec)
  - 15% → `RNR` (30-45 sec)

#### Step 17: Callback Webhook
- **Action**: Mock service sends webhook
```python
requests.put(
    "http://localhost:8000/api/v1/callback/",
    json={
        'call_id': "call_3_+918840265502_...",
        'status': 'PICKED',  # or DISCONNECTED, RNR
        'call_duration': 45,
        'external_call_id': 'ext_abc123'
    }
)
```

#### Step 18-19: Process Callback
- **File**: `calls/views.py:90-160` - CallbackView
- **Actions**:
```python
call_log.status = status  # PICKED, DISCONNECTED, RNR
call_log.total_call_time = call_duration

if status == 'PICKED':
    call_log.status = 'COMPLETED'
    ConcurrencyManager.end_call(call_id, phone_number)
elif status in ['DISCONNECTED', 'RNR']:
    # Calculate next retry time
    call_log.next_retry_at = calculate_next_retry()
```

#### Step 20-21: Callback Consumer
- **File**: `calls/consumer.py:126-170`
- **Action**: Processes callback event from Kafka
- **Handles**: Retry logic for DISCONNECTED/RNR

---

## 🔄 What If Call Fails?

### **DISCONNECTED or RNR Scenario:**

```
1. Callback received: status = DISCONNECTED
   ↓
2. CallLog updated: status = 'DISCONNECTED', attempt_count = 1
   ↓
3. Scheduler runs (every 1 minute)
   File: calls/scheduler.py:127-209
   ↓
4. Finds retry-eligible calls:
   WHERE status IN ('DISCONNECTED', 'RNR')
   AND attempt_count < max_attempts (3)
   AND next_retry_at <= NOW()
   ↓
5. Checks retry window (from retry_config.yaml)
   ↓
6. If in window:
   - Update: attempt_count = 2, status = 'RETRYING'
   - Publish retry event to Kafka
   ↓
7. Consumer processes retry (same flow as new call)
   ↓
8. Repeats until PICKED or max_attempts reached
```

**After 3 Failed Attempts:**
```python
if attempt_count >= 3:
    call_log.status = 'FAILED'
    call_log.error_message = 'Max retry attempts reached (3)'
```

---

## 📊 Database State Timeline

```sql
-- T+0s: Initial creation
call_id: "call_3_+918840265502_1761367864_df2201b3"
status: "INITIATED"
attempt_count: 1
external_call_id: NULL

-- T+1s: Consumer processing
status: "PROCESSING"

-- T+2s: External service called
external_call_id: "ext_abc123"
status: "INITIATED"

-- T+10s: Callback received
status: "COMPLETED" (if PICKED)
  OR
status: "DISCONNECTED" (if failed, will retry)
total_call_time: 45

-- T+60s: If DISCONNECTED, scheduler retries
status: "RETRYING"
attempt_count: 2
```

---

## ⏱️ Timing Breakdown

| Phase | Duration | Type |
|-------|----------|------|
| API Request → Response | 50-200ms | Synchronous |
| Consumer picks up event | 100-500ms | Async |
| External service call | 100-300ms | HTTP |
| Mock simulation delay | 1-10 seconds | Random |
| Callback webhook | 50-200ms | HTTP |
| **Total End-to-End** | **2-15 seconds** | Complete flow |

---

## 📁 Key Files Reference

| Component | File | Line Range |
|-----------|------|------------|
| Authentication | `calls/middleware.py` | 50-100 |
| API View | `calls/views.py` | 30-85 |
| Kafka Publisher | `calls/publisher.py` | 68-90 |
| Consumer | `calls/consumer.py` | 88-202 |
| Mock Service | `mock_service.py` | 123-167 |
| Callback View | `calls/views.py` | 90-160 |
| Retry Scheduler | `calls/scheduler.py` | 127-209 |

---

## 🔍 How to Monitor

```bash
# View all activity
tail -f logs/app.log

# API requests only
tail -f logs/api.log | grep "Incoming Request"

# Kafka events
tail -f logs/kafka.log | grep "Processing"

# Call operations
tail -f logs/calls.log

# Check database
psql -h localhost -U campaign_user -d campaign_db \
  -c "SELECT call_id, status, attempt_count FROM calls_calllog ORDER BY created_at DESC LIMIT 5;"

# Check Redis
redis-cli GET active_calls_count
```

---

## 🎯 Key Takeaways

1. **API Response is Immediate** - Client gets `call_id` in ~100ms
2. **Processing is Async** - Actual call happens via Kafka consumer
3. **External Service is Separate** - Mock service on port 8001
4. **Callbacks are Webhooks** - External service calls back with results
5. **Retry is Automatic** - Scheduler handles failures
6. **Everything is Logged** - Track complete flow in logs

---

**End of Document**
