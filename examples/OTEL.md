# OpenTelemetry Integration for Docling Serve

Docling Serve includes built-in OpenTelemetry instrumentation for metrics and distributed tracing.

## Features

- **Metrics**: Prometheus-compatible metrics endpoint at `/metrics`
- **Traces**: OTLP trace export to OpenTelemetry collectors
- **FastAPI Auto-instrumentation**: HTTP request metrics and traces
- **RQ Metrics**: Worker and job queue metrics (when using RQ engine)

## Configuration

All settings are controlled via environment variables:

```bash
# Enable/disable features
DOCLING_SERVE_OTEL_ENABLE_METRICS=true       # Enable metrics collection
DOCLING_SERVE_OTEL_ENABLE_TRACES=true        # Enable trace collection
DOCLING_SERVE_OTEL_ENABLE_PROMETHEUS=true    # Enable Prometheus /metrics endpoint
DOCLING_SERVE_OTEL_ENABLE_OTLP_METRICS=false # Enable OTLP metrics export

# Service identification
DOCLING_SERVE_OTEL_SERVICE_NAME=docling-serve

# OTLP endpoint (for traces and optional metrics)
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

## Quick Start

### Option 1: Direct Prometheus Scraping

1. Start docling-serve with default settings:
   ```bash
   uv run docling-serve
   ```

2. Add to your `prometheus.yml`:
   ```yaml
   scrape_configs:
     - job_name: 'docling-serve'
       static_configs:
         - targets: ['localhost:5001']
   ```

3. Access metrics at `http://localhost:5001/metrics`

### Option 2: Full OTEL Stack with Docker Compose

1. Use the provided compose file:
   ```bash
   cd examples
   mkdit tempo-data
   docker-compose -f docker-compose-otel.yaml up
   ```

2. This starts:
   - **docling-serve**: API server with UI
   - **docling-worker**: RQ worker for distributed processing (scales independently)
   - **redis**: Message queue for RQ
   - **otel-collector**: Receives and routes telemetry
   - **prometheus**: Metrics storage
   - **tempo**: Trace storage
   - **grafana**: Visualization UI

3. Access:
   - Docling Serve UI: http://localhost:5001/ui
   - Metrics endpoint: http://localhost:5001/metrics
   - Grafana: http://localhost:3000 (pre-configured with Prometheus & Tempo)
   - Prometheus: http://localhost:9090
   - Tempo: http://localhost:3200

4. Scale workers (optional):
   ```bash
   docker-compose -f docker-compose-otel.yaml up --scale docling-worker=3
   ```

## Available Metrics

### HTTP Metrics (from OpenTelemetry FastAPI instrumentation)
- `http_server_request_duration` - Request duration histogram
- `http_server_active_requests` - Active requests gauge
- `http_server_request_size` - Request size histogram
- `http_server_response_size` - Response size histogram

### RQ Metrics (when using RQ engine)
- `rq_workers` - Number of workers by state
- `rq_workers_success` - Successful job count per worker
- `rq_workers_failed` - Failed job count per worker
- `rq_workers_working_time` - Total working time per worker
- `rq_jobs` - Job counts by queue and status
- `rq_request_processing_seconds` - RQ metrics collection time

## Traces

Traces are automatically generated for:
- All HTTP requests to FastAPI endpoints
- Document conversion operations
- **RQ job execution (distributed tracing)**: When using RQ engine, traces propagate from API requests to worker jobs, providing end-to-end visibility across the distributed system

View traces in Grafana Tempo or any OTLP-compatible backend.

### Distributed Tracing in RQ Mode

When running with the RQ engine (`DOCLING_SERVE_ENG_KIND=rq`), traces automatically propagate from the API to RQ workers:

1. **API Request**: FastAPI creates a trace when a document conversion request arrives
2. **Job Enqueue**: The trace context is injected into the RQ job metadata
3. **Worker Execution**: The RQ worker extracts the trace context and continues the trace
4. **End-to-End View**: You can see the complete request flow from API to worker in Grafana

This allows you to:
- Track document processing latency across API and workers
- Identify bottlenecks in the conversion pipeline
- Debug distributed processing issues
- Monitor queue wait times and processing times separately

## Example Files

See the `examples/` directory:
- `prometheus-scrape.yaml` - Prometheus scrape configuration examples
- `docker-compose-otel.yaml` - Full observability stack
- `otel-collector-config.yaml` - OTEL collector configuration
- `prometheus.yaml` - Prometheus configuration
- `tempo.yaml` - Tempo trace storage configuration
- `grafana-datasources.yaml` - Grafana data source provisioning

## Production Considerations

1. **Security**: Add authentication to the `/metrics` endpoint if needed
2. **Performance**: Metrics collection has minimal overhead (<1ms per scrape)
3. **Storage**: Configure retention policies in Prometheus/Tempo
4. **Sampling**: Configure trace sampling for high-volume services
5. **Labels**: Keep cardinality low to avoid metric explosion

## Disabling OTEL

To disable all OTEL features:

```bash
DOCLING_SERVE_OTEL_ENABLE_METRICS=false
DOCLING_SERVE_OTEL_ENABLE_TRACES=false
```
