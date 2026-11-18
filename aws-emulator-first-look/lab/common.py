"""Shared plumbing for the lab scripts: a boto3 session aimed at a local endpoint, and a result recorder."""
import json
import os
import pathlib
import time

import boto3
import botocore.config
import botocore.exceptions


def session_for(target: str) -> tuple[boto3.session.Session, dict]:
    """target is 'emulator:<port>' or 'moto:<port>'. Returns a session and the client keyword arguments.

    For the emulator, everything comes from the files it writes at start-up, exactly as its user guide
    describes. For moto, throwaway keys are enough: it does not check them.
    """
    kind, port = target.split(":")
    if kind == "emulator":
        home = pathlib.Path.home() / ".aws" / "emulator" / port
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = str(home / "emulator_credentials")
        os.environ["AWS_CONFIG_FILE"] = str(home / "config")
        os.environ["AWS_CA_BUNDLE"] = str(home / "ca.pem")
        os.environ["AWS_DISABLE_HOST_PREFIX_INJECTION"] = "true"
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
            os.environ.pop(name, None)
        endpoint = f"https://127.0.0.1:{port}"
    else:
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"       # throwaway; moto ignores it
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"   # throwaway; moto ignores it
        for name in ("AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE", "AWS_CA_BUNDLE"):
            os.environ.pop(name, None)
        endpoint = f"http://127.0.0.1:{port}"
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    config = botocore.config.Config(retries={"max_attempts": 1}, connect_timeout=5, read_timeout=30, inject_host_prefix=False)
    return boto3.session.Session(region_name="us-east-1"), {"endpoint_url": endpoint, "config": config}


def classify(error: Exception) -> str:
    """One short phrase for what went wrong, with 501 called out since it is the emulator's 'not built yet'."""
    if isinstance(error, botocore.exceptions.ClientError):
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = error.response.get("Error", {}).get("Code", "?")
        return f"not implemented (501 {code})" if status == 501 else f"error {status} {code}"
    return f"{type(error).__name__}"


class Recorder:
    def __init__(self, target: str):
        self.target, self.rows = target, []

    def run(self, name: str, experiment) -> None:
        started = time.perf_counter()
        try:
            observed = experiment()
            outcome = "works"
        except AssertionError as error:
            observed, outcome = {"differs": str(error)}, "differs"
        except Exception as error:  # noqa: BLE001 - every failure is a result here
            observed, outcome = {"error": classify(error), "detail": str(error)[:240]}, "fails"
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        self.rows.append({"experiment": name, "outcome": outcome, "ms": elapsed, "observed": observed})
        print(f"{outcome:8} {elapsed:9.1f} ms  {name}  {json.dumps(observed, default=str)[:260]}", flush=True)

    def save(self, path: str) -> None:
        pathlib.Path(path).write_text(json.dumps({"target": self.target, "rows": self.rows}, indent=2, default=str) + "\n")
