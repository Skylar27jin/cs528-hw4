"""Structured stdout plus explicit Cloud Logging API writes on Compute Engine."""
import json
import os
from functools import lru_cache

@lru_cache(maxsize=1)
def logger():
    from google.cloud import logging
    from google.cloud.logging_v2.resource import Resource
    resource = Resource(type="gce_instance", labels={
        "project_id": os.environ["GOOGLE_CLOUD_PROJECT"],
        "instance_id": os.environ["INSTANCE_ID"], "zone": os.environ["ZONE"],
    })
    return logging.Client().logger("hw4-errors", resource=resource)

def emit(event, severity):
    print(json.dumps({"severity": severity, **event}), flush=True)
    if os.getenv("CLOUD_LOGGING", "0") == "1":
        try:
            logger().log_struct(event, severity=severity)
        except Exception as error:
            # Keep serving, but make logging failures visible in systemd journal.
            print(json.dumps({"severity": "ERROR", "message": "Cloud Logging write failed",
                              "error_type": type(error).__name__}), flush=True)
