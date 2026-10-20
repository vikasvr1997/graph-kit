# Cloud Run deployment

The React UI and FastAPI API run in one container and one Cloud Run service.
Chat is disabled by default (`CHAT_ENABLED=false`); graph creation remains enabled.
Set `CHAT_ENABLED=true` and restart to restore the assistant.
The configurable entrypoint is `graphkit.api.application:app`. Set
`GRAPHKIT_ENABLED=false` and `CHAT_ENABLED=true` to run only the assistant; see [CHAT.md](CHAT.md) for
the separate chat-only Dockerfile, evaluations and guardrails.
FastAPI serves `graphkit-web/dist` at `/` and the API at `/api/*`.
Local Vite development proxies `/api` to port 8765. Set `VITE_API_BASE_URL`
at frontend build time only when using a separate backend.

## Build

Build the frontend first. Vite reads the local browser configuration from
`graphkit-web/.env.local`; only the compiled public browser configuration is
included in the image. Never put server secrets in `VITE_*` variables.

```sh
cd graphkit-web
npm ci
npm run build
cd ..
docker build -t graphkit .
docker run --rm -p 8080:8080 graphkit
```

The Docker and Cloud Build upload contexts use allowlists to exclude local
credentials, environment files, datasets and existing workspaces.

## Deployed preview (2026-10-19)

- Project: `premium-odyssey-508202-k9`
- Service: `graphkit`, region: `us-central1`
- URL: https://graphkit-100634033534.us-central1.run.app
- Private: Cloud Run IAM authentication is required.
- Workspace bucket: `gs://premium-odyssey-508202-k9-graphkit-workspaces`
- Runtime identity: `graphkit-run@premium-odyssey-508202-k9.iam.gserviceaccount.com`
- `GRAPHKIT_HOME=/workspaces`, mounted from the bucket with `implicit-dirs`.
- One maximum instance, one concurrent request, 1 CPU, 1 GiB memory.

Open the private service in a normal browser through an authenticated proxy:

```sh
gcloud run services proxy graphkit \
  --project=premium-odyssey-508202-k9 --region=us-central1 --port=8085
```

Then visit http://127.0.0.1:8085. The application is running on Cloud Run;
the local process only proxies authenticated requests.

## Scope and limitations

The included synthetic SQLite demo is generated inside the image and works
without warehouse access. Its `SupplyChain` scan is saved in the workspace
bucket. Local files on your laptop are not accessible to Cloud Run.

The dedicated runtime identity has access to its workspace bucket only.
BigQuery, Spanner, Vertex AI, Firestore and Model Armor workflows require
their own resource permissions and configuration. Assistant Google sign-in
also requires an authorized Firebase browser domain. These integrations were
not validated by this demo deployment.

Terraform is not installed in this preview image, so Terraform plan/apply
requires extending the image and granting the relevant infrastructure roles.
Cloud Storage FUSE is not a general POSIX filesystem; SQLite stays in the
container, not on the mount. Workspace writes have no application-level
locking. The one-instance/request configuration is for preview use; concurrent
production editing needs transactional persistence and coordination, including
across overlapping deployment revisions.

The service remains private because workflow API routes currently have no
application-level authorization. Minimum instances defaults to zero; Cloud Run,
Cloud Build, Artifact Registry and Cloud Storage usage can incur charges.
