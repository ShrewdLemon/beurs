# Releasing

beurs is not on PyPI yet. Until it is, install from GitHub:

```bash
pip install git+https://github.com/ShrewdLemon/beurs
```

Publishing is already wired up in [`.github/workflows/publish.yml`](.github/workflows/publish.yml).
It uses PyPI Trusted Publishing (OIDC), so no API token is stored in this
repository or in GitHub secrets. What is missing is a one-time setup that only
the owner can do, on pypi.org and on GitHub.

## One-time setup (owner, by hand)

1. **Check the name is free.** Open https://pypi.org/project/beurs/. A 404 means
   it is free. If it is taken, pick a new name, change `name` in
   `pyproject.toml`, and use that name below.
2. **Sign in to PyPI** with an account that has 2FA turned on. PyPI requires it
   to publish.
3. **Add a pending publisher.** Go to
   https://pypi.org/manage/account/publishing/ and fill in the
   "GitHub" form exactly as below. A pending publisher lets the first upload
   create the project, so there is no need to upload anything by hand first.

   | field | value |
   |---|---|
   | PyPI project name | `beurs` |
   | Owner | `ShrewdLemon` |
   | Repository name | `beurs` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

4. **Create the `pypi` environment on GitHub.** In the repo, Settings >
   Environments > New environment, name it `pypi`. Optionally add yourself as a
   required reviewer, so every release waits for one click of approval.
5. **Make sure GitHub Actions can run** on the account. The publish job runs on
   GitHub-hosted runners like CI does.

Optional: repeat steps 3 and 4 on https://test.pypi.org with an environment
named `testpypi` if you want a dry run first. The workflow would need a second
job pointing at TestPyPI for that; it does not have one today.

## Cutting a release

1. Bump the version in `beurs/__init__.py` and `pyproject.toml`. They must match.
2. Run the tests locally: `pytest tests/ -q`.
3. Commit, then tag and push the tag:

   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

4. The `publish` workflow then:
   - builds the sdist and wheel and runs `twine check`,
   - installs the built wheel in a clean venv and checks audit, repair and the
     NSE calendar work on pandas alone,
   - refuses to continue if the tag does not match `beurs.__version__`,
   - uploads to PyPI through the `pypi` environment.

5. Check https://pypi.org/project/beurs/ and try `pip install beurs` in a fresh
   venv. Then update the install section of the README to point at PyPI.

## If something goes wrong

- **"invalid-publisher" or 403 on upload**: one of the five fields in step 3 does
  not match. The workflow file name and environment name are the usual culprits.
- **Tag and version mismatch**: delete nothing. Bump the version, commit, and
  push a new tag.
- A version number can only be uploaded to PyPI once, even if you delete it
  later. Fix forward with a new version.
