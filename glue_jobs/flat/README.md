# Why these files are flat

These are the files deployed to AWS Glue. They mirror `transform/` and `storage/` but sit at one
level with no package folders, because a Glue **Python Shell** job can't import a zip of packages
(see `infra/aws_deployment.md`, "Gotchas"). The cleaning logic is the same; only the import paths differ.

| File | Where it goes |
|---|---|
| `run_transform_glue.py` | Pasted into the Glue job's **Script** tab |
| `config.py`, `clean_transform.py`, `storage_helpers.py` | Uploaded individually to `s3://<bucket>/glue-deps/` and listed in the job's **Python library path** |

If you change cleaning logic in `transform/clean_transform.py`, make the same change here and re-upload.
