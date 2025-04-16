# Deployment

## Local GPU deployment

### Docker compose

Manifest example: [compose-gpu.yaml](./deploy-examples/compose-gpu.yaml)

This deployment has the following features:

  - NVIDIA cuda enabled

Install the app with:

```sh
docker compose -f docs/deploy-examples/compose-gpu.yaml up -d
```

For using the API:

```sh
# Make a test query
curl -X 'POST' \
  "localhost:5001/v1alpha/convert/source/async" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "http_sources": [{"url": "https://arxiv.org/pdf/2501.17887"}]
  }'
```

Requirements:

  - debian/ubuntu/rhel/fedora/opensuse
  - docker
  - nivida drivers >=550.54.14
  - nvidia-container-toolkit 

Docs:

https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/supported-platforms.html

https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html#id6

Steps:

1. Check driver version and which GPU you want to use (0/1/2/3.. and update [compose-gpu.yaml](./deploy-examples/compose-gpu.yaml) file or use `count: all`)

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

https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

3. Check which runtime is being used by Docker

```sh
# docker
docker info | grep -i runtime
```

4. If the default Docker runtime, changes back from 'nvidia' to 'default' after restarting the Docker service

(optional) backup daemon.json file

```sh
sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.bak
```

update the daemon.json file

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

restart the Docker service after updating the daemon.json file

```sh
sudo systemctl restart docker
```

confirm 'nvidia' is the default runtime used by Docker by repeating step 3

5. Run the container

```sh
docker compose -f docs/deploy-examples/compose-gpu.yaml up -d
```
 
## OpenShift

### Simple deployment

Manifest example: [docling-serve-simple.yaml](./deploy-examples/docling-serve-simple.yaml)

This deployment has the following features:

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
  "localhost:5001/v1alpha/convert/source/async" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "http_sources": [{"url": "https://arxiv.org/pdf/2501.17887"}]
  }'
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
  "${DOCLING_ROUTE}/v1alpha/convert/source/async" \
  -H "Authorization: Bearer ${OCP_AUTH_TOKEN}" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "http_sources": [{"url": "https://arxiv.org/pdf/2501.17887"}]
  }'
```
