# Branch protection recommendation

Do **not** change GitHub admin settings from this clone. Recommendation for humans:

- Protect `main` and `integration/main`.
- Require the `CI Release Gate` workflow (`ci-release-gate.yml`) to pass.
- Require review on auth, storage, migrations, secrets, and deploy.
- Disallow force-push and deletion of protected branches.
- Do not allow skipping hooks or continuing on error.

This file is documentation only.
