# Preparing a public release

Publish the source as an experimental project. Keep the hardware-tested native
laptop path available, and label browser vehicle BLE and Bluefy as unverified
until hardware evidence establishes otherwise. No hosted service is required.

Before the first public push:

1. Preserve the MIT `LICENSE` and matching package metadata.
2. Review the complete Git file list. Include source, tests, scripts, and public
   documentation only. Do not force-add ignored files.
3. Run the tests and inspect a source export with a secret scanner such as
   Gitleaks. Scan Git history too if any commits already exist. A secret scanner
   does not reliably identify personal vehicle names, VINs, Bluetooth names,
   hostnames, usernames, device IDs, or screenshots; review those separately.
4. Confirm that examples use explicit placeholders or labeled synthetic values.
   Do not publish session output as a usage example: printed invitations, host
   control links, VIN-derived Bluetooth names, and local paths are private.
5. Preserve logs, captures, test APKs, and analysis in ignored local storage.
   Avoid attaching them to issues or releases without a separate privacy review.

Local `car-config.json`, tokens, `.env` files, logs, PID files, signing material,
build outputs, and mobile binaries are excluded by `.gitignore`. Ignore rules do
not remove files that were already tracked. Check both staged files and history
before pushing; revoke any credential that was actually exposed.

Validation:

```sh
.venv/bin/pytest -q
node scripts/test_web_transport.mjs
```

After Git initialization, inspect the publication boundary with:

```sh
git status --short --untracked-files=all
git diff --cached --name-only
git diff --cached
gitleaks git --redact --no-banner .
```

Do not publish `.venv`, `build`, `artifacts`, private configuration, or the entire
working directory as a ZIP. GitHub source archives should derive from the reviewed
commit. Build downloadable binaries separately if releases later need them.
