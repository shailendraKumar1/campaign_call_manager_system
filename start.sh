#!/bin/bash

# Campaign Call Manager System - Startup Script
# This script helps you get the system running quickly

set -e

echo "🚀 Starting Campaign Call Manager System..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create logs directory
mkdir -p logs

# Start services
echo "📦 Starting all services with Docker Compose..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 30

# Check service health
echo "🔍 Checking service health..."

# Check if PostgreSQL is ready
echo "  - Checking PostgreSQL..."
docker-compose exec -T postgres pg_isready -U campaign_user -d campaign_db || {
    echo "❌ PostgreSQL is not ready"
    exit 1
}

# Check if Redis is ready
echo "  - Checking Redis..."
docker-compose exec -T redis redis-cli ping || {
    echo "❌ Redis is not ready"
    exit 1
}

# Check if Kafka is ready
echo "  - Checking Kafka..."
docker-compose exec -T kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null || {
    echo "❌ Kafka is not ready"
    exit 1
}

# Run database migrations
echo "🗄️  Running database migrations..."
docker-compose exec -T web python manage.py migrate

# Create Kafka topics (if they don't exist)
echo "📡 Creating Kafka topics..."
docker-compose exec -T kafka kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists --topic initiated_call_topic --partitions 3 --replication-factor 1
docker-compose exec -T kafka kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists --topic callback_topic --partitions 3 --replication-factor 1
docker-compose exec -T kafka kafka-topics --bootstrap-server localhost:9092 --create --if-not-exists --topic dlq_topic --partitions 1 --replication-factor 1

# Check if services are responding
echo "🌐 Checking API endpoints..."
sleep 10

# Check main API
if curl -s http://localhost:8000/api/v1/metrics/ > /dev/null; then
    echo "  ✅ Main API is responding"
else
    echo "  ❌ Main API is not responding"
fi

# Check mock service
if curl -s http://localhost:8001/health > /dev/null; then
    echo "  ✅ Mock service is responding"
else
    echo "  ❌ Mock service is not responding"
fi

echo ""
echo "🎉 System is ready!"
echo ""
echo "📋 Service URLs:"
echo "  - Main API: http://localhost:8000"
echo "  - API Documentation: http://localhost:8000/api/v1/"
echo "  - Admin Interface: http://localhost:8000/admin"
echo "  - Mock Service: http://localhost:8001"
echo "  - Metrics: http://localhost:8000/api/v1/metrics/"
echo ""
echo "🔧 Useful commands:"
echo "  - View logs: docker-compose logs -f [service-name]"
echo "  - Stop system: docker-compose down"
echo "  - Restart service: docker-compose restart [service-name]"
echo "  - Shell access: docker-compose exec web python manage.py shell"
echo ""
echo "📊 To create a test campaign and make a call:"
echo "  1. Create campaign: curl -X POST http://localhost:8000/api/v1/campaigns/ -H 'Content-Type: application/json' -d '{\"name\":\"Test Campaign\"}'"
echo "  2. Add phone numbers: curl -X POST http://localhost:8000/api/v1/phone-numbers/ -H 'Content-Type: application/json' -d '{\"campaign_id\":1,\"phone_numbers\":[\"+1234567890\"]}'"
echo "  3. Initiate call: curl -X POST http://localhost:8000/api/v1/initiate-call/ -H 'Content-Type: application/json' -d '{\"phone_number\":\"+1234567890\",\"campaign_id\":1}'"
echo ""
echo "Happy calling! 📞"
