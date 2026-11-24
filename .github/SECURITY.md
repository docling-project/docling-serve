# Security and Disclosure Information Policy for the Docling Project

The Docling team and community take security bugs seriously. We appreciate your efforts to responsibly disclose your findings, and will make every effort to acknowledge your contributions.

## Supported Versions

The latest versions of all Docling repositories are supported.

### Security

- Participation in the [OpenSSF Best Practices Badge Program](https://bestpractices.coreinfrastructure.org/en/projects/10101) for Free/Libre and FLOSS projects to ensure that we follow current best practices for quality and security
- Use of [HTTPS](https://en.wikipedia.org/wiki/HTTPS) for network communication
- Use of secure protocols for network communication (through the use of HTTPS)
- Up-to-date support for TLS/SSL (through the use of [OpenSSL](https://www.openssl.org/))
- Performance of TLS certificate verification by default before sending HTTP headers with private information (through the use of OpenSSL and HTTPS)
- Distribution of the software via cryptographically signed releases (on the [PyPI](https://pypi.org/), [Quay.io](https://quay.io/organization/docling-project/) and [GHCR.io](https://github.com/orgs/docling-project/packages) package repositories)
- Use of [GitHub](https://github.com/) Issues for vulnerability reporting and tracking

### Analysis

- Use of [Ruff](https://docs.astral.sh/ruff/), [Mypy](https://mypy.readthedocs.io/) and [Pytest](https://docs.pytest.org/en/7.2.x/) for Python code linting (static and dynamic analysers) on pull requests and builds
- Use of GitHub Issues for bug reporting and tracking

## Scope and Threat Model

This section tells reporters which docling-serve reports we treat as vulnerabilities, and how we score them.

### Threat model

docling-serve is an API service that converts documents for its clients. It has these trust boundaries:

- **API clients are trusted to use every API feature.** docling-serve has one shared API key (`DOCLING_SERVE_API_KEY`) and no per-user permissions. Every client with the key can use every endpoint, including `/v1/clear/*`. Without an API key, every client that can reach the port has the same access. `docling-serve run` and the container images listen on all interfaces, so set an API key, or put an authenticating proxy in front, on any deployment that untrusted clients can reach.
- **Documents are untrusted.** The conversion follows the [Docling threat model](https://github.com/docling-project/docling/blob/main/.github/SECURITY.md#scope-and-threat-model). Report conversion issues to the [Docling repository](https://github.com/docling-project/docling/security).
- **The operator controls the network.** Some features make the server connect to URLs chosen by the client: HTTP sources, callbacks and `put` targets. HTTP sources refuse private addresses unless `DOCLINGCORE_ALLOWED_PRIVATE_IPS` allows them. Callbacks and `put` targets are not filtered, because their usual receivers are on the operator's own network. Restrict where the server can connect with egress network policies. Turn off what you do not use with `DOCLING_SERVE_ENABLE_CALLBACKS=false` and `DOCLING_SERVE_ALLOWED_TARGET_TYPES`.
- **The operator sets resource limits.** Limits such as `DOCLING_SERVE_MAX_FILE_SIZE` and `DOCLING_SERVE_MAX_NUM_PAGES` are off by default. Set request-size limits and rate limits at the ingress or reverse proxy, and run the service with memory and CPU limits.
- **Configuration and logs are trusted.** Only the operator can change the configuration. Logs can contain request details, so restrict who can read them.

### In scope

For example, we treat these as vulnerabilities:

- Using the API without the key when an API key is configured.
- Reading or changing another client's tasks or results without knowing their task id.
- Bypassing a check that the documentation describes, for example the private-address check for HTTP sources.
- Exposing server secrets, such as the API key or storage credentials, to clients, or to logs in a documented configuration.
- A small request that makes docling-serve itself use memory or CPU out of proportion to its size.
- Code execution, or file access outside the configured paths.

### Out of scope

We do not treat these cases as vulnerabilities:

- A client using any API feature when no API key is configured, or when it holds the API key.
- Callbacks or `put` targets connecting to destinations that the deployment's network allows.
- Cost that grows linearly with the size or the number of requests, for example a large upload.
- Behavior that needs an option that the documentation marks as risky. We can accept such reports with low severity.
- Issues in the document conversion itself. Report these to the Docling repository.

### Scoring

We score with CVSS 3.1.

- Issues that need API access use `PR:L`, also when the deployment has no API key. The open default applies to every endpoint, so it is not counted again in each report.
- Only a bypass of a configured API key uses `PR:N`.
- Issues that need a non-default or risky configuration use `AC:H`.

## Reporting a Vulnerability

If you think you've identified a security issue in any Docling project repository, please DO NOT report the issue publicly via the GitHub issue tracker, discussions, or any other public forum.

### Preferred Method: GitHub Private Vulnerability Reporting

**We strongly encourage you to use GitHub's Private Vulnerability Reporting feature**, which provides a secure and streamlined process for disclosing security issues:

1. Navigate to the **Security tab** of the specific Docling repository where the vulnerability exists (e.g., `https://github.com/docling-project/<repository-name>/security`)
   - For example: [docling](https://github.com/docling-project/docling/security), [docling-core](https://github.com/docling-project/docling-core/security), [docling-parse](https://github.com/docling-project/docling-parse/security), etc.
2. Click on "Report a vulnerability"
3. Fill out the vulnerability report form with as many details as possible
4. Submit the report

This method allows for:
- **Secure communication** directly with the maintainers team
- **Coordinated disclosure** through GitHub's built-in workflow
- **Automatic tracking** of the vulnerability lifecycle
- **Credit attribution** when the vulnerability is published

### Alternative Method: Email Disclosure

Alternatively, you can send an email with as many details as possible to [deepsearch-core@zurich.ibm.com](mailto:deepsearch-core@zurich.ibm.com). This is a private mailing list for the maintainers team.

**Important:** Please do not create a public issue or discuss the vulnerability in any public channel until it has been addressed.

### Security Vulnerability Response

Each report is acknowledged and analyzed by the core maintainers within 3 working days.

Any vulnerability information shared with core maintainers stays within the Docling project and will not be disseminated to other projects unless it is necessary to get the issue fixed.

After the initial reply to your report, the security team will keep you informed of the progress towards a fix and full announcement, and may ask for additional information or guidance.

## Security Alerts

We will send announcements of security vulnerabilities and steps to remediate on the [Docling announcements](https://github.com/docling-project/docling/discussions/categories/announcements).
