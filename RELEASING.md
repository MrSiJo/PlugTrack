# Container images, CI & releases

## Container images

Images are published to the GitHub Container Registry:

- `ghcr.io/mrsijo/plugtrack-api`
- `ghcr.io/mrsijo/plugtrack-ui`

Both images are built for `linux/amd64` and `linux/arm64` (Raspberry Pi 4/5 and Apple Silicon work).

Tags published by CI:

| Trigger                                | Tags produced                                       |
| -------------------------------------- | --------------------------------------------------- |
| push to `main`                         | `latest`, `sha-<short>`                             |
| release-please PR merged (cuts a tag)  | `X.Y.Z`, `X.Y`, `X`, `latest`                       |
| pull request                           | (build-only, no push)                               |

Two workflows drive publishing:

- `.github/workflows/build-images.yml` — every push to `main` produces `:latest` + `:sha-<short>`.
- `.github/workflows/release-please.yml` — automates semantic-versioned releases (below).

## Versioned releases — automated via release-please

Versioning follows [Conventional Commits](https://www.conventionalcommits.org/) and is fully automated:

1. Push commits to `main` with prefixes like `feat:`, `fix:`, `feat!:` (breaking), or `chore:`/`docs:`/`ci:` (no version bump).
2. [release-please](https://github.com/googleapis/release-please) maintains a `chore(main): release X.Y.Z` PR that accumulates everything since the last release, with an auto-generated `CHANGELOG.md` and the proposed version (`feat:` → minor, `fix:` → patch, `feat!:` → major).
3. **Merging that PR** cuts the `vX.Y.Z` git tag, creates the matching GitHub Release, and (via a dispatch from `release-please.yml`) runs the multi-arch image build, pushing `:X.Y.Z`, `:X.Y`, `:X`, and `:latest` to GHCR. (The image tags drop the leading `v`; the dispatch is explicit because a `GITHUB_TOKEN`-created tag can't trigger another workflow.)

State is tracked in `.release-please-manifest.json`. To skip a release for a window, simply don't merge the Release PR — it will keep accumulating until you do.
