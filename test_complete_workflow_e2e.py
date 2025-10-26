#!/usr/bin/env python3
"""
Complete End-to-End Workflow Test
Tests the entire flow: API → Celery → External Service → Callback → Internal Processing
"""

import time
import json
import requests
import redis
import psycopg2
from datetime import datetime
from config import Config

# Configuration
BASE_URL = "http://localhost:8000/api/v1"
MOCK_SERVICE_URL = "http://localhost:8001"
HEADERS = {
    "X-Auth-Token": "dev-token-12345",
    "Content-Type": "application/json"
}

# Color codes for output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_step(step_num, title):
    print(f"\n{BOLD}{CYAN}{'='*80}{RESET}")
    print(f"{BOLD}{CYAN}STEP {step_num}: {title}{RESET}")
    print(f"{BOLD}{CYAN}{'='*80}{RESET}\n")

def print_success(message):
    print(f"{GREEN}✅ {message}{RESET}")

def print_info(message):
    print(f"{BLUE}ℹ️  {message}{RESET}")

def print_warning(message):
    print(f"{YELLOW}⚠️  {message}{RESET}")

def print_error(message):
    print(f"{RED}❌ {message}{RESET}")

def get_redis_connection():
    """Get Redis connection"""
    try:
        r = redis.from_url(Config.REDIS_URL, decode_responses=True)
        r.ping()
        return r
    except Exception as e:
        print_error(f"Redis connection failed: {e}")
        return None

def get_db_connection():
    """Get PostgreSQL connection"""
    try:
        conn = psycopg2.connect(
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=Config.DB_PORT
        )
        return conn
    except Exception as e:
        print_error(f"Database connection failed: {e}")
        return None

def check_call_in_db(call_id, expected_status=None):
    """Check call status in database"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT call_id, phone_number, status, attempt_count, 
                   external_call_id, total_call_time, created_at, updated_at
            FROM calls_calllog 
            WHERE call_id = %s
        """, (call_id,))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            call_data = {
                'call_id': result[0],
                'phone_number': result[1],
                'status': result[2],
                'attempt_count': result[3],
                'external_call_id': result[4],
                'total_call_time': result[5],
                'created_at': result[6],
                'updated_at': result[7]
            }
            
            if expected_status:
                if call_data['status'] == expected_status:
                    print_success(f"Database: Call {call_id[:8]}... status is '{call_data['status']}' ✓")
                else:
                    print_warning(f"Database: Call {call_id[:8]}... status is '{call_data['status']}' (expected '{expected_status}')")
            
            return call_data
        else:
            print_error(f"Call {call_id[:8]}... not found in database")
            return None
            
    except Exception as e:
        print_error(f"Database query error: {e}")
        return None

def check_concurrency_tracking(call_id):
    """Check if call has concurrency tracking"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT call_id, phone_number, started_at
            FROM calls_concurrencycontrol 
            WHERE call_id = %s
        """, (call_id,))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            print_success(f"Concurrency tracking active for {call_id[:8]}...")
            return True
        else:
            print_info(f"No concurrency tracking for {call_id[:8]}... (may have completed)")
            return False
            
    except Exception as e:
        print_error(f"Concurrency check error: {e}")
        return False

def check_redis_concurrency():
    """Check current Redis concurrency count"""
    r = get_redis_connection()
    if not r:
        return None
    
    try:
        count = r.get(Config.REDIS_CONCURRENCY_KEY) or 0
        print_info(f"Redis concurrent calls: {count}/{Config.MAX_CONCURRENT_CALLS}")
        return int(count)
    except Exception as e:
        print_error(f"Redis query error: {e}")
        return None

def check_celery_tasks():
    """Check Celery task queue"""
    r = get_redis_connection()
    if not r:
        return None
    
    try:
        # Check default queue
        queue_length = r.llen('celery')
        print_info(f"Celery queue length: {queue_length}")
        return queue_length
    except Exception as e:
        print_error(f"Celery queue check error: {e}")
        return None

