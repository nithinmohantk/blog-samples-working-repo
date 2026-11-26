#!/usr/bin/env bash
# Creates the test cluster for the Nitro Sandboxes article, in AWS CloudShell.
#   EMAIL=you@example.com ./setup.sh
# Everything is tagged project=nitro-sbx-blogtest and removed by ./teardown.sh.
set -euo pipefail
REGION="${REGION:-eu-west-1}"
CLUSTER="${CLUSTER:-nitro-sbx-blogtest}"
K8S_VERSION="${K8S_VERSION:-1.37}"
BUDGET="${BUDGET:-20}"
EMAIL="${EMAIL:?set EMAIL for the budget alert}"
ROLE="${CLUSTER}-podid"
export AWS_REGION="$REGION"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

# eksctl is not preinstalled in CloudShell.
if ! command -v eksctl >/dev/null; then
  mkdir -p "$HOME/bin"
  ARCH=$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')
  curl -sSL "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Linux_${ARCH}.tar.gz" \
    | tar -xz -C "$HOME/bin"
  export PATH="$HOME/bin:$PATH"
fi
eksctl version

# Monthly cost budget with an alert at 50% of actual spend.
if ! aws budgets describe-budget --account-id "$ACCOUNT" --budget-name "$CLUSTER" >/dev/null 2>&1; then
  aws budgets create-budget --account-id "$ACCOUNT" \
    --budget "{\"BudgetName\":\"$CLUSTER\",\"BudgetLimit\":{\"Amount\":\"$BUDGET\",\"Unit\":\"USD\"},\"TimeUnit\":\"MONTHLY\",\"BudgetType\":\"COST\"}" \
    --notifications-with-subscribers "[{\"Notification\":{\"NotificationType\":\"ACTUAL\",\"ComparisonOperator\":\"GREATER_THAN\",\"Threshold\":50,\"ThresholdType\":\"PERCENTAGE\"},\"Subscribers\":[{\"SubscriptionType\":\"EMAIL\",\"Address\":\"$EMAIL\"}]}]"
fi

# EKS Auto Mode ships the isolated-sandbox and confidential-sandbox RuntimeClasses.
# Nitro Sandboxes need Kubernetes 1.36 or later; eksctl's default version is older.
if ! eksctl get cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  eksctl create cluster --name "$CLUSTER" --region "$REGION" --version "$K8S_VERSION" \
    --enable-auto-mode --tags "project=nitro-sbx-blogtest"
fi
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" >/dev/null

# IAM role for the EKS Pod Identity check. It has no permissions: the test only
# calls sts:GetCallerIdentity, which needs none.
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --tags Key=project,Value=nitro-sbx-blogtest \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"]}]}' >/dev/null
fi
kubectl create namespace sbx --dry-run=client -o yaml | kubectl apply -f -
kubectl -n sbx create serviceaccount podid-test --dry-run=client -o yaml | kubectl apply -f -
if [ -z "$(aws eks list-pod-identity-associations --cluster-name "$CLUSTER" --namespace sbx --service-account podid-test --query 'associations[0].associationId' --output text | grep -v None)" ]; then
  aws eks create-pod-identity-association --cluster-name "$CLUSTER" --namespace sbx \
    --service-account podid-test --role-arn "arn:aws:iam::${ACCOUNT}:role/${ROLE}" >/dev/null
fi
kubectl get runtimeclass
echo "setup done"
