#!/usr/bin/env bash
# Organiser script: create the shared observability resources the MCP tools read from.
# Idempotent-ish (az create calls are safe to re-run). Costs: Log Analytics (pay per GB, tiny)
# + one consumption-plan Container App (scale-to-zero). Budget alerts already exist on the RG.
#
#   az login && ./scripts/azure_bootstrap.sh
set -euo pipefail

SUB="${AZURE_SUBSCRIPTION_ID:-e419a266-2639-4134-9ded-7a777b020ae9}"
RG="${AZURE_RESOURCE_GROUP:-VilluResourceGroup}"
LOC="${AZURE_LOCATION:-norwayeast}"
LAW="${LAW_NAME:-hackathon-logs}"
ENVNAME="${ACA_ENV:-hackathon-env}"
APP="${ACA_APP:-orders-api}"

az account set --subscription "$SUB"
echo "subscription: $(az account show --query name -o tsv)  rg: $RG  location: $LOC"

az extension add --name containerapp --upgrade --only-show-errors >/dev/null

echo "== Log Analytics workspace"
az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOC" --only-show-errors >/dev/null
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)

echo "== Container Apps environment"
az containerapp env create -g "$RG" -n "$ENVNAME" -l "$LOC" \
  --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" --only-show-errors >/dev/null

echo "== Sample app that produces logs and revisions"
az containerapp create -g "$RG" -n "$APP" --environment "$ENVNAME" \
  --image mcr.microsoft.com/k8se/quickstart:latest --target-port 80 --ingress external \
  --min-replicas 0 --max-replicas 2 --revisions-mode multiple --only-show-errors >/dev/null

# Create a second revision so get_deployment_history has something to show.
az containerapp update -g "$RG" -n "$APP" --set-env-vars "DEPLOY_MARKER=$(date +%s)" --only-show-errors >/dev/null
FQDN=$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)

echo
echo "Generate some traffic/logs:  for i in \$(seq 1 50); do curl -s https://$FQDN/ >/dev/null; done"
echo
echo "Give participants (Reader + Log Analytics Reader + Monitoring Reader on $RG) and post this:"
echo "  LOG_ANALYTICS_WORKSPACE_ID=$LAW_ID"
echo "  MOCK_AZURE=false"
echo
echo "Note: ContainerAppConsoleLogs_CL appears in the workspace a few minutes after first traffic."
