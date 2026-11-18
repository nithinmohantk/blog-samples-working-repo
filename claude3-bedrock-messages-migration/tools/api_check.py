"""What the installed SDKs offered: Bedrock Runtime operations and Anthropic SDK resources."""
import json

import anthropic
import botocore
import botocore.session

client = anthropic.AnthropicBedrock(aws_access_key="x", aws_secret_key="x", aws_region="us-east-1")
runtime = botocore.session.get_session().get_service_model("bedrock-runtime")
print(json.dumps({
    "botocore": botocore.__version__,
    "bedrock-runtime operations": runtime.operation_names,
    "anthropic": anthropic.__version__,
    "AnthropicBedrock resources": [n for n in ("completions", "messages") if hasattr(client, n)],
}, indent=2))
