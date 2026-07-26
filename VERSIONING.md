# Versioning Conventions

Familiar follows [Semantic Versioning 2.0.0](https://semver.org/) with pre-release extensions for testing builds.

## Version Format

```
MAJOR.MINOR.PATCH[-PRERELEASE]

Examples:
  0.2.2          Stable release
  0.3.0-alpha.1  Alpha pre-release
  0.3.0-beta.1   Beta pre-release
  0.3.0-rc.1     Release candidate
  1.0.0          First stable major release
```

## Release Types

### Major Release (`X.0.0`)

**When to bump:** Breaking changes that require users to modify their setup.

Examples:
- Breaking API changes
- Database schema changes requiring manual migration
- Removing or renaming configuration options
- Major architectural changes
- Dropping support for a platform

```bash
git tag v1.0.0
git push origin v1.0.0
```

### Minor Release (`0.X.0`)

**When to bump:** New features that are backwards-compatible.

Examples:
- New LLM tools or capabilities
- New audio analysis features
- New UI components or views
- New API endpoints
- Performance improvements

```bash
git tag v0.3.0
git push origin v0.3.0
```

### Patch Release (`0.0.X`)

**When to bump:** Bug fixes and small improvements that are backwards-compatible.

Examples:
- Bug fixes
- Memory/performance optimizations
- Documentation updates
- Security patches
- UI polish

```bash
git tag v0.2.3
git push origin v0.2.3
```

## Pre-release Versions

Pre-releases are for testing before a stable release. They are **not** marked as "Latest" on GitHub and users must explicitly download them.

### Alpha (`-alpha.N`)

**Purpose:** Early development, may be unstable. For internal testing.

- Feature incomplete
- APIs may change
- Not recommended for production

```bash
git tag v0.3.0-alpha.1
git push origin v0.3.0-alpha.1
```

### Beta (`-beta.N`)

**Purpose:** Feature complete, testing phase. For adventurous users.

- All planned features implemented
- APIs stable but may have minor adjustments
- Known bugs may exist
- Good for user feedback

```bash
git tag v0.3.0-beta.1
git push origin v0.3.0-beta.1
```

### Release Candidate (`-rc.N`)

**Purpose:** Final testing before stable release. Should be production-ready.

- Feature frozen
- Only critical bug fixes allowed
- APIs locked
- If no issues found, becomes the stable release

```bash
git tag v0.3.0-rc.1
git push origin v0.3.0-rc.1
```

## Version Progression Example

```
v0.2.2           Current stable release
    │
    ├── Development begins on v0.3.0
    │
v0.3.0-alpha.1   Early testing (internal)
v0.3.0-alpha.2   More alpha builds
    │
    ├── Feature freeze
    │
v0.3.0-beta.1    Beta testing (public)
v0.3.0-beta.2    Bug fixes during beta
    │
    ├── Code freeze
    │
v0.3.0-rc.1      Release candidate
v0.3.0-rc.2      Critical fix (if needed)
    │
v0.3.0           Stable release (becomes "Latest")
```

## Hotfix Workflow

For critical bugs in stable releases:

```
v0.2.2           Stable release with critical bug
    │
    ├── Branch: git checkout -b hotfix/0.2.3 v0.2.2
    ├── Fix the bug
    ├── Merge to main
    │
v0.2.3           Hotfix release
```

If a hotfix needs testing:
```bash
git tag v0.2.3-rc.1    # Test the fix
git tag v0.2.3         # Release if OK
```

## GitHub Release Behavior

| Tag Format | GitHub Release Type | Shown as "Latest" | Docker Tag |
|------------|---------------------|-------------------|------------|
| `v1.2.3` | Release | Yes | `latest`, `1.2.3`, `1.2`, `1` |
| `v1.2.3-alpha.1` | Pre-release | No | `1.2.3-alpha.1` |
| `v1.2.3-beta.1` | Pre-release | No | `1.2.3-beta.1` |
| `v1.2.3-rc.1` | Pre-release | No | `1.2.3-rc.1` |

The release workflow automatically detects pre-releases by checking for a hyphen in the tag.

## CI/CD Integration

### Automatic Triggers

| Event | Workflow | Result |
|-------|----------|--------|
| Push to `main` | CI | Lint + test + build |
| Pull request | CI | Lint + test + build |
| Tag `v*` | Release | Build Docker + push to ghcr.io + GitHub Release |

### Creating a Release

1. Ensure CI passes on `main`
2. Update `CHANGELOG.md` with release notes
3. Create and push the tag:
   ```bash
   git tag v0.3.0
   git push origin v0.3.0
   ```
4. Release workflow builds Docker image and creates GitHub Release

### Testing a Pre-release

```bash
# On your server
docker pull ghcr.io/seethroughlab/familiar:0.3.0-beta.1
docker compose -f docker/docker-compose.prod.yml up -d
```

## Version in Code

The version is injected at Docker build time from the git tag:

```dockerfile
# docker/Dockerfile
ARG VERSION=dev
RUN echo "${VERSION}" > /app/VERSION
```

The backend reads this at runtime:

```python
# backend/app/config.py
def get_app_version() -> str:
    version_file = Path("/app/VERSION")
    if version_file.exists():
        return version_file.read_text().strip()
    return "dev"  # Local development
```

The version is exposed via:
- `/api/v1/health/system` endpoint
- Settings UI (bottom of System Status panel)
- FastAPI OpenAPI docs

## Analysis Version

Separate from the app version, `ANALYSIS_VERSION` tracks the audio analysis pipeline:

```python
# backend/app/config.py
ANALYSIS_VERSION = 3
```

**When to bump:** When analysis output changes (new features extracted, algorithm changes).

Bumping this version causes all tracks to be re-analyzed on next library scan.

## When to Release

- **Alpha**: When you want early feedback on new features
- **Beta**: When features are complete and you need broader testing
- **RC**: When you believe it's ready for release but want final validation
- **Stable**: When RC has been tested without critical issues
- **Hotfix**: Immediately for security issues; ASAP for critical bugs
