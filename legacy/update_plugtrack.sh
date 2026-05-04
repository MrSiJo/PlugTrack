#!/bin/bash

# PlugTrack Update Script
# This script backs up the existing PlugTrack installation, 
# copies new files from /sijoupload/plugtrack, and cleans up after successful deployment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if services are running
check_services() {
    local web_status=$(systemctl is-active PlugTrack-Web 2>/dev/null || echo "inactive")
    
    if [[ "$web_status" == "active" ]]; then
        return 0
    else
        return 1
    fi
}

# Function to backup database before update
backup_database() {
    local backup_dir="/opt/plugtrack/backups"
    local db_path="/opt/plugtrack/instance/plugtrack.db"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    
    if [ -f "$db_path" ]; then
        mkdir -p "$backup_dir"
        cp "$db_path" "$backup_dir/plugtrack_pre_update_$timestamp.db"
        print_success "Database backed up to $backup_dir/plugtrack_pre_update_$timestamp.db"
        return 0
    else
        print_warning "Database file not found at $db_path - skipping backup"
        return 1
    fi
}

# Function to run database migrations
run_migrations() {
    print_status "Running database migrations..."
    cd /opt/plugtrack
    
    # Set environment variables
    export PYTHONPATH="/opt/plugtrack:${PYTHONPATH}"
    export FLASK_APP=run_app.py
    export FLASK_ENV=production
    
    # Run migrations
    /opt/plugtrack/venv/bin/python3 -m flask init-db
    
    if [ $? -eq 0 ]; then
        print_success "Database migrations completed successfully"
        return 0
    else
        print_error "Database migrations failed"
        return 1
    fi
}

# Main script execution
main() {
    print_status "Starting PlugTrack update process..."
    
    # Check if source directory exists
    if [[ ! -d "/sijoupload/plugtrack" ]]; then
        print_error "Source directory /sijoupload/plugtrack does not exist!"
        exit 1
    fi
    
    # Check if target directory exists
    if [[ ! -d "/opt/plugtrack" ]]; then
        print_error "Target directory /opt/plugtrack does not exist!"
        exit 1
    fi
    
    # Step 1: Stop services
    print_status "Stopping PlugTrack services..."
    sudo systemctl stop PlugTrack-Web || {
        print_warning "Service may not have been running"
    }
    
    # Step 2: Backup database
    print_status "Backing up database..."
    backup_database
    
    # Step 3: Move existing backups to /sijoupload
    print_status "Checking for existing backups..."
    local existing_backups=$(find /opt -maxdepth 1 -name "plugtrack.backup.*" -type d 2>/dev/null || true)
    if [[ -n "$existing_backups" ]]; then
        print_status "Moving existing backups to /sijoupload..."
        for backup in $existing_backups; do
            local backup_name=$(basename "$backup")
            sudo mv "$backup" "/sijoupload/$backup_name"
            print_status "Moved $backup_name to /sijoupload/"
        done
        print_success "Existing backups moved to /sijoupload"
    else
        print_status "No existing backups found"
    fi
    
    # Step 4: Create new backup in /sijoupload
    local backup_name="/sijoupload/plugtrack.backup.$(date +%Y%m%d_%H%M%S)"
    print_status "Creating backup at $backup_name..."
    sudo cp -r /opt/plugtrack "$backup_name"
    print_success "Backup created successfully"
    
    # Step 5: Copy new files (excluding __pycache__ directories)
    print_status "Copying files from /sijoupload/plugtrack to /opt/plugtrack..."
    sudo rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' /sijoupload/plugtrack/ /opt/plugtrack/
    print_success "Files copied successfully"
    
    # Step 6: Set ownership and permissions
    print_status "Setting ownership and permissions..."
    sudo chown -R PlugTrack:PlugTrack /opt/plugtrack
    sudo chmod -R 755 /opt/plugtrack
    sudo chmod 644 /opt/plugtrack/.env
    print_success "Ownership and permissions set"
    
    # Step 7: Run database migrations
    print_status "Running database migrations..."
    if run_migrations; then
        print_success "Database migrations completed"
    else
        print_error "Database migrations failed - rolling back"
        sudo rm -rf /opt/plugtrack
        sudo mv "$backup_name" /opt/plugtrack
        print_warning "Rolled back to previous version"
        exit 1
    fi
    
    # Step 8: Start services
    print_status "Starting PlugTrack services..."
    sudo systemctl start PlugTrack-Web
    
    # Step 9: Wait a moment for services to initialize
    print_status "Waiting for services to initialize..."
    sleep 5
    
    # Step 10: Verify services are running
    print_status "Verifying services are running..."
    if check_services; then
        print_success "Service is running successfully!"
        
        # Step 11: Cleanup source directory
        print_status "Cleaning up source directory /sijoupload/plugtrack..."
        sudo rm -rf /sijoupload/plugtrack
        print_success "Source directory cleaned up"
        
        print_success "PlugTrack update completed successfully!"
        print_status "Backup location: $backup_name"
        print_status "Database backup location: /opt/plugtrack/backups/"
        
    else
        print_error "Service failed to start properly!"
        print_warning "Backup is available at: $backup_name"
        print_warning "Source directory preserved at: /sijoupload/plugtrack"
        
        # Show service status for debugging
        echo ""
        print_status "Service status:"
        sudo systemctl status PlugTrack-Web --no-pager -l
        
        exit 1
    fi
}

# Run main function
main "$@"
