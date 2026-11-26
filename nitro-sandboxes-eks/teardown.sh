#!/usr/bin/env bash
# Removes everything setup.sh created and checks that nothing tagged is left.
set -uo pipefail
REGION="${REGION:-eu-west-1}"
CLUSTER="${CLUSTER:-nitro-sbx-blogtest}"
ROLE="${CLUSTER}-podid"
export AWS_REGION="$REGION" PATH="$HOME/bin:$PATH"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

kubectl delete namespace sbx --wait=true --timeout=300s 2>/dev/null
for id in $(aws eks list-pod-identity-associations --cluster-name "$CLUSTER" --query 'associations[].associationId' --output text 2>/dev/null); do
  aws eks delete-pod-identity-association --cluster-name "$CLUSTER" --association-id "$id" >/dev/null
done
eksctl delete cluster --name "$CLUSTER" --region "$REGION" --wait
aws iam delete-role --role-name "$ROLE" 2>/dev/null
aws budgets delete-budget --account-id "$ACCOUNT" --budget-name "$CLUSTER" 2>/dev/null

echo "--- left over (all should be empty) ---"
echo "clusters:      $(aws eks list-clusters --query "clusters[?@=='$CLUSTER']" --output text)"
echo "instances:     $(aws ec2 describe-instances --filters Name=tag:eks:eks-cluster-name,Values=$CLUSTER Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text)"
echo "nat gateways:  $(aws ec2 describe-nat-gateways --filter Name=tag:alpha.eksctl.io/cluster-name,Values=$CLUSTER Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId' --output text)"
echo "elastic ips:   $(aws ec2 describe-addresses --filters Name=tag:alpha.eksctl.io/cluster-name,Values=$CLUSTER --query 'Addresses[].AllocationId' --output text)"
echo "vpcs:          $(aws ec2 describe-vpcs --filters Name=tag:alpha.eksctl.io/cluster-name,Values=$CLUSTER --query 'Vpcs[].VpcId' --output text)"
echo "iam role:      $(aws iam get-role --role-name "$ROLE" --query Role.RoleName --output text 2>/dev/null)"
