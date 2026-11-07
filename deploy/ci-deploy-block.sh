  plugtrack)
    REPO=PlugTrack; BRANCH=main
    IMAGES=("plugtrack-api:backend" "plugtrack-ui:frontend")
    TARGETS=("/dockerdata/compose-stacks/plugtrack:plugtrack-api" "/dockerdata/compose-stacks/plugtrack:plugtrack-ui")
    # /mcp/ (trailing slash: /mcp answers 307) is on the API port and answers
    # 401 without a bearer token.
    CHECKS=(plugtrack-api plugtrack-ui
            "GET http://127.0.0.1:9278/api/health 200"
            "POST http://127.0.0.1:9278/mcp/ 401"
            "GET http://127.0.0.1:9279/ 200")
    # Real data: an online SQLite snapshot before every deploy, outside the
    # app's own backups/ so its retention never prunes it.
    pre_deploy() {
      [ "$(docker inspect -f '{{.State.Running}}' plugtrack-api 2>/dev/null)" = true ] \
        || { echo "plugtrack-api not running: no db snapshot"; return 0; }
      local ts; ts=$(date +%Y%m%d-%H%M%S)
      docker exec plugtrack-api python -c "import os, sqlite3; os.makedirs('/app/data/ci-backups', exist_ok=True); s=sqlite3.connect('/app/data/plugtrack.db'); d=sqlite3.connect('/app/data/ci-backups/plugtrack-$ts-ci.db'); s.backup(d); r=d.execute('PRAGMA integrity_check').fetchone()[0]; d.close(); assert r == 'ok', r"
      echo "db snapshot /app/data/ci-backups/plugtrack-$ts-ci.db (integrity ok)"
    }
    ;;
