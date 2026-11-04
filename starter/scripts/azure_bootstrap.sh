#!/usr/bin/env bash
# Organiser script for the live-Azure track: the shared resources the MCP tools read from.
#
#   az login && ./scripts/azure_bootstrap.sh up            # create / update everything (idempotent)
#   ./scripts/azure_bootstrap.sh redeploy-bad              # event morning: fresh "bad deploy" on orders-api
#   ./scripts/azure_bootstrap.sh grant participants.txt    # read access for people (UPNs / object ids, one per line)
#   ./scripts/azure_bootstrap.sh status                    # apps, revisions, newest log line
#   ./scripts/azure_bootstrap.sh pause | resume            # scale apps to 0 / back to 1 (pause ≈ no cost)
#   ./scripts/azure_bootstrap.sh down --yes                # delete everything this script created
#
# What it creates (all in $RG, region $LOC):
#   Log Analytics workspace $LAW  ← ContainerAppConsoleLogs_CL, queried by `query_logs`
#   Container Apps env $ENVNAME   (consumption, logs → $LAW)
#   4 Container Apps, one per incident story, same names as the mock fixtures:
#     orders-api (bad deploy: 2.13.1 → 2.13.2 → 2.14.0 throws 500s), payments-worker (DB refused),
#     checkout-frontend (OOM), search-indexer (busy but healthy).
#   Each runs stock python:3.12-alpine with scripts/noisy_app.py passed in as base64 (no registry).
# Cost while running: 4 × 0.25 vCPU / 0.5 GiB ≈ NOK 25–30 per day. `pause` when not needed.
# Participants get Reader on the four apps and Log Analytics Reader on the workspace only, not
# on the resource group (it holds unrelated resources).
set -euo pipefail

SUB="${AZURE_SUBSCRIPTION_ID:-e419a266-2639-4134-9ded-7a777b020ae9}"
RG="${AZURE_RESOURCE_GROUP:-VilluResourceGroup}"
LOC="${AZURE_LOCATION:-norwayeast}"
LAW="${LAW_NAME:-hackathon-logs}"
ENVNAME="${ACA_ENV:-hackathon-env}"
IMAGE="${APP_IMAGE:-docker.io/library/python:3.12-alpine}"
APPS=(orders-api payments-worker checkout-frontend search-indexer)
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log() { echo "== $*"; }

prepare() {
  az account set --subscription "$SUB"
  az extension add --name containerapp --upgrade --only-show-errors >/dev/null
  az provider register --namespace Microsoft.App --only-show-errors >/dev/null
  az provider register --namespace Microsoft.OperationalInsights --only-show-errors >/dev/null
  echo "subscription: $(az account show --query name -o tsv)  rg: $RG  location: $LOC"
}

app_exists() { az containerapp show -g "$RG" -n "$1" --query name -o tsv >/dev/null 2>&1; }

write_yaml() {  # name version suffix env_id b64
  cat >"$TMP/$1.yaml" <<YAML
location: $LOC
properties:
  managedEnvironmentId: $4
  configuration:
    activeRevisionsMode: Single
  template:
    revisionSuffix: $3
    containers:
      - name: app
        image: $IMAGE
        command: ["/bin/sh", "-c"]
        args: ["echo \$APP_B64 | base64 -d > /tmp/app.py && exec python -u /tmp/app.py"]
        env:
          - name: PROFILE
            value: "$1"
          - name: APP_VERSION
            value: "$2"
          - name: APP_B64
            value: "$5"
        resources:
          cpu: 0.25
          memory: 0.5Gi
    scale:
      minReplicas: 1
      maxReplicas: 1
YAML
}

new_revision() {  # app version suffix
  az containerapp update -g "$RG" -n "$1" --revision-suffix "$3" \
    --set-env-vars "APP_VERSION=$2" --only-show-errors >/dev/null
}

