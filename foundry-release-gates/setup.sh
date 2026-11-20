#!/usr/bin/env bash
# Creates everything the release gate needs in ONE dedicated resource group,
# with a budget alert, and writes .env. Delete it all with ./teardown.sh.
#
#   SUBSCRIPTION=<name or id> ./setup.sh
#
# Billable: Foundry model usage (pay per token), Application Insights /
# Log Analytics ingestion, and a small amount of vector store storage.
set -euo pipefail

SUBSCRIPTION="${SUBSCRIPTION:?set SUBSCRIPTION}"
LOCATION="${LOCATION:-swedencentral}"
RG="${RG:-rg-foundry-evalgate-blogtest}"
BUDGET_AMOUNT="${BUDGET_AMOUNT:-25}"
AGENT_MODEL="${AGENT_MODEL:-gpt-4.1-mini}"
# gpt-5.1 had zero GlobalStandard quota on the test subscription; gpt-5-mini had 500.
OPT_MODEL="${OPT_MODEL:-gpt-5-mini}"

az account set --subscription "$SUBSCRIPTION"
az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null
SUB_ID=$(az account show --query id -o tsv)
SUFFIX=$(echo -n "$SUB_ID$RG" | sha1sum | cut -c1-6)
ACCOUNT="fdy-evalgate-$SUFFIX"
PROJECT="rxinfo-gate"
LAW="law-evalgate-$SUFFIX"
APPI="appi-evalgate-$SUFFIX"
ME=$(az ad signed-in-user show --query id -o tsv)
EMAIL=$(az account show --query user.name -o tsv)

echo "== resource providers (a new subscription has none of these registered)"
for ns in Microsoft.CognitiveServices Microsoft.OperationalInsights Microsoft.Insights; do
  az provider register --namespace "$ns" --wait -o none
done

echo "== resource group $RG in $LOCATION"
az group create -n "$RG" -l "$LOCATION" --tags purpose=blog-test owner=nithin -o none

echo "== budget alert ($BUDGET_AMOUNT in billing currency, 50% actual and 100% forecast)"
START=$(date -u +%Y-%m-01T00:00:00Z)
END=$(date -u -d "+3 months" +%Y-%m-01T00:00:00Z)
cat > /tmp/budget.json <<JSON
{"properties":{"category":"Cost","amount":$BUDGET_AMOUNT,"timeGrain":"Monthly",
 "timePeriod":{"startDate":"$START","endDate":"$END"},
 "notifications":{
  "actual50":{"enabled":true,"operator":"GreaterThan","threshold":50,"thresholdType":"Actual","contactEmails":["$EMAIL"]},
  "forecast100":{"enabled":true,"operator":"GreaterThan","threshold":100,"thresholdType":"Forecasted","contactEmails":["$EMAIL"]}}}}
JSON
az rest --method put -o none \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.Consumption/budgets/evalgate-budget?api-version=2023-05-01" \
  --body @/tmp/budget.json
rm -f /tmp/budget.json

echo "== Foundry resource $ACCOUNT and project $PROJECT"
az cognitiveservices account show -n "$ACCOUNT" -g "$RG" -o none 2>/dev/null || \
az cognitiveservices account create -n "$ACCOUNT" -g "$RG" -l "$LOCATION" --kind AIServices --sku S0 \
  --custom-domain "$ACCOUNT" --assign-identity --allow-project-management true -o none
az cognitiveservices account project show -n "$ACCOUNT" -g "$RG" --project-name "$PROJECT" -o none 2>/dev/null || \
az cognitiveservices account project create -n "$ACCOUNT" -g "$RG" --project-name "$PROJECT" -l "$LOCATION" -o none
ACCOUNT_ID=$(az cognitiveservices account show -n "$ACCOUNT" -g "$RG" --query id -o tsv)
PROJECT_ID=$(az cognitiveservices account project show -n "$ACCOUNT" -g "$RG" --project-name "$PROJECT" --query id -o tsv)
PROJECT_MI=$(az cognitiveservices account project show -n "$ACCOUNT" -g "$RG" --project-name "$PROJECT" --query identity.principalId -o tsv)

