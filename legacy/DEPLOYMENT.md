# PlugTrack Deployment Guide

This guide covers deploying PlugTrack on a Debian/Ubuntu LXC container on Proxmox, following the same patterns as KeroTrack.

## Overview

PlugTrack will be deployed with:
- **Source directory**: `/sijoupload/plugtrack` (for updates)
- **Install directory**: `/opt/plugtrack` (production location)
- **Python virtual environment**: `/opt/plugtrack/venv`
- **Database**: SQLite at `/opt/plugtrack/instance/plugtrack.db`
- **Logs**: `/var/log/plugtrack-*.log` and `/var/log/plugtrack-*.err`
- **Backups**: `/opt/plugtrack/backups/` (daily automatic backups)

## Prerequisites

- Debian/Ubuntu LXC container on Proxmox
- Root access to the container
- Network access for package installation

## Initial Deployment

### 1. Prepare the Source

```bash
# On your development machine, copy PlugTrack to the LXC
scp -r PlugTrack/ root@your-lxc-ip:/sijoupload/plugtrack
```

### 2. Run the Setup Script

```bash
# SSH into your LXC container
ssh root@your-lxc-ip

# Navigate to the source directory
cd /sijoupload/plugtrack

# Make the setup script executable
chmod +x PlugTrack_Setup.sh

# Run the setup script
./PlugTrack_Setup.sh
```

The setup script will:
- Create the `PlugTrack` system user and group
- Install required system packages
- Create the directory structure at `/opt/plugtrack`
- Set up a Python virtual environment
- Install Python dependencies
- Initialize the database
- Create systemd service files
- Set up cron jobs for backups and maintenance
- Start the web service

### 3. Configure Production Settings

After setup, update the production configuration:

```bash
# Edit the production environment file
nano /opt/plugtrack/.env
```

Update the following settings:
- `SECRET_KEY`: Generate a secure secret key
- `FLASK_ENV`: Set to `production`
- Any other environment-specific settings

**Note**: If you're copying existing `.env` and database files, the setup script will detect and use them automatically.

### 4. Verify Deployment

```bash
# Check service status
systemctl status PlugTrack-Web

# Check logs
tail -f /var/log/plugtrack-web.log
tail -f /var/log/plugtrack-web.err

# Test web interface
curl http://localhost:5000
```

## Updating PlugTrack

### 1. Prepare Updated Source

```bash
# Copy updated PlugTrack to the LXC
scp -r PlugTrack/ root@your-lxc-ip:/sijoupload/plugtrack
```

### 2. Run the Update Script

```bash
# SSH into your LXC container
ssh root@your-lxc-ip

# Navigate to the source directory
cd /sijoupload/plugtrack

# Make the update script executable
chmod +x update_plugtrack.sh

# Run the update script
./update_plugtrack.sh
```

The update script will:
- Stop the running service
- Backup the current installation
- Backup the database
- Copy new files
- Run database migrations
- Restart the service
- Clean up source files on success

## Service Management

### Manual Service Control

```bash
# Start the service
systemctl start PlugTrack-Web

# Stop the service
systemctl stop PlugTrack-Web

# Restart the service
systemctl restart PlugTrack-Web

# Check service status
systemctl status PlugTrack-Web

# Enable/disable auto-start
systemctl enable PlugTrack-Web
systemctl disable PlugTrack-Web
```

### Viewing Logs

```bash
# Web application logs
tail -f /var/log/plugtrack-web.log
tail -f /var/log/plugtrack-web.err

# Migration logs
tail -f /var/log/plugtrack-migration.log
tail -f /var/log/plugtrack-migration.err

# Backup logs
tail -f /var/log/plugtrack-backup.log
tail -f /var/log/plugtrack-backup.err

# All PlugTrack logs
journalctl -u PlugTrack-Web -f
```

## Database Management

### Manual Database Operations

