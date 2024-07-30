#!/bin/bash

# Source environment variables from .env file
if [ -f /etc/grafana/.env ]; then
  export $(grep -v '^#' /etc/grafana/.env | xargs)
fi

# Wait for InfluxDB to be ready
until curl -s http://influxdb:8086/health | grep -q '"status":"pass"'; do
  echo "Waiting for InfluxDB to be ready..."
  sleep 5
done

# Start Grafana
/run.sh