deploy() { # name model capacity
  local version
  if az cognitiveservices account deployment show -n "$ACCOUNT" -g "$RG" --deployment-name "$1" -o none 2>/dev/null; then
    echo "   $1 already deployed"; return
  fi
  version=$(az cognitiveservices account list-models -n "$ACCOUNT" -g "$RG" \
    --query "[?name=='$2' && format=='OpenAI'].version | sort(@) | [-1]" -o tsv)
  [ -n "$version" ] || { echo "model $2 not offered in $LOCATION"; exit 1; }
  echo "   $1 -> $2 $version (GlobalStandard, capacity $3)"
  az cognitiveservices account deployment create -n "$ACCOUNT" -g "$RG" --deployment-name "$1" \
    --model-name "$2" --model-version "$version" --model-format OpenAI \
    --sku-name GlobalStandard --sku-capacity "$3" -o none
}
echo "== model deployments"
deploy "$AGENT_MODEL" "$AGENT_MODEL" 100
deploy "$OPT_MODEL" "$OPT_MODEL" 250  # 50 (50K TPM) rate-limited the Agent Insights run

echo "== Log Analytics + Application Insights, connected to the project"
az monitor log-analytics workspace show -g "$RG" -n "$LAW" -o none 2>/dev/null || \
az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOCATION" --retention-time 30 -o none
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query id -o tsv)
az monitor app-insights component show -g "$RG" -a "$APPI" -o none 2>/dev/null || \
az monitor app-insights component create -g "$RG" -a "$APPI" -l "$LOCATION" --workspace "$LAW_ID" -o none
APPI_ID=$(az monitor app-insights component show -g "$RG" -a "$APPI" --query id -o tsv)
# The connection string goes straight from one Azure call into another; it is never printed.
az monitor app-insights component show -g "$RG" -a "$APPI" --query connectionString -o tsv | python3 -c '
import json, sys
cs, target = sys.stdin.read().strip(), sys.argv[1]
json.dump({"properties": {"category": "AppInsights", "target": target, "authType": "ApiKey",
  "isSharedToAll": False, "credentials": {"key": cs},
  "metadata": {"ApiType": "Azure", "ResourceId": target}}}, open("/tmp/appi-conn.json", "w"))' "$APPI_ID"
az rest --method put -o none --url "https://management.azure.com$PROJECT_ID/connections/appinsights?api-version=2025-06-01" \
  --body @/tmp/appi-conn.json
rm -f /tmp/appi-conn.json

echo "== role assignments"
assign() { # principal type role scope
  az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" --role "$3" --scope "$4" -o none \
    || echo "   could not assign $3 to $1"
}
FOUNDRY_USER=53ca6127-db72-4b80-b1b0-d745d6d5456d
assign "$ME" User "$FOUNDRY_USER" "$ACCOUNT_ID"
assign "$ME" User "Log Analytics Reader" "$LAW_ID"
assign "$PROJECT_MI" ServicePrincipal "$FOUNDRY_USER" "$ACCOUNT_ID"
assign "$PROJECT_MI" ServicePrincipal "Log Analytics Reader" "$APPI_ID"
assign "$PROJECT_MI" ServicePrincipal "Privileged Monitoring Data Reader" "$APPI_ID"

ENDPOINT="https://$ACCOUNT.services.ai.azure.com/api/projects/$PROJECT"
cat > .env <<ENV
FOUNDRY_PROJECT_ENDPOINT=$ENDPOINT
AGENT_MODEL=$AGENT_MODEL
JUDGE_MODEL=$AGENT_MODEL
OPTIMIZATION_MODEL=$OPT_MODEL
INSIGHTS_MODEL=$OPT_MODEL
APP_INSIGHTS_RESOURCE_ID=$APPI_ID
RG=$RG
ACCOUNT=$ACCOUNT
ENV
echo "== done. Wait a few minutes for role assignments to apply, then: set -a; . ./.env; set +a"
