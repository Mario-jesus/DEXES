#!/usr/bin/env bash
# Generates prometheus.yml from prometheus.yml.template using .env.
# Run from repo root: ./scripts/generate-prometheus-config.sh
# Requires: GRAFANA_CLOUD_PROMETHEUS_REMOTE_WRITE_URL, GRAFANA_CLOUD_METRICS_INSTANCE_ID, GRAFANA_CLOUD_METRICS_TOKEN in .env

set -e
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Error: .env not found. Create it with GRAFANA_CLOUD_PROMETHEUS_REMOTE_WRITE_URL, GRAFANA_CLOUD_METRICS_INSTANCE_ID, GRAFANA_CLOUD_METRICS_TOKEN"
  exit 1
fi

set -a
# shellcheck source=/dev/null
source .env
set +a

for v in GRAFANA_CLOUD_PROMETHEUS_REMOTE_WRITE_URL GRAFANA_CLOUD_METRICS_INSTANCE_ID GRAFANA_CLOUD_METRICS_TOKEN; do
  if [ -z "${!v}" ]; then
    echo "Error: $v is not set in .env"
    exit 1
  fi
done

if [ ! -f prometheus.yml.template ]; then
  echo "Error: prometheus.yml.template not found"
  exit 1
fi

envsubst '$GRAFANA_CLOUD_PROMETHEUS_REMOTE_WRITE_URL $GRAFANA_CLOUD_METRICS_INSTANCE_ID $GRAFANA_CLOUD_METRICS_TOKEN' < prometheus.yml.template > prometheus.yml
echo "Generated prometheus.yml from .env"
