# GitLab Runner Setup — AL2023 FIPS Shell Runner

This document describes how to build a dedicated GitLab Runner on Amazon Linux 2023
(FIPS mode) with `uv` and Python pre-installed. This is **Option 1** — the
production-grade replacement for the temporary `pip3 install uv` bootstrap currently
in `.gitlab-ci.yml`.

Once this runner is in service, remove the `.uv_bootstrap` hidden job and the
`extends: .uv_bootstrap` lines from the pipeline.

---

## Prerequisites

- An EC2 instance running **Amazon Linux 2023** with FIPS mode enabled
  (`fips-mode-setup --check` should return `FIPS mode is enabled`)
- The instance must have outbound internet access (or a VPC endpoint / proxy) to
  reach the GitLab instance and `dnf` package mirrors
- IAM instance profile or SSH access to run commands as a privileged user
- Your GitLab runner registration token (Settings → CI/CD → Runners)

---

## 1. Install Python 3.12

AL2023 ships Python 3.9 by default. Install 3.12 (or 3.11) from the standard repos:

```bash
sudo dnf install -y python3.12 python3.12-pip python3.12-devel
```

Verify:

```bash
python3.12 --version   # Python 3.12.x
pip3.12 --version
```

---

## 2. Install `uv`

Install via `pip` — this is more reliable in FIPS environments than the
`curl | sh` installer, which may fail due to FIPS-restricted TLS cipher
suites or shell execution policies.

```bash
sudo python3.12 -m pip install uv
```

If `sudo pip3.12` installs to `/usr/local/bin`, verify and add it to the
system-wide `PATH` if needed:

```bash
which uv        # should be /usr/local/bin/uv or /usr/bin/uv
uv --version
```

If `uv` lands in a user-local path instead, install system-wide explicitly:

```bash
sudo python3.12 -m pip install --prefix /usr/local uv
```

---

## 3. Install Docker CLI

The pipeline uses Docker for `build-image` and `build-sbom-image`. If not already
present:

```bash
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker gitlab-runner   # allow runner to use Docker without sudo
```

---

## 4. Install GitLab Runner

```bash
# Add the GitLab Runner repo
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.rpm.sh" \
  | sudo bash

# Install
sudo dnf install -y gitlab-runner

# Verify
gitlab-runner --version
```

> **FIPS note**: If the `curl | bash` script is blocked, download
> `gitlab-runner-*.x86_64.rpm` from
> `https://packages.gitlab.com/runner/gitlab-runner/el/9/` and install with
> `sudo rpm -ivh`.

---

## 5. Register the Runner

```bash
sudo gitlab-runner register \
  --url "https://your-gitlab.example.com" \
  --token "YOUR_REGISTRATION_TOKEN" \
  --executor shell \
  --tag-list al2023-fips-shell \
  --description "AL2023 FIPS Shell Runner" \
  --non-interactive
```

Start and enable the service:

```bash
sudo systemctl enable --now gitlab-runner
sudo systemctl status gitlab-runner
```

---

## 6. Verify the Runner Environment

Log in as the `gitlab-runner` user and confirm all tools are on its `PATH`:

```bash
sudo -u gitlab-runner bash -c "uv --version && python3.12 --version && docker --version && aws --version && jq --version"
```

All commands must resolve without errors before the runner is used in production.

---

## 7. Update the Pipeline

Once the runner is confirmed working, remove the temporary bootstrap from
`.gitlab-ci.yml`:

1. Delete the `.uv_bootstrap:` hidden job block.
2. Remove `extends: .uv_bootstrap` from `lint`, `build-wheel`, and `unit-tests`.
3. Remove the comment referencing this document from those jobs.
4. Commit and push.

---

## Maintenance

- **Update `uv`**: `sudo pip3.12 install --upgrade uv` on the runner host.
- **Update Python**: `sudo dnf upgrade python3.12` or install a new minor version
  and update the runner's `PATH` if needed.
- **GitLab Runner updates**: `sudo dnf upgrade gitlab-runner`.
