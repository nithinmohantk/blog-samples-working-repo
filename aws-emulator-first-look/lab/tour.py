"""Eighteen small experiments against a local AWS endpoint, each recording what actually happened.

    python tour.py emulator:9297 out/tour-emulator.json
    python tour.py moto:5000     out/tour-moto.json

The same script runs against both, so the two columns in the article are like for like. Nothing calls AWS.
"""
import hashlib
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile

import botocore.exceptions

from common import Recorder, session_for

target, out_path = sys.argv[1], sys.argv[2]
session, kw = session_for(target)
client = lambda name: session.client(name, **kw)  # noqa: E731
rec = Recorder(target)
suffix = str(int(time.time()))[-6:]
ACCOUNT = None


def code_of(call) -> str:
    try:
        call()
        return "no error"
    except botocore.exceptions.ClientError as error:
        return error.response["Error"]["Code"]


def identity():
    global ACCOUNT
    who = client("sts").get_caller_identity()
    ACCOUNT = who["Account"]
    return {"account": who["Account"], "arn": who["Arn"]}


def s3_round_trip():
    s3, bucket = client("s3"), f"lab-bucket-{suffix}"
    s3.create_bucket(Bucket=bucket)
    body = bytes(range(256)) * 4096  # 1 MiB
    s3.put_object(Bucket=bucket, Key="data/blob.bin", Body=body)
    got = s3.get_object(Bucket=bucket, Key="data/blob.bin")["Body"].read()
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256(body).hexdigest(), "object came back different"
    listed = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents", [])]
    return {"bytes": len(got), "listed": listed, "missing_key": code_of(lambda: s3.get_object(Bucket=bucket, Key="nope"))}


def s3_versioning():
    s3, bucket = client("s3"), f"lab-versions-{suffix}"
    s3.create_bucket(Bucket=bucket)
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    first = s3.put_object(Bucket=bucket, Key="k", Body=b"one")["VersionId"]
    s3.put_object(Bucket=bucket, Key="k", Body=b"two")
    versions = s3.list_object_versions(Bucket=bucket).get("Versions", [])
    old = s3.get_object(Bucket=bucket, Key="k", VersionId=first)["Body"].read().decode()
    return {"versions": len(versions), "first_version_reads": old}


def s3_presigned_url():
    s3, bucket = client("s3"), f"lab-presign-{suffix}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="hello.txt", Body=b"hello")
    url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": "hello.txt"}, ExpiresIn=60)
    context = ssl.create_default_context(cafile=__import__("os").environ.get("AWS_CA_BUNDLE")) if url.startswith("https") else None
    with urllib.request.urlopen(url, timeout=10, context=context) as response:
        return {"status": response.status, "body": response.read().decode()}


def s3_bucket_policy_deny():
    """A bucket policy that denies every read. On AWS the read that follows is refused."""
    s3, bucket = client("s3"), f"lab-policy-{suffix}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="secret.txt", Body=b"classified")
    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
    return {"read_after_deny_policy": code_of(lambda: s3.get_object(Bucket=bucket, Key="secret.txt"))}


def dynamodb_lifecycle():
    ddb, table = client("dynamodb"), f"lab-orders-{suffix}"
    created = ddb.create_table(TableName=table, BillingMode="PAY_PER_REQUEST",
                               AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                               KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}])
    status_at_once = created["TableDescription"]["TableStatus"]
    write_at_once = code_of(lambda: ddb.put_item(TableName=table, Item={"id": {"S": "early"}}))
    started = time.perf_counter()
    ddb.get_waiter("table_exists").wait(TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
    active_after = round(time.perf_counter() - started, 1)
    ddb.put_item(TableName=table, Item={"id": {"S": "o-1"}, "total": {"N": "42"}})
    again = code_of(lambda: ddb.put_item(TableName=table, Item={"id": {"S": "o-1"}}, ConditionExpression="attribute_not_exists(id)"))
    item = ddb.get_item(TableName=table, Key={"id": {"S": "o-1"}})["Item"]
    return {"status_at_once": status_at_once, "write_at_once": write_at_once, "seconds_to_active": active_after,
            "conditional_put_on_existing": again, "item_total": item["total"]["N"]}


def dynamodb_validation_message():
    ddb = client("dynamodb")
    try:
        ddb.create_table(TableName="ab", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}])
        return {"message": "accepted"}
    except botocore.exceptions.ClientError as error:
        return {"code": error.response["Error"]["Code"], "message": error.response["Error"]["Message"]}


