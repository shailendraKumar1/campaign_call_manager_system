#!/usr/bin/env python3
"""
Mock External Call Service

This is a standalone Flask service that simulates an external call initiation service.
It provides endpoints for initiating calls and simulates callback events.

Usage:
    python mock_service.py

The service will run on http://localhost:8001 by default.
"""

import os
import sys
import django

# Setup Django environment for Celery task access
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'campaign_call_manager_system.settings')
django.setup()

import json
import logging
import random
import threading
import time
import uuid
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify
import httpx
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory storage for active calls
active_calls = {}

# Configuration
CALLBACK_URL = "http://localhost:8000/api/v1/callback/"
MOCK_SERVICE_PORT = 8001

# Call simulation settings - loaded from config.py
# You can change probabilities in config.py to test retry logic
CALL_OUTCOMES = Config.MOCK_CALL_OUTCOMES
CALL_DELAY_MIN = Config.MOCK_CALL_DELAY_MIN
CALL_DELAY_MAX = Config.MOCK_CALL_DELAY_MAX


class CallSimulator:
    """Simulates call behavior and sends callbacks"""
    
    @staticmethod
    def simulate_call(call_data):
        """Simulate a call and send callback after random delay"""
        call_id = call_data['call_id']
        phone_number = call_data['phone_number']
        
        try:
            # Random delay before call outcome (configurable)
            delay = random.uniform(CALL_DELAY_MIN, CALL_DELAY_MAX)
            logger.info(
                f"[Mock Service] Simulating call | "
                f"call_id={call_id}, phone={phone_number}, wait={delay:.1f}s"
            )
            time.sleep(delay)
            
            # Determine call outcome based on probabilities
            rand = random.random()
            cumulative_prob = 0
            
            for outcome, probability, duration_range in CALL_OUTCOMES:
                cumulative_prob += probability
                if rand <= cumulative_prob:
                    status = outcome
                    duration = random.randint(*duration_range)
                    break
            else:
                # Fallback
                status = 'FAILED'
                duration = 0
            
            # Send callback
            callback_data = {
                'call_id': call_id,
                'status': status,
                'call_duration': duration,
                'external_call_id': active_calls.get(call_id, {}).get('external_call_id'),
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info(
                f"[STEP 7] Callback Generated | "
                f"call_id={call_id}, status={status}, duration={duration}s, url={CALLBACK_URL}"
            )
            
            # Send callback to main service
            try:
                CallSimulator.send_callback(callback_data, call_id)
            except Exception as e:
                logger.error(f"Error sending callback for {call_id}: {str(e)}")
            
            # Remove from active calls
            if call_id in active_calls:
                del active_calls[call_id]
                
        except Exception as e:
            logger.error(f"Error simulating call {call_id}: {str(e)}")
    
    @staticmethod
    def send_callback(callback_data, call_id):
        """
        Queue callback task to Celery instead of calling API directly
        
        Benefits:
        - Decouples mock service from main API
        - Better scalability - callbacks processed by Celery workers
        - Automatic retry logic
        - Prevents callback API overload
        """
        try:
            # Import Celery task dynamically to avoid circular imports
            from calls.tasks import process_external_callback
            
            logger.info(f"[STEP 7] Queueing callback task | call_id={call_id}, status={callback_data.get('status')}")
            
            # Queue task to Celery (Redis)
            task = process_external_callback.delay(callback_data)
            
            logger.info(f"✅ Callback task queued: {call_id} (task_id: {task.id})")
            
        except Exception as e:
            # Fallback to direct HTTP call if Celery queueing fails
            logger.error(f"Failed to queue callback task for {call_id}: {str(e)}")
            logger.info(f"Falling back to direct HTTP callback for {call_id}")
            
            try:
                with httpx.Client(timeout=10.0, verify=False, http2=False) as client:
                    response = client.put(
                        CALLBACK_URL,
                        json=callback_data,
                        headers={
                            'X-Auth-Token': Config.X_AUTH_TOKEN,
                            'Content-Type': 'application/json'
                        }
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ Direct callback sent successfully: {call_id}")
                    else:
                        logger.error(f"❌ Direct callback failed: {call_id} (status: {response.status_code})")
                        
            except httpx.RequestError as http_error:
                logger.error(f"Direct callback HTTP error for {call_id}: {str(http_error)}")


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'mock-call-service',
        'active_calls': len(active_calls),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/initiate-call', methods=['POST'])
def initiate_call():
    """Initiate a call (mock implementation)"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['call_id', 'phone_number', 'campaign_id']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        call_id = data['call_id']
        phone_number = data['phone_number']
        campaign_id = data['campaign_id']
        
        # Generate external call ID
        external_call_id = f"ext_{uuid.uuid4().hex[:8]}"
        
        # Store call information
        active_calls[call_id] = {
            'external_call_id': external_call_id,
            'phone_number': phone_number,
            'campaign_id': campaign_id,
            'initiated_at': datetime.now().isoformat(),
            'status': 'initiated'
        }
        
        # Start call simulation in background thread
        thread = threading.Thread(
            target=CallSimulator.simulate_call,
            args=(data,)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Call initiated: {call_id} -> {external_call_id} ({phone_number})")
        
        return jsonify({
            'success': True,
            'external_call_id': external_call_id,
            'call_id': call_id,
            'status': 'initiated',
            'message': 'Call initiated successfully'
        }), 200
        
    except Exception as e:
        logger.error(f"Error initiating call: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/active-calls', methods=['GET'])
def get_active_calls():
    """Get list of currently active calls"""
    return jsonify({
        'active_calls': active_calls,
        'count': len(active_calls)
    })


@app.route('/api/simulate-callback', methods=['POST'])
def simulate_callback():
    """Manually trigger a callback for testing"""
    try:
        data = request.get_json()
        call_id = data.get('call_id')
        status = data.get('status', 'PICKED')
        
        if not call_id:
            return jsonify({'error': 'call_id is required'}), 400
        
        if call_id not in active_calls:
            return jsonify({'error': 'Call not found'}), 404
        
        # Send immediate callback
        callback_data = {
            'call_id': call_id,
            'status': status,
            'call_duration': random.randint(10, 120),
            'external_call_id': active_calls[call_id]['external_call_id'],
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            response = requests.put(
                CALLBACK_URL,
                json=callback_data,
                timeout=10
            )
            
            # Remove from active calls
            del active_calls[call_id]
            
            return jsonify({
                'success': True,
                'callback_sent': True,
                'callback_response_status': response.status_code
            })
            
        except requests.exceptions.RequestException as e:
            return jsonify({
                'success': False,
                'error': f'Failed to send callback: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Error simulating callback: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get service statistics"""
    return jsonify({
        'service': 'mock-call-service',
        'active_calls': len(active_calls),
        'call_outcomes': {
            outcome: f"{probability*100}%" 
            for outcome, probability, _ in CALL_OUTCOMES
        },
        'callback_url': CALLBACK_URL,
        'uptime': 'N/A'  # Could implement actual uptime tracking
    })


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    logger.info(f"Starting Mock Call Service on port {MOCK_SERVICE_PORT}")
    logger.info(f"Callback URL: {CALLBACK_URL}")
    logger.info("Available endpoints:")
    logger.info("  GET  /health - Health check")
    logger.info("  POST /api/initiate-call - Initiate a call")
    logger.info("  GET  /api/active-calls - List active calls")
    logger.info("  POST /api/simulate-callback - Manually trigger callback")
    logger.info("  GET  /api/stats - Service statistics")
    
    app.run(
        host='0.0.0.0',
        port=MOCK_SERVICE_PORT,
        debug=False,
        threaded=True
    )
