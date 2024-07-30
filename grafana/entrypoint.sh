#!/bin/bash

# Source environment variables from .env file
if [ -f /etc/grafana/.env ]; then
  export $(grep -v '^#' /etc/grafana/.env | xargs)
fi

# Generate InfluxDB token if it doesn't exist
if [ -z "$INFLUXDB_INIT_ADMIN_TOKEN" ]; then
  INFLUXDB_INIT_ADMIN_TOKEN=$(curl -X POST http://influxdb:8086/api/v2/authorizations \
    -H "Authorization: Token ${INFLUXDB_INIT_ADMIN_TOKEN}" \
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
