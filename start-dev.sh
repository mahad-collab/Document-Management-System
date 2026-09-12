#!/bin/bash
# Starts the full local dev environment: backend on :8000 (plain HTTP,
# localhost only) and :8443 (HTTPS, LAN-reachable), frontend on :3000
# (plain HTTP, localhost) and :3443 (HTTPS, LAN-reachable).
#
# The HTTPS instances are reachable from any device on the same network at
# https://desktop-3e2t2nd.local:8443 (backend) and :3443 (frontend) — this
# machine's mDNS hostname, which resolves to whatever this machine's actual
# address is on ANY network, so these two links never need to change when
# the network does (see backend/app/auth/routes.py's _MDNS_HOST_RE and the
# matching checks in main.py / frontend/src/lib/api.ts).
#
# Run from the repo root: ./start-dev.sh
# Stop everything:        ./start-dev.sh stop

set -e
cd "$(dirname "$0")"

PORTS="8000 8443 3000 3443"

stop_all() {
  echo "Stopping any running instances on ports: $PORTS"
  for port in $PORTS; do
    pid=$(netstat -ano 2>/dev/null | grep -E ":$port " | grep LISTEN | awk '{print $5}' | head -1)
    if [ -n "$pid" ]; then
      taskkill //PID "$pid" //F 2>/dev/null && echo "  stopped PID $pid on :$port" || true
    fi
  done
}

if [ "$1" = "stop" ]; then
  stop_all
  exit 0
fi

stop_all

echo ""
echo "Starting backend (http :8000, https :8443)..."
(
  cd backend
  source .venv/Scripts/activate
  (uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn_out.log 2>&1 &)
  (uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile certs/lan-key.pem --ssl-certfile certs/lan-cert.pem > /tmp/uvicorn_https_out.log 2>&1 &)
)
sleep 3

echo "Starting frontend (http :3000, https :3443)..."
(
  cd frontend
  (npm run dev > /tmp/nextjs_out.log 2>&1 &)
)
sleep 6
(
  cd frontend
  (export NEXT_DIST_DIR=.next-https && npx next dev --experimental-https \
    --experimental-https-key "../backend/certs/lan-key.pem" \
    --experimental-https-cert "../backend/certs/lan-cert.pem" \
    -p 3443 -H 0.0.0.0 > /tmp/nextjs_https_out.log 2>&1 &)
)
sleep 8

echo ""
echo "Checking health..."
printf "  backend  http  localhost:8000  -> "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health
printf "  backend  https .local:8443     -> "; curl -sk -o /dev/null -w "%{http_code}\n" https://desktop-3e2t2nd.local:8443/health
printf "  frontend http  localhost:3000  -> "; curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/
printf "  frontend https .local:3443     -> "; curl -sk -o /dev/null -w "%{http_code}\n" https://desktop-3e2t2nd.local:3443/

cat << 'EOF'

Ready. Fixed links (work on any network, no reconfiguration needed):
  You (this machine):     http://localhost:3000
  Anyone on the LAN:      https://desktop-3e2t2nd.local:3443
  Backend API docs:       https://desktop-3e2t2nd.local:8443/docs

First time on a new device: visit the :8443 link once, click through the
certificate warning, then the :3443 link and do the same, before signing in.
EOF
