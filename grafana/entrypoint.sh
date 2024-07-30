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

# Generate InfluxDB token if it doesn't exist
if [ -z "$INFLUXDB_INIT_ADMIN_TOKEN" ]; then
  # Get InfluxDB organization ID without using the token
  INFLUXDB_INIT_ORG_ID=$(curl -s -X GET http://influxdb:8086/api/v2/orgs?org=${INFLUXDB_INIT_ORG} | jq -r '.orgs[0].id')

  # Generate a new token
  INFLUXDB_INIT_ADMIN_TOKEN=$(curl -s -X POST http://influxdb:8086/api/v2/authorizations \
    -H "Content-Type: application/json" \
    -d '{
      "status": "active",
      "description": "admin token",
      "orgID": "'"${INFLUXDB_INIT_ORG_ID}"'",
      "permissions": [
        {
          "action": "read",
          "resource": {
            "type": "buckets"
          }
        },
        {
          "action": "write",
          "resource": {
            "type": "buckets"
          }
        }
      ]
    }' | jq -r '.token')

  echo "INFLUXDB_INIT_ADMIN_TOKEN=${INFLUXDB_INIT_ADMIN_TOKEN}" >> /etc/grafana/.env
  export INFLUXDB_INIT_ADMIN_TOKEN
fi

# Start Grafana
/run.sh
