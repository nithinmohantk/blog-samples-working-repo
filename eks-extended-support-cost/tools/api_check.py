"""Print what the installed botocore EKS model offers for version and support information."""
import json

import botocore
import botocore.session

eks = botocore.session.get_session().get_service_model("eks")
cluster = list(eks.shape_for("Cluster").members)
print(json.dumps({
    "botocore": botocore.__version__,
    "Cluster fields mentioning support or upgrade": [m for m in cluster if "support" in m.lower() or "upgrade" in m.lower()],
    "operations with Version or Insight in the name": [o for o in eks.operation_names if "Version" in o or "Insight" in o],
    "InsightCategory": eks.shape_for("Category").enum if "Category" in eks.shape_names else None,
}, indent=2))
