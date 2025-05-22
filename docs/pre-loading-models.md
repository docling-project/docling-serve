# Pre-loading models for docling

This document provides examples for pre-loading docling models to a persistent volume and re-using it for docling-serve deployments.

1. We need to create a persistent volume that will store models weights:

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

2. In order to load model weights, we can use docling-toolkit to download them, as this is a one time operation we can use kubernetes job for this:

    ```yaml
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: docling-model-cache-load
    spec:
      selector: {}
      template:
        metadata:
          name: docling-model-load
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

    The job will mount previously created persistent volume and execute command similar to how we would load models locally:
    `docling-tools models download --output-dir <MOUNT-PATH> [LIST_OF_MODELS]`

    In manifest, we specify desired models individually, or we can use `--all` parameter to download all models.

    Manifest example: [docling-model-cache-job.yaml](./deploy-examples/docling-model-cache-job.yaml)

3. Now we can mount volume in the docling-serve deployment and set env `DOCLING_SERVE_ARTIFACTS_PATH` to point to it.
    Following additions to deploymeny should be made:

    ```yaml
    spec:
      template:
        spec:
          containers:
            - name: api
              env:
              ...
                - name: DOCLING_SERVE_ARTIFACTS_PATH
                  value: '/modelcache'
              volumeMounts:
                - name: docling-model-cache
                  mountPath: /modelcache
          ...
          volumes:
            - name: docling-model-cache
              persistentVolumeClaim:
                claimName: docling-model-cache-pvc
    ```

    Make sure that value of `DOCLING_SERVE_ARTIFACTS_PATH` is the same as where models were downloaded and where volume is mounted.

    Now when docling-serve is executing tasks, the underlying docling installation will load model weights from mouted volume.

    Manifest example: [docling-model-cache-deployment.yaml](./deploy-examples/docling-model-cache-deployment.yaml)
