# Configuration

The `docling-serve` executable allows to configure the server via command line
options as well as environment variables.
Configurations are divided between the settings used for the `uvicorn` asgi
server and the actual app-specific configurations.

 > [!WARNING]
> When the server is running with `reload` or with multiple `workers`, uvicorn
> will spawn multiple subprocesses. This invalidates all the values configured
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
| `-v, --verbose` | `DOCLING_SERVE_LOG_LEVEL` | `WARNING` | Set the verbosity level. CLI: `-v` for INFO, `-vv` for DEBUG. ENV: `WARNING`, `INFO`, or `DEBUG` (case-insensitive). CLI flag takes precedence over ENV. |
| `--artifacts-path` | `DOCLING_SERVE_ARTIFACTS_PATH` | unset | If set to a valid directory, the model weights will be loaded from this path |
|  | `DOCLING_SERVE_STATIC_PATH` | unset | If set to a valid directory, the static assets for the docs and UI will be loaded from this path |
|  | `DOCLING_SERVE_SCRATCH_PATH` |  | If set, this directory will be used as scratch workspace, e.g. storing the results before they get requested. If unset, a temporary created is created for this purpose. |
| `--enable-ui` | `DOCLING_SERVE_ENABLE_UI` | `false` | Enable the demonstrator UI. |
|  | `DOCLING_SERVE_ENABLE_MANAGEMENT_ENDPOINTS` | `false` | If enabled, the `/v1/memory` endpoints will provide memory statistics, otherwise it will return a forbidden 403 error. |
|  | `DOCLING_SERVE_SHOW_VERSION_INFO` | `true` | If enabled, the `/version` endpoint will provide the Docling package versions, otherwise it will return a forbidden 403 error. |
|  | `DOCLING_SERVE_ENABLE_REMOTE_SERVICES` | `false` | Allow pipeline components making remote connections. For example, this is needed when using a vision-language model via APIs. |
|  | `DOCLING_SERVE_ALLOW_EXTERNAL_PLUGINS` | `false` | Allow the selection of third-party plugins. |
|  | `DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG` | `false` | Allow users to specify a fully custom VLM pipeline configuration (`vlm_pipeline_custom_config`). When `false`, only presets are accepted. |
|  | `DOCLING_SERVE_ALLOW_CUSTOM_PICTURE_DESCRIPTION_CONFIG` | `false` | Allow users to specify a fully custom picture description configuration. When `false`, only presets are accepted. |
|  | `DOCLING_SERVE_ALLOW_CUSTOM_CODE_FORMULA_CONFIG` | `false` | Allow users to specify a fully custom code/formula configuration. When `false`, only presets are accepted. |
|  | `DOCLING_SERVE_SINGLE_USE_RESULTS` | `true` | If true, results can be accessed only once. If false, the results accumulate in the scratch directory. |
|  | `DOCLING_SERVE_RESULT_REMOVAL_DELAY` | `300` | When `DOCLING_SERVE_SINGLE_USE_RESULTS` is active, this is the delay before results are removed from the task registry. |
|  | `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT` | `604800` (7 days) | The maximum time for processing a document. |
|  | `DOCLING_SERVE_MAX_NUM_PAGES` |  | The maximum number of pages for a document to be processed. |
|  | `DOCLING_SERVE_MAX_FILE_SIZE` |  | The maximum file size for a document to be processed. |
|  | `DOCLING_SERVE_SYNC_POLL_INTERVAL` | `2` | Number of seconds to sleep between polling the task status in the sync endpoints. |
|  | `DOCLING_SERVE_MAX_SYNC_WAIT` | `120` | Max number of seconds a synchronous endpoint is waiting for the task completion. |
|  | `DOCLING_SERVE_LOAD_MODELS_AT_BOOT` | `True` | If enabled, the models for the default options will be loaded at boot. |
|  | `DOCLING_SERVE_OPTIONS_CACHE_SIZE` | `2` | How many DocumentConveter objects (including their loaded models) to keep in the cache. |
|  | `DOCLING_SERVE_QUEUE_MAX_SIZE` | | Size of the pages queue. Potentially so many pages opened at the same time. |
|  | `DOCLING_SERVE_OCR_BATCH_SIZE` | | Batch size for the OCR stage. |
|  | `DOCLING_SERVE_LAYOUT_BATCH_SIZE` | | Batch size for the layout detection stage. |
|  | `DOCLING_SERVE_TABLE_BATCH_SIZE` | | Batch size for the table structure stage. |
|  | `DOCLING_SERVE_BATCH_POLLING_INTERVAL_SECONDS` | | Wait time for gathering pages before starting a stage processing. |
|  | `DOCLING_SERVE_CORS_ORIGINS` | `["*"]` | A list of origins that should be permitted to make cross-origin requests. |
|  | `DOCLING_SERVE_CORS_METHODS` | `["*"]` | A list of HTTP methods that should be allowed for cross-origin requests. |
|  | `DOCLING_SERVE_CORS_HEADERS` | `["*"]` | A list of HTTP request headers that should be supported for cross-origin requests. |
|  | `DOCLING_SERVE_API_KEY` | | If specified, all the API requests must contain the header `X-Api-Key` with this value. |
|  | `DOCLING_SERVE_ENG_KIND` | `local` | The compute engine to use for the async tasks. Possible values are `local`, `rq` and `kfp`. See below for more configurations of the engines. |

