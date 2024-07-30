#!/bin/bash

# Wait for InfluxDB to be ready
until curl -s http://influxdb:8086/ping; do
  echo "Waiting for InfluxDB..."
  sleep 5
done

# Configure Grafana data source
curl -X POST http://admin:admin123@grafana:3000/api/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "InfluxDB",
    "type": "influxdb",
    "access": "proxy",
    "url": "http://influxdb:8086",
    "isDefault": true,
    "database": "'"${INFLUXDB_INIT_BUCKET}"'",
    "user": "'"${INFLUXDB_INIT_USERNAME}"'",
    "secureJsonData": {
      "token": "'"${INFLUXDB_INIT_ADMIN_TOKEN}"'"
    },
    "jsonData": {
      "organization": "'"${INFLUXDB_INIT_ORG}"'",
      "defaultBucket": "'"${INFLUXDB_INIT_BUCKET}"'"
    }
  }'

# Start Grafana
/run.sh
