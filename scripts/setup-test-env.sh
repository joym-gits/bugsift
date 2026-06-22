#!/bin/bash
# Quick setup script for test environment with dashboard

set -e

echo "🧪 BugSift Test Environment Setup"
echo "=================================="

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo -e "${BLUE}Checking Python version...${NC}"
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "✓ Python $python_version"

# Check Node version
echo -e "${BLUE}Checking Node.js version...${NC}"
node_version=$(node --version)
echo "✓ Node $node_version"

# Setup backend
echo -e "${BLUE}Setting up backend...${NC}"
cd backend

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
    source venv/bin/activate
fi

# Install dependencies
echo "Installing backend dependencies..."
pip install --upgrade pip
pip install -e ".[dev]"
pip install pytest-html pytest-json-report playwright

# Create test directories
mkdir -p test-results

# Setup frontend
echo -e "${BLUE}Setting up frontend...${NC}"
cd ../frontend

if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm ci
else
    echo "✓ Frontend dependencies already installed"
fi

# Install Playwright browsers
echo -e "${BLUE}Installing Playwright browsers...${NC}"
cd ../backend
playwright install --with-deps

# Test database connectivity
echo -e "${BLUE}Checking database connectivity...${NC}"
if command -v psql &> /dev/null; then
    echo "✓ PostgreSQL client available"
else
    echo "${YELLOW}⚠ PostgreSQL client not found (optional for local testing)${NC}"
fi

# Create .env if doesn't exist
if [ ! -f ".env" ]; then
    echo -e "${BLUE}Creating .env file...${NC}"
    cat > .env << EOF
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/bugsift_test
POSTGRES_HOST=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# Redis
REDIS_URL=redis://localhost:6379/0

# Testing
TESTING=true

# GitHub
GITHUB_CLIENT_ID=test
GITHUB_CLIENT_SECRET=test
GITHUB_WEBHOOK_SECRET=test

# OpenAI
OPENAI_API_KEY=sk-test-key

# Anthropic
ANTHROPIC_API_KEY=test-key

# Encryption
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
EOF
    echo "✓ .env file created"
else
    echo "✓ .env file already exists"
fi

# Summary
echo ""
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Start PostgreSQL and Redis:"
echo "   docker-compose up postgres redis -d"
echo ""
echo "2. Run tests with dashboard:"
echo "   pytest tests/ -v"
echo ""
echo "3. View dashboard:"
echo "   open test-results/index.html"
echo ""
echo "4. For E2E tests:"
echo "   pytest tests/test_e2e_workflows.py -v"
echo ""
echo "Documentation:"
echo "  📖 TEST_DASHBOARD_GUIDE.md - Complete guide"
echo "  📖 tests/README.md - Quick reference"
echo "  📖 TESTING_GUIDE.md - Testing best practices"