def sqs_visibility_timeout():
    sqs = client("sqs")
    url = sqs.create_queue(QueueName=f"lab-jobs-{suffix}")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="job-1")
    first = sqs.receive_message(QueueUrl=url, VisibilityTimeout=2, AttributeNames=["ApproximateReceiveCount"]).get("Messages", [])
    hidden = sqs.receive_message(QueueUrl=url, WaitTimeSeconds=0).get("Messages", [])
    time.sleep(3)
    second = sqs.receive_message(QueueUrl=url, AttributeNames=["ApproximateReceiveCount"]).get("Messages", [])
    assert first and not hidden and second, f"first={len(first)} hidden={len(hidden)} second={len(second)}"
    return {"first_receive_count": first[0]["Attributes"]["ApproximateReceiveCount"], "while_hidden": len(hidden),
            "after_timeout_receive_count": second[0]["Attributes"]["ApproximateReceiveCount"], "queue_url_host": url.split("/")[2]}


def drain(sqs, url: str, seconds: int = 6) -> list[str]:
    deadline, bodies = time.time() + seconds, []
    while time.time() < deadline and not bodies:
        bodies = [m["Body"] for m in sqs.receive_message(QueueUrl=url, WaitTimeSeconds=1).get("Messages", [])]
    return bodies


def sns_to_sqs():
    sns, sqs = client("sns"), client("sqs")
    url = sqs.create_queue(QueueName=f"lab-fanout-{suffix}")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    topic = sns.create_topic(Name=f"lab-topic-{suffix}")["TopicArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=arn)
    sns.publish(TopicArn=topic, Message="order placed")
    bodies = drain(sqs, url)
    assert bodies, "published, and nothing arrived on the subscribed queue"
    return {"delivered": True, "payload_is_sns_envelope": '"Type"' in bodies[0] and "order placed" in bodies[0]}


def eventbridge_to_sqs():
    events, sqs = client("events"), client("sqs")
    url = sqs.create_queue(QueueName=f"lab-events-{suffix}")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    events.put_rule(Name=f"lab-rule-{suffix}", EventPattern=json.dumps({"source": ["lab.orders"]}))
    events.put_targets(Rule=f"lab-rule-{suffix}", Targets=[{"Id": "q", "Arn": arn}])
    put = events.put_events(Entries=[{"Source": "lab.orders", "DetailType": "OrderPlaced", "Detail": json.dumps({"id": "o-1"})}])
    bodies = drain(sqs, url)
    assert bodies, f"event accepted (failed entries: {put.get('FailedEntryCount')}), and nothing arrived on the target queue"
    return {"delivered": True, "detail_type": json.loads(bodies[0]).get("detail-type")}


def lambda_invoke():
    iam, lam = client("iam"), client("lambda")
    role = iam.create_role(RoleName=f"lab-role-{suffix}", AssumeRolePolicyDocument=json.dumps(
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}))["Role"]["Arn"]
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("app.py", "def handler(event, context):\n    return {'doubled': event['n'] * 2}\n")
    created = lam.create_function(FunctionName=f"lab-fn-{suffix}", Runtime="python3.13", Role=role, Handler="app.handler", Code={"ZipFile": package.getvalue()})
    for _ in range(20):
        if lam.get_function_configuration(FunctionName=f"lab-fn-{suffix}").get("State", "Active") == "Active":
            break
        time.sleep(0.5)
    result = lam.invoke(FunctionName=f"lab-fn-{suffix}", Payload=json.dumps({"n": 21}).encode())
    payload = result["Payload"].read().decode()
    assert '"doubled": 42' in payload or '"doubled":42' in payload, f"function created (state {created.get('State')}), invoke returned {payload[:120]!r} with FunctionError={result.get('FunctionError')}"
    return {"invoke_result": payload}


def step_functions_execution():
    iam, sfn = client("iam"), client("stepfunctions")
    role = iam.create_role(RoleName=f"lab-sfn-{suffix}", AssumeRolePolicyDocument=json.dumps(
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "states.amazonaws.com"}, "Action": "sts:AssumeRole"}]}))["Role"]["Arn"]
    definition = {"StartAt": "Route", "States": {
        "Route": {"Type": "Choice", "Choices": [{"Variable": "$.amountCents", "NumericLessThanEquals": 5000, "Next": "Small"}], "Default": "Large"},
        "Small": {"Type": "Pass", "Parameters": {"outcome": "CREDITED"}, "End": True},
        "Large": {"Type": "Pass", "Parameters": {"outcome": "NEEDS_APPROVAL"}, "End": True}}}
    machine = sfn.create_state_machine(name=f"lab-machine-{suffix}", definition=json.dumps(definition), roleArn=role)["stateMachineArn"]
    execution = sfn.start_execution(stateMachineArn=machine, input=json.dumps({"amountCents": 2500}))["executionArn"]
    described = {}
    for _ in range(20):
        described = sfn.describe_execution(executionArn=execution)
        if described["status"] != "RUNNING":
            break
        time.sleep(0.5)
    assert described.get("status") == "SUCCEEDED" and "CREDITED" in described.get("output", ""), f"status {described.get('status')}, output {described.get('output')}"
    return {"status": described["status"], "output": json.loads(described["output"])}


