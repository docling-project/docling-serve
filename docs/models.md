# Handling Models in Docling Serve

When enabling steps in Docling Serve that require extra models (such as picture classification, picture description, table detection, code recognition, formula extraction, or vision-language modules), you must ensure those models are available in the runtime environment. The standard container image includes only the default models. Any additional models must be downloaded and made available before use. If required models are missing, Docling Serve will raise runtime errors rather than downloading them automatically. This default choice wants to guarantee the system is not calling external services.

## Model Storage Location

Docling Serve loads models from the directory specified by the `DOCLING_SERVE_ARTIFACTS_PATH` environment variable. This path must be consistent across model download and runtime. When running with multiple workers or reload enabled, you must use the environment variable rather than the CLI argument for configuration [[source]](./configuration.md).

## Approaches for Making Extra Models Available

There are several ways to ensure required models are present:

### 1. Disable Local Models (Trigger Auto-Download)

You can configure the container to download all models at startup by clearing the artifacts path:

```sh
podman run -d -p 5001:5001 --name docling-serve \
  -e DOCLING_SERVE_ARTIFACTS_PATH="" \
  -e DOCLING_SERVE_ENABLE_UI=true \
  quay.io/docling-project/docling-serve
```

This approach is simple for local development but not recommended for production, as it increases startup time and depends on network availability.

### 2. Build a Custom Image with Pre-Downloaded Models

You can create a new image that includes the required models:

```Dockerfile
FROM quay.io/docling-project/docling-serve
RUN docling-tools models download smolvlm
```

This method is suitable for production, as it ensures all models are present in the image and avoids runtime downloads.

### 3. Update the Entrypoint to Download Models Before Startup

You can override the entrypoint to download models before starting the service:

```sh
podman run -p 5001:5001 -e DOCLING_SERVE_ENABLE_UI=true \
  quay.io/docling-project/docling-serve \
  -- sh -c 'exec docling-tools models download smolvlm && exec docling-serve run'
```

This is useful for environments where you want to keep the base image unchanged but still automate model preparation.

### 4. Mount a Volume with Pre-Downloaded Models

Download models locally and mount them into the container:

```sh
# Download the models locally
docling-tools models download --all -o models

# Start the container with the local models folder
podman run -p 5001:5001 \
  -v $(pwd)/models:/opt/app-root/src/models \
  -e DOCLING_SERVE_ARTIFACTS_PATH="/opt/app-root/src/models" \
  -e DOCLING_SERVE_ENABLE_UI=true \
  quay.io/docling-project/docling-serve
```

This approach is robust for both local and production deployments, especially when using persistent storage.

## Kubernetes/Cluster Deployments

For Kubernetes or OpenShift clusters, the recommended approach is to use a PersistentVolumeClaim (PVC) for model storage, a Kubernetes Job to download models, and mount the volume into the deployment. This ensures models persist across pod restarts and scale-out scenarios.

### Example: PersistentVolumeClaim

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: docling-model-cache-pvc
spec:
  accessModes:
    - ReadWriteOnce
  volumeMode: Filesystem
  resources:
    requests:
      storage: 10Gi
```

If you don't want to use default storage class, set your custom storage class with following:

```yaml
spec:
    ...
    storageClassName: <Storage Class Name>
```

Manifest example: [docling-model-cache-pvc.yaml](./deploy-examples/docling-model-cache-pvc.yaml)

### Example: Model Download Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: docling-model-cache-load
spec:
  template:
    spec:
      containers:
        - name: loader
          image: ghcr.io/docling-project/docling-serve-cpu:main
          command:
            - docling-tools
            - models
            - download
            - '--output-dir=/modelcache'
            - 'layout'
            - 'tableformer'
            - 'code_formula'
            - 'picture_classifier'
            - 'smolvlm'
            - 'granite_vision'
            - 'easyocr'
          volumeMounts:
            - name: docling-model-cache
              mountPath: /modelcache
      volumes:
        - name: docling-model-cache
          persistentVolumeClaim:
            claimName: docling-model-cache-pvc
      restartPolicy: Never
```

The job will mount the previously created persistent volume and execute command similar to how we would load models locally:
`docling-tools models download --output-dir <MOUNT-PATH> [LIST_OF_MODELS]`

In manifest, we specify desired models individually, or we can use `--all` parameter to download all models.

Manifest example: [docling-model-cache-job.yaml](./deploy-examples/docling-model-cache-job.yaml)

### Example: Deployment with Mounted Volume

```yaml
spec:
  template:
    spec:
      containers:
        - name: api
          env:
            - name: DOCLING_SERVE_ARTIFACTS_PATH
              value: '/modelcache'
          volumeMounts:
            - name: docling-model-cache
              mountPath: /modelcache
      volumes:
        - name: docling-model-cache
          persistentVolumeClaim:
            claimName: docling-model-cache-pvc
```

The value of `DOCLING_SERVE_ARTIFACTS_PATH` must match the mount path where models are stored.

Now, when docling-serve is executing tasks, the underlying docling installation will load model weights from mounted volume.

Manifest example: [docling-model-cache-deployment.yaml](./deploy-examples/docling-model-cache-deployment.yaml)

## Local Docker Execution

For local Docker or Podman execution, you can use any of the approaches above. Mounting a local directory with pre-downloaded models is the most reliable for repeated runs and avoids network dependencies.

## Troubleshooting and Best Practices

- If a required model is missing from the artifacts path, Docling Serve will raise a runtime error.
- Always ensure the value of `DOCLING_SERVE_ARTIFACTS_PATH` matches the directory where models are stored and mounted.
- For production and cluster environments, prefer persistent storage and pre-loading models via a dedicated job.

For more details and YAML manifest examples, see the [deployment documentation](./deployment.md).
