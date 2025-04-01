# Deployment

## OpenShift

### Secure deployment with `oauth-proxy`

Manifest example: [docling-serve-oauth.yaml](./deploy-examples/docling-serve-oauth.yaml)

This deployment has the following features:

- TLS encryption between all components (using the cluster-internal CA authority).
- Authentication via a secure `oauth-proxy` sidecar.
- Expose the service using a secure OpenShift `Route`

Install the app with:

```sh
kubectl apply -f docs/deploy-examples/docling-serve-oauth.yaml
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
