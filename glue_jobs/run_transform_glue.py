"""
Glue Python Shell job entrypoint.

Deliberately thin: it resolves job parameters, sets the env vars config.py
reads, and calls the same run_transform_for_date() that's already covered
by tests/test_clean_transform.py. The cleaning logic itself lives in one
place (transform/clean_transform.py) whether it runs locally, via
`python lambda_handler.py --local-transform`, or here in Glue.

Deploy: zip up config.py, transform/, and storage/ and upload to S3, then
point the job's "Python library path" (--extra-py-files) at that zip. See
infra/glue_setup_guide.md for the full console walkthrough.

Job parameters:
  --BUCKET          S3 bucket the pipeline uses (sets config.S3_BUCKET)
  --PROCESS_DATE    Date to process, YYYY-MM-DD (defaults to today, UTC)
  --RAW_PREFIX      Optional, defaults to "raw"
  --CURATED_PREFIX  Optional, defaults to "curated"
"""
import os
import sys
from datetime import datetime, timezone

from awsglue.utils import getResolvedOptions

# Env vars must be set BEFORE config.py is imported anywhere below,
# since config.py reads most of them at import time.
args = getResolvedOptions(sys.argv, ["BUCKET"])

os.environ["STORAGE_BACKEND"] = "s3"
os.environ["S3_BUCKET"] = args["BUCKET"]
os.environ.setdefault("S3_RAW_PREFIX", "raw")
os.environ.setdefault("S3_CURATED_PREFIX", "curated")

for opt_name, env_name in [
    ("RAW_PREFIX", "S3_RAW_PREFIX"),
    ("CURATED_PREFIX", "S3_CURATED_PREFIX"),
    ("AWS_REGION", "AWS_REGION"),
]:
    try:
        os.environ[env_name] = getResolvedOptions(sys.argv, [opt_name])[opt_name]
    except Exception:
        pass  # not passed as a job argument — default already set above

try:
    process_date = getResolvedOptions(sys.argv, ["PROCESS_DATE"])["PROCESS_DATE"]
except Exception:
    process_date = f"{datetime.now(timezone.utc):%Y-%m-%d}"

from transform.clean_transform import run_transform_for_date  # noqa: E402

print(f"Running transform for date={process_date} against bucket={args['BUCKET']}")
df = run_transform_for_date(process_date)
print(f"Done. {len(df)} curated rows written for {process_date}.")