### Docling configuration

Some Docling settings, mostly about performance, are exposed as environment variable which can be used also when running Docling Serve.

| ENV | Default | Description |
| ----|---------|-------------|
| `DOCLING_NUM_THREADS` | `4` | Number of concurrent threads used for the `torch` CPU execution. |
| `DOCLING_DEVICE` | | Device used for the model execution. Valid values are `cpu`, `cuda`, `mps`. When unset, the best device is chosen. For CUDA-enabled environments, you can choose which GPU using the syntax `cuda:0`, `cuda:1`, ... |
| `DOCLING_PERF_PAGE_BATCH_SIZE` | `4` | Number of pages processed in the same batch. |
| `DOCLING_PERF_ELEMENTS_BATCH_SIZE` | `8` | Number of document items/elements processed in the same batch during enrichment. |
| `DOCLING_DEBUG_PROFILE_PIPELINE_TIMINGS` | `false` | When enabled, Docling will provide detailed timings information. |


### Compute engine

Docling Serve can be deployed with several possible of compute engine.
The selected compute engine will be running all the async jobs.

#### Local engine

The following table describes the options to configure the Docling Serve local engine.

| ENV | Default | Description |
|-----|---------|-------------|
| `DOCLING_SERVE_ENG_LOC_NUM_WORKERS` | 2 | Number of workers/threads processing the incoming tasks. |
| `DOCLING_SERVE_ENG_LOC_SHARE_MODELS` | False | If true, each process will share the same models among all thread workers. Otherwise, one instance of the models is allocated for each worker thread. |

#### RQ engine

The following table describes the options to configure the Docling Serve RQ engine.

| ENV | Default | Description |
|-----|---------|-------------|
| `DOCLING_SERVE_ENG_RQ_REDIS_URL` | (required) | The connection Redis url, e.g. `redis://localhost:6373/` |
| `DOCLING_SERVE_ENG_RQ_RESULTS_PREFIX` | `docling:results` | The prefix used for storing the results in Redis. |
| `DOCLING_SERVE_ENG_RQ_SUB_CHANNEL` | `docling:updates` | The channel key name used for storing communicating updates between the workers and the orchestrator. |
| `DOCLING_SERVE_ENG_RQ_RESULTS_TTL` | `14400` (4 hours) | Time To Live (in seconds) for RQ job results in Redis. This controls how long job results are kept before being automatically deleted. |
| `DOCLING_SERVE_ENG_RQ_REDIS_MAX_CONNECTIONS` | `50` | Maximum number of connections in the Redis connection pool. Increase this value when scaling to many RQ workers (e.g., 100 for 10+ workers). |
| `DOCLING_SERVE_ENG_RQ_REDIS_SOCKET_TIMEOUT` | `None` | Socket timeout in seconds for Redis operations. If not set, uses Redis client default. Set to a value (e.g., 5.0) if you experience timeout issues. |
| `DOCLING_SERVE_ENG_RQ_REDIS_SOCKET_CONNECT_TIMEOUT` | `None` | Socket connect timeout in seconds for establishing Redis connections. If not set, uses Redis client default. Set to a value (e.g., 5.0) for slow networks. |

**Scaling Recommendations for RQ Engine:**

