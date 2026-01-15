#!/bin/bash
#
# ShowNotes Automated Setup Script
# This script automates the initial setup process for ShowNotes
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Emoji support check
if locale -a | grep -qi 'utf-8\|utf8'; then
    EMOJI_SUPPORT=true
else
    EMOJI_SUPPORT=false
fi

print_header() {
    echo ""
    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}                    ShowNotes Setup Script${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo ""
}

print_success() {
    if [ "$EMOJI_SUPPORT" = true ]; then
        echo -e "${GREEN}✅ $1${NC}"
    else
        echo -e "${GREEN}[OK] $1${NC}"
    fi
}

print_error() {
    if [ "$EMOJI_SUPPORT" = true ]; then
        echo -e "${RED}❌ $1${NC}"
    else
        echo -e "${RED}[ERROR] $1${NC}"
    fi
}

print_warning() {
    if [ "$EMOJI_SUPPORT" = true ]; then
        echo -e "${YELLOW}⚠️  $1${NC}"
    else
        echo -e "${YELLOW}[WARNING] $1${NC}"
    fi
}

print_info() {
    if [ "$EMOJI_SUPPORT" = true ]; then
        echo -e "${BLUE}ℹ️  $1${NC}"
    else
        echo -e "${BLUE}[INFO] $1${NC}"
    fi
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        print_error "$1 is required but not installed"
        return 1
    else
        print_success "$1 found: $(command -v $1)"
        return 0
    fi
}

print_header

# Check for required dependencies
echo "Checking system requirements..."
echo ""

REQUIREMENTS_MET=true

if ! check_command "python3"; then
    REQUIREMENTS_MET=false
    print_info "Install Python 3.8+: https://www.python.org/downloads/"
fi

# Check Python version
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        print_warning "Python $PYTHON_VERSION detected. Python 3.8+ is recommended."
    else
        print_success "Python version $PYTHON_VERSION (sufficient)"
    fi
fi

if ! check_command "pip" && ! check_command "pip3"; then
    REQUIREMENTS_MET=false
    print_info "pip is usually included with Python"
fi

# Node.js is optional (for Tailwind rebuild)
if check_command "node"; then
    NODE_VERSION=$(node --version)
    print_info "Node.js version: $NODE_VERSION (optional, for Tailwind CSS)"
else
    print_warning "Node.js not found (optional - Tailwind CSS already built)"
fi

echo ""

if [ "$REQUIREMENTS_MET" = false ]; then
    print_error "Missing required dependencies. Please install them and try again."
    exit 1
fi

print_success "All required dependencies found!"
echo ""

# Create virtual environment
echo "Setting up Python virtual environment..."
if [ -d ".venv" ]; then
    print_warning "Virtual environment already exists. Skipping creation."
else
    python3 -m venv .venv
    if [ $? -eq 0 ]; then
        print_success "Virtual environment created"
    else
        print_error "Failed to create virtual environment"
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate
if [ $? -eq 0 ]; then
    print_success "Virtual environment activated"
else
    print_error "Failed to activate virtual environment"
    exit 1
fi

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q
print_success "pip upgraded"

# Install Python dependencies
echo "Installing Python dependencies (this may take a minute)..."
pip install -r requirements.txt -q
if [ $? -eq 0 ]; then
    print_success "Python dependencies installed"
else
    print_error "Failed to install Python dependencies"
    exit 1
fi

# Setup .env file
echo "Setting up environment configuration..."
if [ -f ".env" ]; then
    print_warning ".env file already exists. Skipping creation."
    print_info "Review your .env file to ensure settings are correct"
else
    cp .env.example .env
    if [ $? -eq 0 ]; then
        print_success ".env file created from template"
        print_warning "Please edit .env with your Plex settings before running the app"
    else
        print_error "Failed to create .env file"
        exit 1
    fi
fi

# Initialize database
echo "Initializing database..."
if [ -f "instance/shownotes.sqlite3" ]; then
    print_warning "Database already exists. Skipping initialization."
    print_info "To reset database, run: python3 scripts/reset_database.py"
else
    FLASK_APP=run.py .venv/bin/flask init-db > /tmp/db_init.log 2>&1
    if [ $? -eq 0 ]; then
        print_success "Database initialized"
    else
        print_warning "Database initialization completed with warnings (this is normal for fresh install)"
        print_info "Check /tmp/db_init.log if you encounter issues"
    fi
fi

# Build Tailwind CSS if needed
if [ -f "app/static/css/style.css" ]; then
    print_success "Tailwind CSS already built"
else
    if command -v npx &> /dev/null; then
        echo "Building Tailwind CSS..."
        npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify
        if [ $? -eq 0 ]; then
            print_success "Tailwind CSS built"
        else
            print_error "Failed to build Tailwind CSS"
        fi
    else
        print_warning "npx not found. Skipping Tailwind CSS build."
        print_info "Tailwind CSS can be built later with: npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css"
    fi
fi

# Create necessary directories
echo "Creating required directories..."
mkdir -p logs
mkdir -p instance
mkdir -p app/static/poster
mkdir -p app/static/background
print_success "Directories created"

# Setup complete
echo ""
echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}                    Setup Complete! 🎉${NC}"
echo -e "${GREEN}======================================================================${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo ""
echo "1. Edit your .env file with Plex settings:"
echo -e "   ${YELLOW}nano .env${NC}  # or use your preferred editor"
echo ""
echo "2. Start the application:"
echo -e "   ${YELLOW}source .venv/bin/activate${NC}"
echo -e "   ${YELLOW}python3 run.py${NC}"
echo ""
echo "3. Access ShowNotes in your browser:"
echo -e "   ${BLUE}http://localhost:5001${NC}"
echo ""
echo "4. Configure services in the admin panel:"
echo -e "   ${BLUE}http://localhost:5001/admin/settings${NC}"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo "  • Quick Start: QUICKSTART.md"
echo "  • Setup Guide: SETUP.md"
echo "  • Features: README.md"
echo ""
echo -e "${GREEN}Happy watching! 🎬${NC}"
echo ""