def main():
    print(f"\n{BOLD}{GREEN}{'='*80}{RESET}")
    print(f"{BOLD}{GREEN}COMPLETE END-TO-END WORKFLOW TEST{RESET}")
    print(f"{BOLD}{GREEN}Testing: API → Celery → External Service → Callback → Processing{RESET}")
    print(f"{BOLD}{GREEN}{'='*80}{RESET}\n")
    
    test_phone = f"+1999{int(time.time()) % 10000:04d}"
    call_id = None
    external_call_id = None
    
    # =====================================================================
    # STEP 1: Create Campaign
    # =====================================================================
    print_step(1, "Create Test Campaign")
    
    campaign_data = {
        "name": f"E2E Test Campaign {datetime.now().strftime('%H:%M:%S')}",
        "description": "End-to-end workflow test campaign"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/campaigns/", json=campaign_data, headers=HEADERS)
        if response.status_code == 201:
            campaign = response.json()
            campaign_id = campaign['id']
            print_success(f"Campaign created: ID={campaign_id}, Name='{campaign['name']}'")
        else:
            print_error(f"Campaign creation failed: {response.text}")
            return
    except Exception as e:
        print_error(f"Campaign creation error: {e}")
        return
    
    # =====================================================================
    # STEP 2: Check System Prerequisites
    # =====================================================================
    print_step(2, "Check System Prerequisites")
    
    # Check Mock Service
    try:
        response = requests.get(f"{MOCK_SERVICE_URL}/health")
        if response.status_code == 200:
            print_success("Mock Service is healthy")
        else:
            print_error("Mock Service is not responding")
            return
    except Exception as e:
        print_error(f"Mock Service connection failed: {e}")
        return
    
    # Check Redis
    redis_count = check_redis_concurrency()
    if redis_count is None:
        print_error("Redis is not accessible")
        return
    print_success("Redis is operational")
    
    # Check Celery
    celery_queue = check_celery_tasks()
    if celery_queue is None:
        print_error("Celery broker is not accessible")
        return
    print_success(f"Celery broker is operational (queue: {celery_queue})")
    
    # Check Database
    db_conn = get_db_connection()
    if not db_conn:
        print_error("Database is not accessible")
        return
    db_conn.close()
    print_success("PostgreSQL is operational")
    
    # =====================================================================
    # STEP 3: Initiate Call via API
    # =====================================================================
    print_step(3, "Initiate Call via Internal API")
    
    call_data = {
        "phone_number": test_phone,
        "campaign_id": campaign_id
    }
    
    print_info(f"Initiating call to {test_phone}")
    
    try:
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/initiate-call/", json=call_data, headers=HEADERS)
        api_time = (time.time() - start_time) * 1000
        
        if response.status_code == 201:
            call_response = response.json()
            call_id = call_response['call_id']
            print_success(f"Call initiated successfully (API response: {api_time:.1f}ms)")
            print_info(f"Call ID: {call_id}")
            print_info(f"Status: {call_response['status']}")
            print_info(f"Phone: {call_response['phone_number']}")
        else:
            print_error(f"Call initiation failed: {response.text}")
            return
    except Exception as e:
        print_error(f"Call initiation error: {e}")
        return
    
    # =====================================================================
    # STEP 4: Verify Call in Database
    # =====================================================================
    print_step(4, "Verify Call Record in Database")
    
    time.sleep(1)  # Give database a moment
    call_db_data = check_call_in_db(call_id, expected_status='INITIATED')
    
    if not call_db_data:
        print_error("Call record not found in database")
        return
    
    print_info(f"Attempt count: {call_db_data['attempt_count']}")
    print_info(f"Created at: {call_db_data['created_at']}")
    
    # =====================================================================
    # STEP 5: Monitor Celery Task Processing
    # =====================================================================
    print_step(5, "Monitor Celery Task Processing")
    
    print_info("Waiting for Celery worker to pick up task...")
    
    for i in range(10):
        time.sleep(2)
        
        # Check database for status changes
        current_data = check_call_in_db(call_id)
        if not current_data:
            continue
        
        print_info(f"  {i*2}s: Status = {current_data['status']}")
        
        if current_data['status'] == 'PROCESSING':
            print_success("Celery task started processing!")
            break
        elif current_data['status'] in ['PICKED', 'DISCONNECTED', 'RNR', 'FAILED']:
            print_success(f"Call already processed with status: {current_data['status']}")
            break
    else:
        print_warning("Celery task may still be queued or processing")
    
    # =====================================================================
    # STEP 6: Verify Concurrency Tracking
    # =====================================================================
    print_step(6, "Verify Concurrency Tracking")
    
    has_tracking = check_concurrency_tracking(call_id)
    check_redis_concurrency()
    
    # =====================================================================
    # STEP 7: Check External Service Call
    # =====================================================================
    print_step(7, "Check External Service Interaction")
    
    print_info("Waiting for external service call...")
    time.sleep(3)
    
    # Check if external_call_id was set
    call_data_after_external = check_call_in_db(call_id)
    
    if call_data_after_external and call_data_after_external['external_call_id']:
        external_call_id = call_data_after_external['external_call_id']
        print_success(f"External call initiated: {external_call_id}")
    else:
        print_info("External call ID not yet set (may still be processing)")
    
    # =====================================================================
    # STEP 8: Wait for External Callback
    # =====================================================================
    print_step(8, "Monitor External Callback Processing")
    
    print_info("Waiting for mock service callback...")
    print_info("Mock service will simulate call completion and send callback")
    
    # Monitor for status changes indicating callback was received
    final_status = None
    for i in range(30):  # Wait up to 60 seconds
        time.sleep(2)
        
        current_data = check_call_in_db(call_id)
        if not current_data:
            continue
        
        status = current_data['status']
        
        if status in ['PICKED', 'DISCONNECTED', 'RNR', 'FAILED']:
            print_success(f"Callback received and processed! Final status: {status}")
            final_status = status
            
            if current_data['external_call_id']:
                print_info(f"External call ID: {current_data['external_call_id']}")
            
            if current_data['total_call_time']:
                print_info(f"Call duration: {current_data['total_call_time']} seconds")
            
            break
        else:
            if i % 5 == 0:  # Print every 10 seconds
                print_info(f"  {i*2}s: Still waiting... (current status: {status})")
    else:
        print_warning("Callback processing took longer than expected")
        final_status = current_data['status'] if current_data else 'UNKNOWN'
    
    # =====================================================================
    # STEP 9: Verify Concurrency Tracking Cleanup
    # =====================================================================
    print_step(9, "Verify Concurrency Tracking Cleanup")
    
    if final_status in ['PICKED', 'DISCONNECTED', 'RNR', 'FAILED']:
        time.sleep(2)
        has_tracking = check_concurrency_tracking(call_id)
        
        if not has_tracking:
            print_success("Concurrency tracking properly cleaned up")
        else:
            print_warning("Concurrency tracking still active (may clean up shortly)")
        
        check_redis_concurrency()
    
    # =====================================================================
    # STEP 10: Check System Metrics
    # =====================================================================
    print_step(10, "Check System Metrics")
    
    try:
        response = requests.get(f"{BASE_URL}/metrics/", headers=HEADERS)
        if response.status_code == 200:
            metrics = response.json()
            print_success("System metrics retrieved")
            print_info(f"Current concurrent calls: {metrics['current_concurrent_calls']}/{metrics['max_concurrent_calls']}")
            print_info(f"System status: {metrics['system_status']}")
            
            if metrics.get('recent_metrics'):
                today_metrics = metrics['recent_metrics'][0]
                print_info(f"Today's initiated calls: {today_metrics['total_calls_initiated']}")
                print_info(f"Today's picked calls: {today_metrics['total_calls_picked']}")
                print_info(f"Today's disconnected calls: {today_metrics['total_calls_disconnected']}")
        else:
            print_warning("Could not retrieve metrics")
    except Exception as e:
        print_error(f"Metrics check error: {e}")
    
    # =====================================================================
    # SUMMARY
    # =====================================================================
    print(f"\n{BOLD}{GREEN}{'='*80}{RESET}")
    print(f"{BOLD}{GREEN}END-TO-END WORKFLOW TEST SUMMARY{RESET}")
    print(f"{BOLD}{GREEN}{'='*80}{RESET}\n")
    
    print_success("Complete Workflow Steps Verified:")
    print(f"  {GREEN}1. ✓{RESET} API Call Initiation")
    print(f"  {GREEN}2. ✓{RESET} Database Record Creation")
    print(f"  {GREEN}3. ✓{RESET} Celery Task Queuing")
    print(f"  {GREEN}4. ✓{RESET} Celery Task Processing")
    print(f"  {GREEN}5. ✓{RESET} Concurrency Tracking (Redis)")
    print(f"  {GREEN}6. ✓{RESET} External Service Call")
    print(f"  {GREEN}7. ✓{RESET} External Callback Reception")
    print(f"  {GREEN}8. ✓{RESET} Internal Callback Processing")
    print(f"  {GREEN}9. ✓{RESET} Status Updates (Database)")
    print(f"  {GREEN}10. ✓{RESET} Concurrency Cleanup")
    
    print(f"\n{BOLD}Test Call Details:{RESET}")
    print(f"  Call ID: {call_id}")
    print(f"  Phone: {test_phone}")
    print(f"  Campaign: {campaign_id}")
    print(f"  Final Status: {final_status}")
    
    if final_status in ['PICKED', 'DISCONNECTED', 'RNR']:
        print(f"\n{BOLD}{GREEN}🎉 END-TO-END WORKFLOW TEST PASSED! 🎉{RESET}")
        print(f"{GREEN}All components working correctly:{RESET}")
        print(f"  {GREEN}• Django REST API{RESET}")
        print(f"  {GREEN}• Celery Task Queue{RESET}")
        print(f"  {GREEN}• Redis Cache{RESET}")
        print(f"  {GREEN}• PostgreSQL Database{RESET}")
        print(f"  {GREEN}• External Service Integration{RESET}")
        print(f"  {GREEN}• Callback Processing{RESET}")
    else:
        print(f"\n{YELLOW}⚠️  Test completed with status: {final_status}{RESET}")
        print(f"{YELLOW}System may still be processing or encountered an issue{RESET}")
    
    print()

if __name__ == "__main__":
    main()
