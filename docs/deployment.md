# Deployment Examples

This document provides deployment examples for running the application in different environments.

Choose the deployment option that best fits your setup.

- **[Local GPU NVIDIA](#local-gpu-nvidia)**: For deploying the application locally on a machine with a supported NVIDIA GPU (using Docker Compose).
- **[Local GPU AMD](#local-gpu-amd)**: For deploying the application locally on a machine with a supported AMD GPU (using Docker Compose).
- **[OpenShift](#openshift)**: For deploying the application on an OpenShift cluster, designed for cloud-native environments.

---

## Local GPU NVIDIA

### Docker compose

Manifest example: [compose-nvidia.yaml](./deploy-examples/compose-nvidia.yaml)

This deployment has the following features:

- NVIDIA cuda enabled

Install the app with:

```sh
docker compose -f docs/deploy-examples/compose-nvidia.yaml up -d
```

For using the API:

```sh
# Make a test query
curl -X 'POST' \
  "localhost:5001/v1/convert/source/async" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": [{"kind": "http", "url": "https://arxiv.org/pdf/2501.17887"}]
  }'
```

<details>
<summary><b>Requirements</b></summary>

- debian/ubuntu/rhel/fedora/opensuse
- docker
- nvidia drivers >=550.54.14
- nvidia-container-toolkit

Docs:

- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/supported-platforms.html)
- [CUDA Toolkit Release Notes](https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html#id6)

</details>

<details>
<summary><b>Steps</b></summary>

1. Check driver version and which GPU you want to use 0/1/2/n (and update [compose-nvidia.yaml](./deploy-examples/compose-nvidia.yaml) file or use `count: all`)

    ```sh
    nvidia-smi
    ```

2. Check if the NVIDIA Container Toolkit is installed/updated

    ```sh
    # debian
    dpkg -l | grep nvidia-container-toolkit
    ```

    ```sh
    # rhel
    rpm -q nvidia-container-toolkit
    ```

    NVIDIA Container Toolkit install steps can be found here:

    <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>

3. Check which runtime is being used by Docker

    ```sh
    # docker
    docker info | grep -i runtime
    ```

4. If the default Docker runtime changes back from 'nvidia' to 'default' after restarting the Docker service (optional):

    Backup the daemon.json file:

    ```sh
    sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.bak
    ```

    Update the daemon.json file:

    ```sh
    echo '{
      "runtimes": {
        "nvidia": {
          "path": "nvidia-container-runtime"
        }
      },
      "default-runtime": "nvidia"
    }' | sudo tee /etc/docker/daemon.json > /dev/null
    ```

    Restart the Docker service:

    ```sh
    sudo systemctl restart docker
    ```

    Confirm 'nvidia' is the default runtime used by Docker by repeating step 3.

5. Run the container:

    ```sh
    docker compose -f docs/deploy-examples/compose-nvidia.yaml up -d
    ```

</details>

## Local GPU AMD

### Docker compose

Manifest example: [compose-amd.yaml](./deploy-examples/compose-amd.yaml)

This deployment has the following features:

- AMD ROCm GPU acceleration (ROCm 6.3, ROCm 7.2, or ROCm 10.1.0 for modern AMD GPUs and APUs)

Install the app with:

```sh
docker compose -f docs/deploy-examples/compose-amd.yaml up -d
```

For using the API:

```sh
# Make a test query
curl -X 'POST' \
  "localhost:5001/v1/convert/source/async" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": [{"kind": "http", "url": "https://arxiv.org/pdf/2501.17887"}]
  }'
```

<details>
<summary><b>Requirements</b></summary>

- Linux distribution (Debian/Ubuntu/RHEL/Fedora/openSUSE/Arch)
- Container engine (Docker or Podman)
- AMDGPU kernel driver & ROCm runtime:
  - Discrete RDNA / CDNA GPUs: AMD ROCm >= 6.3
  - Modern AMD GPUs and APUs (Radeon RX 7000 series, Strix Halo `gfx1151`, Strix Point `gfx1150`): ROCm 10.1.0 (`rocm101` image)

Docs:

- [AMD ROCm installation](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/quick-start.html)
- [AMD ROCm Compatibility Matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html)

</details>

<details>
<summary><b>Steps</b></summary>

1. Check driver version and which GPU you want to use 0/1/2/n (and update [compose-amd.yaml](./deploy-examples/compose-amd.yaml) file)

    ```sh
    rocm-smi --showdriverversion
    rocminfo | grep -i "ROCm version"
    ```

2. Find both video group GID and render group GID from host (and update [compose-amd.yaml](./deploy-examples/compose-amd.yaml) file)

    ```sh
    getent group video
    getent group render
    ```

3. Build the container image locally:

    - For ROCm 6.3:
      ```sh
      make docling-serve-rocm-image
      ```
    - For ROCm 7.2:
      ```sh
      make docling-serve-rocm72-image
      ```
    - For ROCm 10.1.0 (defaults to AMD Strix Halo `gfx1151`):
      ```sh
      make docling-serve-rocm101-image
      ```
      Or specify target architecture (`DEVICE=<arch>`, e.g. `gfx1150`, `gfx1100`, `gfx942`, `gfx90a`):
      ```sh
      make docling-serve-rocm101-image DEVICE=gfx1150
      ```

4. Configure Environment Variables for AMD ROCm 10.1 / APUs:

    When deploying on AMD Strix Halo (`gfx1151` / Radeon 8060S / 8050S) or Strix Point (`gfx1150` / Radeon 890M / 880M), set the following container environment:

    ```env
    ROCR_VISIBLE_DEVICES=0
    HSA_ENABLE_SDMA=0
    ```

    > [!IMPORTANT]
    > **Hardware Notes for Strix Halo / APUs (`gfx1151`, `gfx1150`):**
    > - **PyTorch SDPA Math Fallback:** FlashAttention / Composable-Kernel C++ fatbins do not include precompiled binary code objects for client APUs (`gfx1151`, `gfx1150`). `docling-serve` automatically detects this at startup and enables PyTorch Math SDPA fallback to route attention ops to standard rocBLAS / hipBLASLt GEMM, avoiding `hipErrorInvalidImage`.
    > - **Do NOT override GFX version:** Do not set `HSA_OVERRIDE_GFX_VERSION` on ROCm 10.1.0 since `gfx1151` and `gfx1150` are natively targeted by the AMD modular runtime.
    > - **Do NOT enable AOTriton experimental:** Ensure `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL` is unset or `0` on client APUs.
    > - **SDMA:** `HSA_ENABLE_SDMA=0` is recommended for unified APU memory architectures to prevent SDMA queue stalls.

</details>

## OpenShift

### Simple deployment

Manifest example: [docling-serve-simple.yaml](./deploy-examples/docling-serve-simple.yaml)

This deployment example has the following features:

- Deployment configuration
- Service configuration
- NVIDIA cuda enabled

Install the app with:

```sh
oc apply -f docs/deploy-examples/docling-serve-simple.yaml
```

For using the API:

```sh
# Port-forward the service
oc port-forward svc/docling-serve 5001:5001

# Make a test query
curl -X 'POST' \
  "localhost:5001/v1/convert/source/async" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": [{"kind": "http", "url": "https://arxiv.org/pdf/2501.17887"}]
  }'
```

### Multiple workers with RQ

Manifest example: [`docling-serve-rq-workers.yaml`](./deploy-examples/docling-serve-rq-workers.yaml)

This deployment example has the following features:

- Deployment configuration
- Service configuration
- Redis deployment
- Multiple (2 by default) worker Pods

Install the app with:

- create k8s secret:

```sh
kubectl create secret generic docling-serve-rq-secrets --from-literal=REDIS_PASSWORD=myredispassword --from-literal=RQ_REDIS_URL=redis://:myredispassword@docling-serve-redis-service:6373/
```

- apply deployment manifest:

```sh
oc apply -f docs/deploy-examples/docling-serve-rq-workers.yaml
```

### Secure deployment with `oauth-proxy`

Manifest example: [docling-serve-oauth.yaml](./deploy-examples/docling-serve-oauth.yaml)

This deployment has the following features:

- TLS encryption between all components (using the cluster-internal CA authority).
- Authentication via a secure `oauth-proxy` sidecar.
- Expose the service using a secure OpenShift `Route`

Install the app with:

```sh
oc apply -f docs/deploy-examples/docling-serve-oauth.yaml
```

For using the API:

```sh
# Retrieve the endpoint
DOCLING_NAME=docling-serve
DOCLING_ROUTE="https://$(oc get routes ${DOCLING_NAME} --template={{.spec.host}})"

# Retrieve the authentication token
OCP_AUTH_TOKEN=$(oc whoami --show-token)

# Make a test query
curl -X 'POST' \
  "${DOCLING_ROUTE}/v1/convert/source/async" \
  -H "Authorization: Bearer ${OCP_AUTH_TOKEN}" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": [{"kind": "http", "url": "https://arxiv.org/pdf/2501.17887"}]
  }'
```

### ReplicaSets with `sticky sessions`

Manifest example: [docling-serve-replicas-w-sticky-sessions.yaml](./deploy-examples/docling-serve-replicas-w-sticky-sessions.yaml)

This deployment has the following features:

- Deployment configuration with 3 replicas
- Service configuration
- Expose the service using a OpenShift `Route` and enables sticky sessions

Install the app with:

```sh
oc apply -f docs/deploy-examples/docling-serve-replicas-w-sticky-sessions.yaml
```

For using the API:

```sh
# Retrieve the endpoint
DOCLING_NAME=docling-serve
DOCLING_ROUTE="https://$(oc get routes $DOCLING_NAME --template={{.spec.host}})"

# Make a test query, store the cookie and taskid
task_id=$(curl -s -X 'POST' \
    "${DOCLING_ROUTE}/v1/convert/source/async" \
    -H "accept: application/json" \
    -H "Content-Type: application/json" \
    -d '{
      "sources": [{"kind": "http", "url": "https://arxiv.org/pdf/2501.17887"}]
    }' \
    -c cookies.txt | grep -oP '"task_id":"\K[^"]+')
```

```sh
# Grab the taskid and cookie to check the task status
curl -v -X 'GET' \
  "${DOCLING_ROUTE}/v1/status/poll/$task_id?wait=0" \
  -H "accept: application/json" \
  -b "cookies.txt"
```
