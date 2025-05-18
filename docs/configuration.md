# Configuration

The `docling-serve` executable allows to configure the server via command line
options as well as environment variables.
Configurations are divided between the settings used for the `uvicorn` asgi
server and the actual app-specific configurations.

 > [!WARNING]
> When the server is running with `reload` or with multiple `workers`, uvicorn
> will spawn multiple subprocessed. This invalides all the values configured
> via the CLI command line options. Please use environment variables in this
> type of deployments.

## Webserver configuration

The following table shows the options which are propagated directly to the
`uvicorn` webserver runtime.

| CLI option | ENV | Default | Description |
| -----------|-----|---------|-------------|
| `--host` | `UVICORN_HOST` | `0.0.0.0` for `run`, `localhost` for `dev` | THe host to serve on. |
| `--port` | `UVICORN_PORT` | `5001` | The port to serve on. |
| `--reload` | `UVICORN_RELOAD` | `false` for `run`, `true` for `dev` | Enable auto-reload of the server when (code) files change. |
| `--workers` | `UVICORN_WORKERS` | `1` | Use multiple worker processes. |
| `--root-path` | `UVICORN_ROOT_PATH` | `""` | The root path is used to tell your app that it is being served to the outside world with some |
| `--proxy-headers` | `UVICORN_PROXY_HEADERS` | `true` | Enable/Disable X-Forwarded-Proto, X-Forwarded-For, X-Forwarded-Port to populate remote address info. |
| `--timeout-keep-alive` | `UVICORN_TIMEOUT_KEEP_ALIVE` | `60` | Timeout for the server response. |
| `--ssl-certfile` | `UVICORN_SSL_CERTFILE` |  | SSL certificate file. |
| `--ssl-keyfile` | `UVICORN_SSL_KEYFILE` |  | SSL key file. |
| `--ssl-keyfile-password` | `UVICORN_SSL_KEYFILE_PASSWORD` |  | SSL keyfile password. |

## Docling Serve configuration

THe following table describes the options to configure the Docling Serve app.

| CLI option | ENV | Default | Description |
| -----------|-----|---------|-------------|
| `--artifacts-path` | `DOCLING_SERVE_ARTIFACTS_PATH` | unset | If set to a valid directory, the model weights will be loaded from this path |
|  | `DOCLING_SERVE_STATIC_PATH` | unset | If set to a valid directory, the static assets for the docs and ui will be loaded from this path |
|  | `DOCLING_SERVE_SCRATCH_PATH` |  | If set, this directory will be used as scratch workspace, e.g. storing the results before they get requested. If unset, a temporary created is created for this purpose. |
| `--enable-ui` | `DOCLING_SERVE_ENABLE_UI` | `false` | Enable the demonstrator UI. |
|  | `DOCLING_SERVE_ENABLE_REMOTE_SERVICES` | `false` | Allow pipeline components making remote connections. For example, this is needed when using a vision-language model via APIs. |
|  | `DOCLING_SERVE_ALLOW_EXTERNAL_PLUGINS` | `false` | Allow the selection of third-party plugins. |
|  | `DOCLING_SERVE_SINGLE_USE_RESULTS` | `true` | If true, results can be accessed only once. If false, the results accumulate in the scratch directory. |
|  | `DOCLING_SERVE_RESULT_REMOVAL_DELAY` | `300` | When `DOCLING_SERVE_SINGLE_USE_RESULTS` is active, this is the delay before results are removed from the task registry. |
|  | `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT` | `604800` (7 days) | The maximum time for processing a document. |
|  | `DOCLING_SERVE_MAX_NUM_PAGES` |  | The maximum number of pages for a document to be processed. |
|  | `DOCLING_SERVE_MAX_FILE_SIZE` |  | The maximum file size for a document to be processed. |
|  | `DOCLING_SERVE_MAX_SYNC_WAIT` | `120` | Max number of seconds a synchronous endpoint is waiting for the task completion. |
|  | `DOCLING_SERVE_OPTIONS_CACHE_SIZE` | `2` | How many DocumentConveter objects (including their loaded models) to keep in the cache. |
|  | `DOCLING_SERVE_CORS_ORIGINS` | `["*"]` | A list of origins that should be permitted to make cross-origin requests. |
|  | `DOCLING_SERVE_CORS_METHODS` | `["*"]` | A list of HTTP methods that should be allowed for cross-origin requests. |
|  | `DOCLING_SERVE_CORS_HEADERS` | `["*"]` | A list of HTTP request headers that should be supported for cross-origin requests. |
|  | `DOCLING_SERVE_ENG_KIND` | `local` | The compute engine to use for the async tasks. Possible values are `local` and `kfp`. See below for more configurations of the engines. |

### Compute engine

Docling Serve can be deployed with several possible of compute engine.
The selected compute engine will be running all the async jobs.

#### Local engine

The following table describes the options to configure the Docling Serve KFP engine.

| ENV | Default | Description |
|-----|---------|-------------|
| `DOCLING_SERVE_ENG_LOC_NUM_WORKERS` | 2 | Number of workers/threads processing the incoming tasks. |

#### KFP engine

The following table describes the options to configure the Docling Serve KFP engine.

| ENV | Default | Description |
|-----|---------|-------------|
| `DOCLING_SERVE_ENG_KFP_ENDPOINT` |  | Must be set to the Kubeflow Pipeline endpoint. When using the in-cluster deployment, make sure to use the cluster endpoint, e.g. `https://NAME.NAMESPACE.svc.cluster.local:8888`  |
| `DOCLING_SERVE_ENG_KFP_TOKEN` |  | The authentication token for KFP. For in-cluster deployment, the app will load automatically the token of the ServiceAccount. |
| `DOCLING_SERVE_ENG_KFP_CA_CERT_PATH` |  | Path to the CA certificates for the KFP endpoint. For in-cluster deployment, the app will load automatically the internal CA. |
| `DOCLING_SERVE_ENG_KFP_SELF_CALLBACK_ENDPOINT` |  | If set, it enables internal callbacks providing status update of the KFP job. Usually something like `https://NAME.NAMESPACE.svc.cluster.local:5001/v1alpha/callback/task/progress`. |
| `DOCLING_SERVE_ENG_KFP_SELF_CALLBACK_TOKEN_PATH` |  | The token used for authenticating the progress callback. For cluster-internal workloads, use `/run/secrets/kubernetes.io/serviceaccount/token`. |
| `DOCLING_SERVE_ENG_KFP_SELF_CALLBACK_CA_CERT_PATH` |  | The CA certificate for the progress callback. For cluster-inetrnal workloads, use `/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`. |
