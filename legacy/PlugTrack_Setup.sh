#!/bin/bash

# This script is used to setup the PlugTrack EV Charging Session Manager on a Debian/Ubuntu LXC or VM.

# Exit on any error
set -e

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

echo "Starting PlugTrack Setup Script..."

# Create PlugTrack user and group
echo "Creating PlugTrack user and group..."
groupadd --system PlugTrack || true
useradd --system --home /opt/plugtrack --shell /usr/sbin/nologin --gid PlugTrack --comment "PlugTrack service account" PlugTrack || true

# Update system and install required packages
echo "Installing required packages..."
apt-get update
apt-get install -y \
    python3 \
    python3-venv \
    python3-dev \
    python3-pip \
    gcc \
    build-essential \
    dos2unix \
    sudo \
    sqlite3 \
    rsync

# Create service directory structure
echo "Creating service directory structure..."
install -d -m 755 /opt/plugtrack
install -d -m 755 /opt/plugtrack/instance
install -d -m 755 /opt/plugtrack/logs
install -d -m 755 /opt/plugtrack/exports
install -d -m 755 /opt/plugtrack/backups

# Create log files
echo "Setting up log files..."
touch /var/log/plugtrack-web.log /var/log/plugtrack-web.err
touch /var/log/plugtrack-migration.log /var/log/plugtrack-migration.err
touch /var/log/plugtrack-backup.log /var/log/plugtrack-backup.err

# Copy files (excluding __pycache__ directories)
echo "Copying files..."
rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' plugtrack/ /opt/plugtrack/

# Create .env file for production (only if it doesn't exist)
echo "Checking for existing .env file..."
if [ ! -f "/opt/plugtrack/.env" ]; then
    echo "Creating production environment file..."
    cat > /opt/plugtrack/.env << 'EOF'
# PlugTrack Production Configuration
FLASK_APP=run_app.py
FLASK_ENV=production
SECRET_KEY=your-secret-key-change-this-in-production
DATABASE_URL=sqlite:///instance/plugtrack.db
WTF_CSRF_ENABLED=True
EOF
else
    echo "Using existing .env file"
fi

