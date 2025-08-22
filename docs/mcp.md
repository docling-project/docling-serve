The `docling-serve` container image includes all MCP (Model Communication Protocol) features starting from version v1.1.0. To leverage these features, you simply need to use a different entrypoint—no custom image builds or additional installations are required. The image provides the `docling-mcp-server` executable, which enables MCP functionality out of the box as of version v1.1.0 ([changelog](https://github.com/docling-project/docling-serve/blob/624f65d41b734e8b39ff267bc8bf6e766c376d6d/CHANGELOG.md)).

Read more on [Docling MCP](https://github.com/docling-project/docling-mcp) in its dedicated repository.

**Launching the MCP Service**

By default, the container runs `docling-serve run` and exposes port 5001. To start the MCP service, override the entrypoint and specify your desired port mapping. For example:

```sh
podman run -p 8000:8000 quay.io/docling-project/docling-serve -- docling-mcp-server --transport streamable-http --port 8000 --host 0.0.0.0
```

This command starts the MCP server on port 8000, accessible at `http://localhost:8000/mcp`. Adjust the port and host as needed. Key arguments for `docling-mcp-server` include `--transport streamable-http` (HTTP transport for client connections), `--port <PORT>`, and `--host <HOST>` (use `0.0.0.0` to accept connections from any interface).

**Configuring MCP Clients**

Most MCP-compatible clients, such as LM Studio and Claude Desktop, allow you to specify custom MCP server endpoints. The standard configuration uses a JSON block to define available MCP servers. For example, to connect to the Docling MCP server running on port 8000:

```json
{
  "mcpServers": {
    "docling": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Insert this configuration in your client's settings where MCP servers are defined. Update the URL if you use a different port.

**LM Studio and Claude Desktop**

Both LM Studio and Claude Desktop support MCP endpoints via configuration files or UI settings. Paste the above JSON block into the appropriate configuration section. For Claude Desktop, add the MCP server in the "Custom Model" or "MCP Server" section. For LM Studio, refer to its documentation for the location of the MCP server configuration.

**Other MCP Clients**

Other clients, such as Continue Coding Assistant, also support custom MCP endpoints. Use the same configuration pattern: provide the MCP server URL ending with `/mcp` and ensure the port matches your container setup. See the [Docling MCP docs](https://github.com/docling-project/docling-mcp/tree/main/docs/integrations) for more details.

**Troubleshooting**

If clients cannot connect, check for port conflicts, firewall rules, or incorrect endpoint URLs. Ensure the MCP server is running and accessible at the specified address. Most clients expect the endpoint to be reachable at `/mcp` over HTTP.

