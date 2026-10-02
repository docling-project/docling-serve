# Docling Serve Helm Chart

This Helm chart deploys [Docling Serve](https://github.com/docling-project/docling-serve), a document processing service that enables PDF conversion, OCR, and AI-powered document understanding.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- (Optional) External Secrets Operator for AWS Secrets Manager integration
- (Optional) KEDA for queue-based autoscaling of RQ workers

## Installing the Chart

Add the Helm repository (once published):

```bash
helm repo add docling https://docling-project.github.io/docling-serve/charts/
helm repo update
```

Install the chart:

```bash
helm install my-docling docling/docling-serve -n docling-system --create-namespace
```

## Configuration

### General Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `images.api.repository` | API image repository | `ghcr.io/docling-project/docling-serve-cpu` |
| `images.api.tag` | API image tag | `latest` |
| `images.rqWorker.repository` | RQ Worker image repository | `ghcr.io/docling-project/docling-serve-cpu` |
| `images.rqWorker.tag` | RQ Worker image tag | `latest` |
| `images.redis.repository` | Redis image repository | `redis` |
| `images.redis.tag` | Redis image tag | `7.2` |
| `replicaCount` | Number of API replicas | `1` |

### Autoscaling

| Parameter | Description | Default |
|-----------|-------------|---------|
| `autoscaling.enabled` | Enable HPA for API pods | `false` |
| `autoscaling.minReplicas` | Minimum API replicas | `1` |
| `autoscaling.maxReplicas` | Maximum API replicas | `5` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU utilization | `70` |
| `autoscaling.targetMemoryUtilizationPercentage` | Target memory utilization | `80` |

### RQ Worker Configuration

When using `engine.kind: rq`, background workers process jobs asynchronously via Redis.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `engine.kind` | Engine mode: `local` or `rq` | `local` |
| `engine.local.numWorkers` | Number of local workers | `4` |
| `engine.rq.resultsTtl` | TTL for successful job results (seconds) | `3600` |
| `engine.rq.failureTtl` | TTL for failed job results (seconds) | `3600` |
| `rqWorker.replicas` | Number of RQ worker replicas | `2` |

### Redis Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `redis.type` | Redis deployment type: `internal` or `external` | `internal` |
| `redis.replicas` | Number of Redis replicas (internal mode) | `1` |
| `redis.volume.medium` | Redis volume medium (internal mode) | `Memory` |
| `redis.volume.sizeLimit` | Redis volume size limit | `2Gi` |
| `redis.external.host` | External Redis host (for external mode) | `""` |
| `redis.external.port` | External Redis port | `6379` |
| `redis.external.database` | External Redis database number | `0` |
| `redis.external.tls.enabled` | Enable TLS for external Redis | `false` |

### KEDA Autoscaling (Optional)

For queue-based autoscaling of RQ workers when using external Redis:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kedaScaling.enabled` | Enable KEDA autoscaling | `false` |
| `kedaScaling.minReplicas` | Minimum RQ worker replicas | `1` |
| `kedaScaling.maxReplicas` | Maximum RQ worker replicas | `10` |
| `kedaScaling.listName` | RQ queue name to monitor | `rq:queue:convert` |
| `kedaScaling.listLength` | Queue items per replica trigger | `1` |

### External Secrets (AWS Secrets Manager)

For using external Redis with credentials stored in AWS Secrets Manager:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.externalSecret.enabled` | Enable ExternalSecret | `false` |
| `secrets.externalSecret.secretStore.name` | SecretStore name | `aws-secrets-manager` |
| `secrets.externalSecret.secretStore.kind` | SecretStore type | `ClusterSecretStore` |
| `secrets.externalSecret.secretStore.region` | AWS region | `us-east-1` |
| `secrets.externalSecret.remoteSecretName` | AWS Secrets Manager secret name | `""` |

### OpenTelemetry

| Parameter | Description | Default |
|-----------|-------------|---------|
| `opentelemetry.enabled` | Enable OpenTelemetry | `false` |
| `opentelemetry.traces.enabled` | Enable trace collection | `true` |
| `opentelemetry.metrics.enabled` | Enable metrics collection | `true` |
| `opentelemetry.exporter.endpoint` | OTLP exporter endpoint | `""` |
| `opentelemetry.exporter.protocol` | OTLP protocol | `grpc` |

### Docling Serve Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `doclingServe.enableUI` | Enable the web UI | `true` |
| `doclingServe.enableRemoteServices` | Allow remote pipeline connections | `false` |
| `doclingServe.allowCustomVlmConfig` | Allow custom VLM configurations | `false` |
| `doclingServe.maxFileSize` | Maximum file size (bytes) | `""` (default) |
| `doclingServe.maxNumPages` | Maximum pages to process | `""` (default) |
| `doclingServe.scratchPath` | Scratch path for temp files | `""` (default) |
| `doclingServe.singleUseResults` | Single-use result URLs | `""` (default) |

### Resource Requirements

| Parameter | Description | Default |
|-----------|-------------|---------|
| `resources.api.requests.cpu` | API CPU request | `250m` |
| `resources.api.requests.memory` | API memory request | `1Gi` |
| `resources.api.limits.memory` | API memory limit | `2Gi` |
| `resources.rqWorker.requests.cpu` | RQ Worker CPU request | `250m` |
| `resources.rqWorker.requests.memory` | RQ Worker memory request | `1Gi` |
| `resources.rqWorker.limits.memory` | RQ Worker memory limit | `4Gi` |
| `resources.redis.requests.cpu` | Redis CPU request | `250m` |
| `resources.redis.requests.memory` | Redis memory request | `100Mi` |
| `resources.redis.limits.memory` | Redis memory limit | `1Gi` |

## Examples

### Basic Installation (Local Engine)

```bash
helm install my-docling ./docling-serve \
  --namespace docling-system \
  --create-namespace
```

### RQ Engine with Internal Redis

```bash
helm install my-docling ./docling-serve \
  --namespace docling-system \
  --set engine.kind=rq \
  --set redis.type=internal \
  --set secrets.rqRedis.name=my-redis-secrets
```

### RQ Engine with External Redis and KEDA

```bash
helm install my-docling ./docling-serve \
  --namespace docling-system \
  --set engine.kind=rq \
  --set redis.type=external \
  --set redis.external.host=valkey.example.com \
  --set redis.external.port=6379 \
  --set redis.external.tls.enabled=true \
  --set kedaScaling.enabled=true \
  --set secrets.externalSecret.enabled=true \
  --set secrets.externalSecret.remoteSecretName=docling-serve-redis \
  --set secrets.rqRedis.name=docling-serve-redis-external-secret
```

### GPU-Enabled RQ Workers

```bash
helm install my-docling ./docling-serve \
  --namespace docling-system \
  --set engine.kind=rq \
  --set images.rqWorker.repository=ghcr.io/docling-project/docling-serve-cu128 \
  --set images.rqWorker.tag=latest \
  --set resources.rqWorker.requests.nvidia.com/gpu=1 \
  --set resources.rqWorker.limits.nvidia.com/gpu=1
```

## Troubleshooting

### Redis Connection Issues

If using internal Redis, ensure the secret exists:

```bash
kubectl create secret generic docling-serve-rq-secrets \
  --from-literal=RQ_REDIS_URL="redis://docling-serve-fullname-redis:6379/" \
  --from-literal=REDIS_PASSWORD="your-password" \
  --namespace docling-system
```

### Scaling Issues with KEDA

Verify KEDA is installed and the TriggerAuthentication is created:

```bash
kubectl get scaledobject -n docling-system
kubectl get triggerauthentication -n docling-system
```

## Uninstalling

```bash
helm uninstall my-docling -n docling-system
```

## Contributing

Contributions are welcome! Please see the [main project README](https://github.com/docling-project/docling-serve) for contribution guidelines.

## License

This Helm chart is licensed under the MIT License.