- **Small deployments (1-4 workers):** Default settings (50 connections) are sufficient
- **Medium deployments (5-10 workers):** Set `DOCLING_SERVE_ENG_RQ_REDIS_MAX_CONNECTIONS=100`
- **Large deployments (10+ workers):** Set `DOCLING_SERVE_ENG_RQ_REDIS_MAX_CONNECTIONS=150-200`
- **Timeout settings:** Only set if experiencing connection issues. Start with 5.0 seconds for both timeouts.
- Ensure your Redis server's `maxclients` setting can accommodate all connections from all docling-serve instances and RQ workers

#### KFP engine

The following table describes the options to configure the Docling Serve KFP engine.

| ENV | Default | Description |
|-----|---------|-------------|
| `DOCLING_SERVE_ENG_KFP_ENDPOINT` |  | Must be set to the Kubeflow Pipeline endpoint. When using the in-cluster deployment, make sure to use the cluster endpoint, e.g. `https://NAME.NAMESPACE.svc.cluster.local:8888`  |
| `DOCLING_SERVE_ENG_KFP_TOKEN` |  | The authentication token for KFP. For in-cluster deployment, the app will load automatically the token of the ServiceAccount. |
| `DOCLING_SERVE_ENG_KFP_CA_CERT_PATH` |  | Path to the CA certificates for the KFP endpoint. For in-cluster deployment, the app will load automatically the internal CA. |
| `DOCLING_SERVE_ENG_KFP_SELF_CALLBACK_ENDPOINT` |  | If set, it enables internal callbacks providing status update of the KFP job. Usually something like `https://NAME.NAMESPACE.svc.cluster.local:5001/v1/callback/task/progress`. |
| `DOCLING_SERVE_ENG_KFP_SELF_CALLBACK_TOKEN_PATH` |  | The token used for authenticating the progress callback. For cluster-internal workloads, use `/run/secrets/kubernetes.io/serviceaccount/token`. |
| `DOCLING_SERVE_ENG_KFP_SELF_CALLBACK_CA_CERT_PATH` |  | The CA certificate for the progress callback. For cluster-inetrnal workloads, use `/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`. |

### Gradio UI

When using Gradio UI and using the option to output conversion as file, Gradio uses cache to prevent files to be overwritten ([more info here](https://www.gradio.app/guides/file-access#the-gradio-cache)), and we defined the cache clean frequency of one hour to clean files older than 10hours. For situations that files need to be available to download from UI older than 10 hours, there is two options:

- Increase the older age of files to clean [here](https://github.com/docling-project/docling-serve/blob/main/docling_serve/gradio_ui.py#L483) to suffice the age desired;
- Or set the clean up manually by defining the temporary dir of Gradio to use the same as `DOCLING_SERVE_SCRATCH_PATH` absolute path. This can be achieved by setting the environment variable `GRADIO_TEMP_DIR`, that can be done via command line `export GRADIO_TEMP_DIR="<same_path_as_scratch>"` or in `Dockerfile` using `ENV GRADIO_TEMP_DIR="<same_path_as_scratch>"`. After this, set the clean of cache to `None` [here](https://github.com/docling-project/docling-serve/blob/main/docling_serve/gradio_ui.py#L483). Now, the clean up of `DOCLING_SERVE_SCRATCH_PATH` will also clean the Gradio temporary dir. (If you use this option, please remember when reversing changes to remove the environment variable `GRADIO_TEMP_DIR`, otherwise may lead to files not be available to download).

### Telemetry

THe following table describes the telemetry options for the Docling Serve app. Some deployment examples are available in [examples/OTEL.md](../examples/OTEL.md).

ENV | Default | Description |
|-----|---------|-------------|
| `DOCLING_SERVE_OTEL_ENABLE_METRICS` | true | Enable metrics collection. |
| `DOCLING_SERVE_OTEL_ENABLE_TRACES` | false | Enable trace collection. Requires a valid value for `OTEL_EXPORTER_OTLP_ENDPOINT`. |
| `DOCLING_SERVE_OTEL_ENABLE_PROMETHEUS` | true | Enable Prometheus /metrics endpoint. |
| `DOCLING_SERVE_OTEL_ENABLE_OTLP_METRICS` | `false` | Enable OTLP metrics export. |
| `DOCLING_SERVE_OTEL_SERVICE_NAME` | docling-serve | Service identification. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` |  | OTLP endpoint (for traces and optional metrics). |
