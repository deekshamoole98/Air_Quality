"""
Glue Python Shell job script -- paste this into the job's Script tab.

It imports FLAT modules (config.py, clean_transform.py, storage_helpers.py), which
are uploaded individually to S3 and listed in the job's "Python library path".
See infra/aws_deployment.md for why this isn't a zip of packages.

Job parameters:
  --BUCKET         required, the pipeline's S3 bucket
  --PROCESS_DATE   optional, YYYY-MM-DD (defaults to today, UTC)
  --RAW_PREFIX / --CURATED_PREFIX / --AWS_REGION   optional

Optional arguments are checked with `in sys.argv` because getResolvedOptions does
not raise an ordinary exception when an argument is missing: it exits the process
(SystemExit), which `except Exception` does not catch.
All prints use flush=True so they reach CloudWatch, and any failure prints its
full traceback to stdout.
"""
import sys

print("SCRIPT ENTRY: run_transform_glue.py has started executing", flush=True)

import os
import traceback
from datetime import datetime, timezone

try:
    from awsglue.utils import getResolvedOptions
    print("Imported awsglue.utils successfully", flush=True)

    args = getResolvedOptions(sys.argv, ["BUCKET"])  # required
    print(f"Resolved required arg BUCKET={args['BUCKET']}", flush=True)

    os.environ["STORAGE_BACKEND"] = "s3"
    os.environ["S3_BUCKET"] = args["BUCKET"]
    os.environ.setdefault("S3_RAW_PREFIX", "raw")
    os.environ.setdefault("S3_CURATED_PREFIX", "curated")
    os.environ.setdefault("AWS_REGION", "us-east-1")

    for opt_name, env_name in [
        ("RAW_PREFIX", "S3_RAW_PREFIX"),
        ("CURATED_PREFIX", "S3_CURATED_PREFIX"),
        ("AWS_REGION", "AWS_REGION"),
    ]:
        if f"--{opt_name}" in sys.argv:
            val = getResolvedOptions(sys.argv, [opt_name])[opt_name]
            os.environ[env_name] = val
            print(f"Resolved optional arg {opt_name}={val}", flush=True)
        else:
            print(f"Optional arg {opt_name} not passed -- using default {os.environ[env_name]}", flush=True)

    if "--PROCESS_DATE" in sys.argv:
        process_date = getResolvedOptions(sys.argv, ["PROCESS_DATE"])["PROCESS_DATE"]
    else:
        process_date = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    print(f"Resolved PROCESS_DATE={process_date}", flush=True)

    print("Importing clean_transform...", flush=True)
    from clean_transform import run_transform_for_date
    print("Import succeeded. Calling run_transform_for_date...", flush=True)

    df = run_transform_for_date(process_date)
    print(f"Done. {len(df)} curated rows written for {process_date}.", flush=True)

except Exception:
    print("FATAL ERROR in run_transform_glue.py:", flush=True)
    print(traceback.format_exc(), flush=True)
    raise
