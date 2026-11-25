#!/usr/bin/env bash
# Azure OpenAI for the live run, in ONE dedicated resource group with a budget
# alert. Keys are disabled: the sample signs in with Microsoft Entra ID.
#   SUBSCRIPTION=<name or id> ./setup.sh      then: set -a; . ./.env; set +a
set -euo pipefail
SUBSCRIPTION="${SUBSCRIPTION:?set SUBSCRIPTION}"
LOCATION="${LOCATION:-swedencentral}"
RG="${RG:-rg-llamaindex-rag-blogtest}"
# gpt-4o and gpt-4.1 had zero GlobalStandard quota on the test subscription in Nov 2026;
# gpt-4.1-mini (released 14 Apr 2025) was available and is what the live run used.
CHAT_MODEL="${CHAT_MODEL:-gpt-4.1-mini}"
CHAT_VERSION="${CHAT_VERSION:-2025-04-14}"
EMBED_MODEL="${EMBED_MODEL:-text-embedding-3-small}"
EMBED_VERSION="${EMBED_VERSION:-1}"
BUDGET="${BUDGET:-20}"

az account set --subscription "$SUBSCRIPTION"
SUB_ID=$(az account show --query id -o tsv)
SUFFIX=$(echo -n "$SUB_ID$RG" | sha1sum | cut -c1-6)
ACCOUNT="aoai-llamaidx-$SUFFIX"
ME=$(az ad signed-in-user show --query id -o tsv)
EMAIL=$(az account show --query user.name -o tsv)

az provider register --namespace Microsoft.CognitiveServices --wait -o none
az group create -n "$RG" -l "$LOCATION" --tags purpose=blog-test -o none

START=$(date -u +%Y-%m-01T00:00:00Z); END=$(date -u -d "+3 months" +%Y-%m-01T00:00:00Z)
az rest --method put -o none \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.Consumption/budgets/llamaidx-budget?api-version=2023-05-01" \
  --body "{\"properties\":{\"category\":\"Cost\",\"amount\":$BUDGET,\"timeGrain\":\"Monthly\",\"timePeriod\":{\"startDate\":\"$START\",\"endDate\":\"$END\"},\"notifications\":{\"actual50\":{\"enabled\":true,\"operator\":\"GreaterThan\",\"threshold\":50,\"thresholdType\":\"Actual\",\"contactEmails\":[\"$EMAIL\"]}}}}"

az cognitiveservices account show -n "$ACCOUNT" -g "$RG" -o none 2>/dev/null || \
az cognitiveservices account create -n "$ACCOUNT" -g "$RG" -l "$LOCATION" --kind OpenAI --sku S0 \
  --custom-domain "$ACCOUNT" --yes -o none
az resource update -g "$RG" -n "$ACCOUNT" --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true -o none
ACCOUNT_ID=$(az cognitiveservices account show -n "$ACCOUNT" -g "$RG" --query id -o tsv)

deploy() { # name model version sku capacity
  az cognitiveservices account deployment show -n "$ACCOUNT" -g "$RG" --deployment-name "$1" -o none 2>/dev/null && return
  az cognitiveservices account deployment create -n "$ACCOUNT" -g "$RG" --deployment-name "$1" \
    --model-name "$2" --model-version "$3" --model-format OpenAI --sku-name "$4" --sku-capacity "$5" -o none
}
deploy "$CHAT_MODEL" "$CHAT_MODEL" "$CHAT_VERSION" GlobalStandard 50
deploy "$EMBED_MODEL" "$EMBED_MODEL" "$EMBED_VERSION" GlobalStandard 50  # Standard is not offered in swedencentral

# Cognitive Services OpenAI User: call deployments with an Entra ID token.
az role assignment create --assignee-object-id "$ME" --assignee-principal-type User \
  --role 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd --scope "$ACCOUNT_ID" -o none || true

cat > .env <<ENV
RAG_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://$ACCOUNT.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT=$CHAT_MODEL
AZURE_OPENAI_CHAT_MODEL=$CHAT_MODEL
AZURE_OPENAI_EMBED_DEPLOYMENT=$EMBED_MODEL
AZURE_OPENAI_API_VERSION=2024-10-21
RG=$RG
ACCOUNT=$ACCOUNT
LOCATION=$LOCATION
ENV
echo "done; role assignments can take a few minutes to apply"
