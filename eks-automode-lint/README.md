# eks-automode-lint

Sample code for the dataa.dev article *Amazon EKS Auto Mode: How AWS Finally Solved the Node Management Problem* (14 February 2026).

## What is here

- `manifests/`: a starting set for an EKS Auto Mode cluster.
  - `nodeclass.yaml`: a custom `NodeClass` (`eks.amazonaws.com/v1`) with private subnets, a node role and KMS-encrypted ephemeral storage.
  - `nodepools.yaml`: an on-demand general-purpose `NodePool` and a tainted Spot pool for batch work, using `eks.amazonaws.com/*` instance labels.
  - `storageclass.yaml`: a gp3 `StorageClass` on the Auto Mode provisioner `ebs.csi.eks.amazonaws.com`.
  - `ingressclass.yaml`: `IngressClassParams` and an `IngressClass` for internal Application Load Balancers through `eks.amazonaws.com/alb`.
- `automode_lint.py`: reads existing manifests and reports what must change before a move to Auto Mode: Karpenter `EC2NodeClass` objects, unsupported `NodeClass` fields, `karpenter.k8s.aws/*` instance labels, Windows requirements, `expireAfter` above the 21-day maximum node lifetime, the self-managed EBS CSI provisioner and Load Balancer Controller, unsupported Ingress annotations, and workloads pinned to managed node groups.

## Run it

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python automode_lint.py path/to/your/manifests    # exit code 1 if there are errors
pytest -q
kubectl apply -f manifests/                      # on an Auto Mode cluster, after editing names and tags
```

## What has been verified

- 12 pytest tests pass on Python 3.13 with `pyyaml==6.0.3` and `pytest==9.0.2`, including a check that the files in `manifests/` lint clean.
- The manifests follow the field names in the EKS Auto Mode user guide. They have not been applied to a cluster by these tests; set the role name, subnet and security group tags, and KMS alias for your account before applying.