# Fix line endings
echo "Fixing line endings..."
dos2unix /opt/plugtrack/*.py || true
dos2unix /opt/plugtrack/models/*.py || true
dos2unix /opt/plugtrack/routes/*.py || true
dos2unix /opt/plugtrack/services/*.py || true
dos2unix /opt/plugtrack/migrations/*.py || true
dos2unix /opt/plugtrack/migrations/versions/*.py || true

# Create and set up virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv /opt/plugtrack/venv

# Install required Python packages
echo "Installing Python packages..."
/opt/plugtrack/venv/bin/python3 -m pip install --no-cache-dir --upgrade pip
/opt/plugtrack/venv/bin/python3 -m pip install --no-cache-dir \
    Flask==3.0.0 \
    Flask-SQLAlchemy==3.1.1 \
    Flask-Migrate==4.0.5 \
    Flask-Login==0.6.3 \
    Flask-WTF==1.2.1 \
    WTForms==3.1.1 \
    cryptography==41.0.7 \
    python-dotenv==1.0.0 \
    Werkzeug==3.0.1 \
    pandas==2.1.4 \
    numpy==1.24.3 \
    click==8.1.7

# Fix potential pandas installation issue
echo "Fixing pandas installation..."
/opt/plugtrack/venv/bin/python3 -m pip install --no-cache-dir --force-reinstall pandas==2.1.4

# Create startup scripts
echo "Creating startup scripts..."

# Web Application startup script
cat > /opt/plugtrack/start-web.sh << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/plugtrack/venv/bin/python3"
export PYTHONPATH="/opt/plugtrack:${PYTHONPATH}"
export FLASK_APP=run_app.py
export FLASK_ENV=production
export HOST=0.0.0.0
export PORT=5000
cd /opt/plugtrack
exec $VENV_PYTHON run_app.py
EOF

# Database migration script
cat > /opt/plugtrack/run-migration.sh << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/plugtrack/venv/bin/python3"
export PYTHONPATH="/opt/plugtrack:${PYTHONPATH}"
export FLASK_APP=run_app.py
export FLASK_ENV=production
cd /opt/plugtrack
exec $VENV_PYTHON -m flask init-db
EOF

# Database backup script
cat > /opt/plugtrack/backup-db.sh << 'EOF'
#!/bin/sh
BACKUP_DIR="/opt/plugtrack/backups"
DB_PATH="/opt/plugtrack/instance/plugtrack.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ -f "$DB_PATH" ]; then
    mkdir -p "$BACKUP_DIR"
    cp "$DB_PATH" "$BACKUP_DIR/plugtrack_$TIMESTAMP.db"
    echo "Database backed up to $BACKUP_DIR/plugtrack_$TIMESTAMP.db"
    
    # Keep only last 10 backups
    ls -t "$BACKUP_DIR"/plugtrack_*.db | tail -n +11 | xargs -r rm
else
    echo "Database file not found at $DB_PATH"
    exit 1
fi
EOF

chmod +x /opt/plugtrack/start-*.sh
chmod +x /opt/plugtrack/run-migration.sh
chmod +x /opt/plugtrack/backup-db.sh

# Set up daily backup cron job
echo "Setting up daily backup cron job..."
cat > /etc/cron.daily/plugtrack-backup << 'EOF'
#!/bin/sh
/opt/plugtrack/backup-db.sh >> /var/log/plugtrack-backup.log 2>> /var/log/plugtrack-backup.err
EOF

# Set up weekly maintenance cron job
echo "Setting up weekly maintenance cron job..."
cat > /etc/cron.weekly/plugtrack-maintenance << 'EOF'
#!/bin/sh
VENV_PYTHON="/opt/plugtrack/venv/bin/python3"
export PYTHONPATH="/opt/plugtrack:${PYTHONPATH}"
export FLASK_APP=run_app.py
export FLASK_ENV=production
cd /opt/plugtrack
exec $VENV_PYTHON -m flask init-db >> /var/log/plugtrack-migration.log 2>> /var/log/plugtrack-migration.err
EOF

# Make cron files executable
chmod +x /etc/cron.daily/plugtrack-backup
chmod +x /etc/cron.weekly/plugtrack-maintenance

# Initialize the database (only if no existing database)
echo "Checking for existing database..."
if [ ! -f "/opt/plugtrack/instance/plugtrack.db" ]; then
    echo "Initializing database..."
    cd /opt/plugtrack
    /opt/plugtrack/venv/bin/python3 -m flask init-db
else
    echo "Using existing database at /opt/plugtrack/instance/plugtrack.db"
    echo "Running migrations to ensure database is up to date..."
    cd /opt/plugtrack
    /opt/plugtrack/venv/bin/python3 -m flask init-db
fi

# Set correct permissions
echo "Setting permissions..."
chown -R PlugTrack:PlugTrack /opt/plugtrack
chown PlugTrack:PlugTrack /var/log/plugtrack-*
chmod -R 755 /opt/plugtrack
chmod 644 /opt/plugtrack/.env
chmod 644 /var/log/plugtrack-*

# Copy systemd service files and enable/start services
echo "Setting up systemd services..."
if [ -f "../PlugTrack-Web.service" ]; then
    cp ../PlugTrack-Web.service /etc/systemd/system/
elif [ -f "PlugTrack-Web.service" ]; then
    cp PlugTrack-Web.service /etc/systemd/system/
else
    echo "Creating PlugTrack-Web.service..."
    cat > /etc/systemd/system/PlugTrack-Web.service << 'EOF'
[Unit]
Description=PlugTrack EV Charging Session Manager Web Application
After=network.target

[Service]
Type=simple
User=PlugTrack
Group=PlugTrack
WorkingDirectory=/opt/plugtrack
ExecStart=/opt/plugtrack/start-web.sh
StandardOutput=append:/var/log/plugtrack-web.log
StandardError=append:/var/log/plugtrack-web.err
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
fi
dos2unix /etc/systemd/system/PlugTrack-Web.service || true
systemctl daemon-reload
systemctl enable PlugTrack-Web.service
systemctl start PlugTrack-Web.service

echo "Setup complete!"
echo "Next steps:"
echo "1. Update the SECRET_KEY in /opt/plugtrack/.env (if using default)"
echo "2. Configure any additional settings in the web interface"
echo "3. Check logs in /var/log/plugtrack-*.log and /var/log/plugtrack-*.err"
echo "4. Web interface will be available at http://<your-server-ip>:5000"
echo "5. Database backups will be created daily in /opt/plugtrack/backups/"