```bash
# Run database migrations manually
cd /opt/plugtrack
/opt/plugtrack/venv/bin/python3 -m flask init-db

# Check migration status
/opt/plugtrack/venv/bin/python3 -m flask migration-status

# Initialize database (fresh install)
/opt/plugtrack/venv/bin/python3 -m flask init-db
```

### Database Backups

```bash
# Manual backup
/opt/plugtrack/backup-db.sh

# List existing backups
ls -la /opt/plugtrack/backups/

# Restore from backup (example)
cp /opt/plugtrack/backups/plugtrack_20240101_120000.db /opt/plugtrack/instance/plugtrack.db
```

## Maintenance Tasks

### Automated Tasks

The deployment includes several automated maintenance tasks:

1. **Daily Database Backups** (`/etc/cron.daily/plugtrack-backup`)
   - Creates timestamped database backups
   - Keeps only the last 10 backups
   - Logs to `/var/log/plugtrack-backup.log`

2. **Weekly Maintenance** (`/etc/cron.weekly/plugtrack-maintenance`)
   - Runs database migrations
   - Logs to `/var/log/plugtrack-migration.log`

### Manual Maintenance

```bash
# Check disk usage
du -sh /opt/plugtrack/
du -sh /opt/plugtrack/backups/

# Clean old backups (keep last 10)
ls -t /opt/plugtrack/backups/plugtrack_*.db | tail -n +11 | xargs -r rm

# Check database integrity
sqlite3 /opt/plugtrack/instance/plugtrack.db "PRAGMA integrity_check;"
```

## Troubleshooting

### Common Issues

1. **Service won't start**
   ```bash
   # Check service status
   systemctl status PlugTrack-Web
   
   # Check logs
   journalctl -u PlugTrack-Web --no-pager -l
   
   # Check file permissions
   ls -la /opt/plugtrack/
   ```

2. **Database issues**
   ```bash
   # Check database file exists
   ls -la /opt/plugtrack/instance/
   
   # Check database integrity
   sqlite3 /opt/plugtrack/instance/plugtrack.db "PRAGMA integrity_check;"
   
   # Run migrations
   cd /opt/plugtrack
   /opt/plugtrack/venv/bin/python3 -m flask init-db
   ```

3. **Permission issues**
   ```bash
   # Fix ownership
   chown -R PlugTrack:PlugTrack /opt/plugtrack
   
   # Fix permissions
   chmod -R 755 /opt/plugtrack
   chmod 644 /opt/plugtrack/plugtrack/.env
   ```

### Rollback Procedure

If an update fails, you can rollback:

```bash
# Stop the service
systemctl stop PlugTrack-Web

# Restore from backup
rm -rf /opt/plugtrack
mv /sijoupload/plugtrack.backup.YYYYMMDD_HHMMSS /opt/plugtrack

# Fix permissions
chown -R PlugTrack:PlugTrack /opt/plugtrack
chmod -R 755 /opt/plugtrack

# Start the service
systemctl start PlugTrack-Web
```

## Security Considerations

1. **Change default secret key** in `/opt/plugtrack/plugtrack/.env`
2. **Use HTTPS** in production (configure reverse proxy)
3. **Regular backups** are automated but verify they're working
4. **Monitor logs** for any suspicious activity
5. **Keep system updated** with security patches

## File Structure

```
/opt/plugtrack/
├── venv/                          # Python virtual environment
├── instance/
│   └── plugtrack.db              # SQLite database
├── .env                          # Production environment config
├── run_app.py                    # Main application entry point
├── models/                       # Database models
├── routes/                       # Flask routes
├── services/                     # Business logic
├── templates/                    # HTML templates
├── static/                       # Static assets
├── migrations/                   # Database migrations
├── backups/                      # Database backups
├── logs/                         # Application logs
├── start-web.sh                  # Web service startup script
├── run-migration.sh              # Migration script
└── backup-db.sh                  # Database backup script
```

## Support

For issues with the deployment:
1. Check the logs first
2. Verify file permissions and ownership
3. Ensure all required packages are installed
4. Check database integrity
5. Review the service status and configuration
