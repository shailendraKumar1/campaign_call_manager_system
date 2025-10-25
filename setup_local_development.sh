#!/bin/bash

# Campaign Call Manager System - Local Development Setup Script
# This script sets up all required services for local development

set -e

echo "🚀 Setting up Campaign Call Manager System for Local Development"
echo "================================================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    print_error "This script is designed for macOS. Please adapt for your OS."
    exit 1
fi

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    print_error "Homebrew is not installed. Please install it first:"
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

print_status "Homebrew found"

# Update Homebrew
print_info "Updating Homebrew..."
brew update

# Install PostgreSQL
print_info "Installing PostgreSQL..."
if brew list postgresql &> /dev/null; then
    print_status "PostgreSQL already installed"
else
    brew install postgresql
fi

# Start PostgreSQL service
print_info "Starting PostgreSQL service..."
brew services start postgresql

# Wait for PostgreSQL to start
sleep 3

# Create database and user
print_info "Setting up database..."
psql postgres -c "CREATE DATABASE campaign_db;" 2>/dev/null || print_warning "Database campaign_db already exists"
psql postgres -c "CREATE USER campaign_user WITH PASSWORD 'yourpassword';" 2>/dev/null || print_warning "User campaign_user already exists"
psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE campaign_db TO campaign_user;" 2>/dev/null || true

print_status "PostgreSQL setup complete"

# Install Redis
print_info "Installing Redis..."
if brew list redis &> /dev/null; then
    print_status "Redis already installed"
else
    brew install redis
fi

# Start Redis service
print_info "Starting Redis service..."
brew services start redis

# Test Redis connection
sleep 2
if redis-cli ping &> /dev/null; then
    print_status "Redis setup complete"
else
    print_error "Redis connection failed"
    exit 1
fi

# Install Kafka
print_info "Installing Apache Kafka..."
if brew list kafka &> /dev/null; then
    print_status "Kafka already installed"
else
    brew install kafka
fi

# Start Zookeeper and Kafka
print_info "Starting Zookeeper..."
brew services start zookeeper

print_info "Starting Kafka..."
brew services start kafka

# Wait for Kafka to start
print_info "Waiting for Kafka to start (30 seconds)..."
sleep 30

# Create Kafka topics
print_info "Creating Kafka topics..."
kafka-topics --create --topic initiated_call_topic --bootstrap-server localhost:9092 --partitions 3 --replication-factor 1 2>/dev/null || print_warning "Topic initiated_call_topic already exists"
kafka-topics --create --topic callback_topic --bootstrap-server localhost:9092 --partitions 3 --replication-factor 1 2>/dev/null || print_warning "Topic callback_topic already exists"
kafka-topics --create --topic dlq_topic --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1 2>/dev/null || print_warning "Topic dlq_topic already exists"

print_status "Kafka setup complete"

# Install Python if needed
print_info "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    if [[ $(echo "$PYTHON_VERSION >= 3.8" | bc -l) -eq 1 ]]; then
        print_status "Python $PYTHON_VERSION found"
    else
        print_warning "Python version is $PYTHON_VERSION. Recommend 3.8+"
    fi
else
    print_info "Installing Python..."
    brew install python@3.11
fi

# Verify all services are running
print_info "Verifying services..."

# Check PostgreSQL
if pg_isready -h localhost -p 5432 &> /dev/null; then
    print_status "PostgreSQL is running"
else
    print_error "PostgreSQL is not running"
fi

# Check Redis
if redis-cli ping &> /dev/null; then
    print_status "Redis is running"
else
    print_error "Redis is not running"
fi

# Check Kafka
if kafka-topics --list --bootstrap-server localhost:9092 &> /dev/null; then
    print_status "Kafka is running"
else
    print_error "Kafka is not running"
fi

echo ""
echo "================================================================"
print_status "Local Development Environment Setup Complete!"
echo "================================================================"
echo ""
echo "📋 Services Status:"
echo "  • PostgreSQL: Running on port 5432"
echo "  • Redis: Running on port 6379"
echo "  • Kafka: Running on port 9092"
echo "  • Zookeeper: Running on port 2181"
echo ""
echo "🔧 Next Steps:"
echo "  1. Open PyCharm and load the project"
echo "  2. Create virtual environment in PyCharm"
echo "  3. Install Python dependencies: pip install -r requirements.txt"
echo "  4. Copy .env.example to .env and configure"
echo "  5. Run migrations: python manage.py migrate"
echo "  6. Start the Django server: python manage.py runserver"
echo ""
echo "📚 Useful Commands:"
echo "  • Stop all services: brew services stop postgresql redis kafka zookeeper"
echo "  • Start all services: brew services start postgresql redis kafka zookeeper"
echo "  • View Kafka topics: kafka-topics --list --bootstrap-server localhost:9092"
echo "  • Connect to database: psql -h localhost -U campaign_user -d campaign_db"
echo "  • Test Redis: redis-cli ping"
echo ""
print_status "Ready for development! 🎉"