cmd_up() {
  prepare
  log "Log Analytics workspace $LAW"
  az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOC" --retention-time 30 --only-show-errors >/dev/null
  LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)
  LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)

  log "Container Apps environment $ENVNAME"
  if ! az containerapp env show -g "$RG" -n "$ENVNAME" >/dev/null 2>&1; then
    az containerapp env create -g "$RG" -n "$ENVNAME" -l "$LOC" \
      --logs-destination log-analytics --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" \
      --only-show-errors >/dev/null
  fi
  ENV_ID=$(az containerapp env show -g "$RG" -n "$ENVNAME" --query id -o tsv)
  B64=$(base64 -w0 "$HERE/noisy_app.py")

  for app in "${APPS[@]}"; do
    if app_exists "$app"; then
      log "app $app exists (use redeploy-bad for a fresh orders-api deploy)"
      continue
    fi
    log "app $app"
    first_version="1.0.0"
    [ "$app" = "orders-api" ] && first_version="2.13.1"
    write_yaml "$app" "$first_version" "v$(echo "$first_version" | tr . -)" "$ENV_ID" "$B64"
    az containerapp create -g "$RG" -n "$app" --yaml "$TMP/$app.yaml" --only-show-errors >/dev/null
  done

  if [ "$(az containerapp revision list -g "$RG" -n orders-api --query 'length(@)' -o tsv)" -lt 3 ]; then
    log "orders-api history: 2.13.2 (good), then 2.14.0 (bad)"
    new_revision orders-api 2.13.2 v2-13-2
    new_revision orders-api 2.14.0 "v2-14-0-$(date +%H%M)"
  fi

  echo
  echo "Post this to participants (live-Azure track):"
  echo "  MOCK_AZURE=false"
  echo "  LOG_ANALYTICS_WORKSPACE_ID=$LAW_ID"
  echo "Logs show up in ContainerAppConsoleLogs_CL 5–10 minutes after the apps start."
}

cmd_redeploy_bad() {
  prepare
  local suffix
  suffix="v2-14-0-$(date +%m%d%H%M)"
  log "orders-api: new bad revision $suffix (deploy happened 'just now' for the deployment_regression story)"
  new_revision orders-api 2.14.0 "$suffix"
}

cmd_grant() {
  local file="${1:?usage: grant <file with one UPN, e-mail or object id per line>}"
  prepare
  local scopes=()
  for app in "${APPS[@]}"; do scopes+=("$(az containerapp show -g "$RG" -n "$app" --query id -o tsv)"); done
  local law_scope
  law_scope=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query id -o tsv)
  grep -v '^\s*#' "$file" | sed '/^\s*$/d' | while read -r who; do
    log "grant $who"
    for s in "${scopes[@]}"; do
      az role assignment create --assignee "$who" --role Reader --scope "$s" --only-show-errors >/dev/null
    done
    az role assignment create --assignee "$who" --role "Log Analytics Reader" --scope "$law_scope" \
      --only-show-errors >/dev/null
  done
}

cmd_status() {
  prepare
  az containerapp list -g "$RG" --query "[?properties.environmentId && contains(properties.environmentId, '$ENVNAME')].{app:name, latest:properties.latestRevisionName, state:properties.runningStatus}" -o table
  az containerapp revision list -g "$RG" -n orders-api --all \
    --query "[].{revision:name, created:properties.createdTime, active:properties.active}" -o table
  LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)
  echo "workspace customerId: $LAW_ID"
  az monitor log-analytics query -w "$LAW_ID" -t PT30M --analytics-query \
    "ContainerAppConsoleLogs_CL | summarize lines=count(), newest=max(TimeGenerated) by ContainerAppName_s" -o table \
    || echo "(no logs yet — wait a few minutes after up/resume)"
}

scale_all() {  # min max
  prepare
  for app in "${APPS[@]}"; do
    az containerapp update -g "$RG" -n "$app" --min-replicas "$1" --max-replicas "$2" --only-show-errors >/dev/null
    echo "$app → min=$1 max=$2"
  done
}

cmd_down() {
  [ "${1:-}" = "--yes" ] || { echo "This deletes the 4 apps, $ENVNAME and $LAW in $RG. Re-run with: down --yes"; exit 1; }
  prepare
  for app in "${APPS[@]}"; do
    az containerapp delete -g "$RG" -n "$app" --yes --only-show-errors >/dev/null 2>&1 && echo "deleted $app" || true
  done
  az containerapp env delete -g "$RG" -n "$ENVNAME" --yes --only-show-errors >/dev/null 2>&1 && echo "deleted $ENVNAME" || true
  az monitor log-analytics workspace delete -g "$RG" -n "$LAW" --yes --force true --only-show-errors >/dev/null 2>&1 \
    && echo "deleted $LAW" || true
}

case "${1:-up}" in
  up) cmd_up ;;
  redeploy-bad) cmd_redeploy_bad ;;
  grant) shift; cmd_grant "$@" ;;
  status) cmd_status ;;
  pause) scale_all 0 1 ;;
  resume) scale_all 1 1 ;;
  down) shift; cmd_down "$@" ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
