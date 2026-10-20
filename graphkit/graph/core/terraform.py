"""Write a small Terraform folder that creates (or updates) the graph, and run it.

BigQuery: a `google_bigquery_job` runs the DDL. Its job id includes a hash of
the DDL, so any change to the graph makes Terraform run the new version.

Spanner: a `terraform_data` resource runs `gcloud spanner databases ddl update`
whenever the DDL changes. (If Terraform already owns your Spanner database,
you can instead add the statement to its `ddl` list.)
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from graphkit.graph.core.ddl import create_graph_ddl
from graphkit.graph.core.model import GraphSpec

VERSIONS_TF = """terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }
}
"""

BIGQUERY_TF = """provider "google" {{
  project = "{project}"
}}

locals {{
  ddl = file("${{path.module}}/graph.sql")
}}

# Created by graphkit. Re-run `graphkit terraform` after editing the graph.
resource "google_bigquery_job" "property_graph" {{
  # A new job id each time the DDL changes, so Terraform runs the new version.
  job_id   = "graphkit_{name}_${{substr(sha256(local.ddl), 0, 16)}}"
  location = "{region}"

  query {{
    query              = local.ddl
    use_legacy_sql     = false
    create_disposition = "" # must be empty for DDL statements
    write_disposition  = ""
  }}
}}

output "graph" {{
  value = "{graph}"
}}
"""

SPANNER_TF = """locals {{
  ddl = file("${{path.module}}/graph.sql")
}}

# Created by graphkit. Re-run `graphkit terraform` after editing the graph.
resource "terraform_data" "property_graph" {{
  triggers_replace = sha256(local.ddl)

  provisioner "local-exec" {{
    command = "gcloud spanner databases ddl update {database} --instance={instance} --project={project} --ddl-file=${{path.module}}/graph.sql"
  }}
}}

output "graph" {{
  value = "{graph}"
}}
"""


def write_terraform(spec: GraphSpec, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ddl = create_graph_ddl(spec)
    (out / "graph.sql").write_text(ddl + "\n")
    (out / "versions.tf").write_text(VERSIONS_TF)
    loc = spec.location
    safe = re.sub(r"[^A-Za-z0-9_]", "_", spec.name)
    if spec.backend == "bigquery":
        main = BIGQUERY_TF.format(
            project=loc["project"], name=safe, region=loc.get("region", "US"),
            graph=f"{loc.get('data_project') or loc['project']}.{loc['dataset']}.{spec.name}",
        )
    elif spec.backend == "spanner":
        main = SPANNER_TF.format(project=loc["project"], instance=loc["instance"],
                                 database=loc["database"], graph=spec.name)
    else:
        raise ValueError(f"Terraform output needs bigquery or spanner, not {spec.backend}.")
    (out / "main.tf").write_text(main)
    return out


def terraform_available() -> bool:
    return shutil.which("terraform") is not None


def run_terraform(out_dir: str | Path, action: str = "plan") -> tuple[int, str]:
    """Run `terraform init` then `plan` or `apply`. Returns (exit code, combined output).

    Only call with action="apply" after a developer has confirmed the change.
    """
    if action not in ("plan", "apply"):
        raise ValueError("action must be plan or apply")
    if not terraform_available():
        return 127, "Terraform isn't installed. Install it, or run the commands in the README by hand."
    log = []
    steps = [["init", "-input=false", "-no-color"]]
    steps.append(["plan", "-input=false", "-no-color"] if action == "plan"
                 else ["apply", "-input=false", "-no-color", "-auto-approve"])
    for args in steps:
        p = subprocess.run(["terraform", f"-chdir={out_dir}", *args], capture_output=True, text=True)
        log.append(f"$ terraform {' '.join(args)}\n{p.stdout}{p.stderr}")
        if p.returncode != 0:
            return p.returncode, "\n".join(log)
    return 0, "\n".join(log)