def secrets_manager():
    sm, name = client("secretsmanager"), f"lab/secret-{suffix}"
    sm.create_secret(Name=name, SecretString="first")
    sm.put_secret_value(SecretId=name, SecretString="second")
    current = sm.get_secret_value(SecretId=name)["SecretString"]
    previous = sm.get_secret_value(SecretId=name, VersionStage="AWSPREVIOUS")["SecretString"]
    return {"current": current, "previous": previous}


def kms_round_trip():
    kms = client("kms")
    key = kms.create_key(Description="lab key")["KeyMetadata"]["KeyId"]
    blob = kms.encrypt(KeyId=key, Plaintext=b"attack at dawn")["CiphertextBlob"]
    plain = kms.decrypt(CiphertextBlob=blob)["Plaintext"]
    assert plain == b"attack at dawn", "decrypt did not return the plaintext"
    return {"ciphertext_bytes": len(blob), "ciphertext_contains_plaintext": b"attack at dawn" in blob}


def ssm_parameter():
    ssm, name = client("ssm"), f"/lab/{suffix}/db-password"
    ssm.put_parameter(Name=name, Value="synthetic-value", Type="SecureString")
    hidden = ssm.get_parameter(Name=name)["Parameter"]["Value"]
    shown = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return {"without_decryption_is_plaintext": hidden == "synthetic-value", "with_decryption": shown}


def kinesis_stream():
    kinesis, name = client("kinesis"), f"lab-stream-{suffix}"
    kinesis.create_stream(StreamName=name, ShardCount=1)
    kinesis.get_waiter("stream_exists").wait(StreamName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
    kinesis.put_record(StreamName=name, Data=b"reading-1", PartitionKey="sensor-a")
    shard = kinesis.describe_stream(StreamName=name)["StreamDescription"]["Shards"][0]["ShardId"]
    iterator = kinesis.get_shard_iterator(StreamName=name, ShardId=shard, ShardIteratorType="TRIM_HORIZON")["ShardIterator"]
    records = kinesis.get_records(ShardIterator=iterator)["Records"]
    assert records and records[0]["Data"] == b"reading-1", f"{len(records)} records read back"
    return {"records": len(records)}


def cloudformation_stack():
    cfn, sqs = client("cloudformation"), client("sqs")
    template = {"Resources": {"Queue": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": f"lab-cfn-{suffix}"}}}}
    cfn.create_stack(StackName=f"lab-stack-{suffix}", TemplateBody=json.dumps(template))
    status = "?"
    for _ in range(30):
        status = cfn.describe_stacks(StackName=f"lab-stack-{suffix}")["Stacks"][0]["StackStatus"]
        if not status.endswith("IN_PROGRESS"):
            break
        time.sleep(0.5)
    exists = any(f"lab-cfn-{suffix}" in u for u in sqs.list_queues(QueueNamePrefix="lab-cfn-").get("QueueUrls", []))
    assert status == "CREATE_COMPLETE" and exists, f"stack status {status}, queue exists: {exists}"
    return {"stack_status": status, "queue_created": exists}


def ec2_control_plane():
    ec2 = client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.20.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.20.1.0/24")["Subnet"]["SubnetId"]
    overlapping = code_of(lambda: ec2.create_subnet(VpcId=vpc, CidrBlock="10.20.1.0/24"))
    return {"vpc": vpc[:4] + "...", "subnet": subnet[:7] + "...", "overlapping_subnet": overlapping}


def unsigned_request():
    """A plain HTTPS request with no signature, as a web page or a stray script would send."""
    url = kw["endpoint_url"] + "/?Action=ListQueues&Version=2012-11-05"
    context = ssl.create_default_context(cafile=__import__("os").environ.get("AWS_CA_BUNDLE")) if url.startswith("https") else None
    try:
        with urllib.request.urlopen(url, timeout=10, context=context) as response:
            return {"status": response.status, "served": True}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "served": False, "body": error.read().decode()[:160]}


for name, experiment in [
    ("01 identity", identity), ("02 s3 round trip, 1 MiB", s3_round_trip), ("03 s3 versioning", s3_versioning), ("04 s3 presigned URL", s3_presigned_url),
    ("05 s3 bucket policy that denies reads", s3_bucket_policy_deny), ("06 dynamodb table lifecycle", dynamodb_lifecycle),
    ("07 dynamodb validation message", dynamodb_validation_message), ("08 sqs visibility timeout", sqs_visibility_timeout),
    ("09 sns to sqs", sns_to_sqs), ("10 eventbridge to sqs", eventbridge_to_sqs), ("11 lambda create and invoke", lambda_invoke),
    ("12 step functions execution", step_functions_execution), ("13 secrets manager versions", secrets_manager), ("14 kms encrypt and decrypt", kms_round_trip),
    ("15 ssm secure parameter", ssm_parameter), ("16 kinesis put and get", kinesis_stream), ("17 cloudformation stack", cloudformation_stack),
    ("18 ec2 vpc and subnet", ec2_control_plane), ("19 unsigned request", unsigned_request),
]:
    rec.run(name, experiment)
rec.save(out_path)
