# Declarative project and lock format v1

`efloud.toml` is human-edited acquisition and dataset **intent**. `efloud.lock` is
machine-generated exact **resolved state**. They are deliberately different files.
The TOML declaration is not a second semantic model: each source becomes the same
`Source` object used by the Python API, each dataset becomes the same `DatasetSpec`,
and `[sync]` becomes `SyncRequest`.

## `efloud.toml`

The top-level schema is strict and versioned:

```toml
schema_version = 1

[sync]
include_derived = true
dry_run = false
max_concurrency = 4
refresh = false
refresh_source_ids = []

[[sources]]
id = "catalog"
adapter = "efloud:http"
adapter_version = "1" # optional execution constraint
role = "catalog"
tags = ["pdb"]

[sources.config]
url = "https://example.test/catalog.json"

[[sources]]
id = "analysis-input"
adapter = "efloud:local"
role = "analysis-input"

[sources.config]
path = "inputs/analysis.json"
artifact_key = "analysis:input"
media_type = "application/json"

[[datasets]]
name = "analysis"
metadata = { purpose = "reproducible-analysis" }
constraints = { complete_snapshots = true }

[[datasets.selections]]
kind = "latest"
artifact_key = "analysis:input"
role = "configuration"

[[datasets.selections]]
kind = "source-selection"
source_id = "catalog"
role_filter = "catalog"
tags = ["pdb"]
prefix = "source:catalog:"
role = "catalog-entry"
```

Unknown fields and unsupported schema versions fail rather than being silently
ignored or normalized as historical forms.

### Source declaration

Every `[[sources]]` table has:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable project-local source identity. |
| `adapter` | yes | Stable namespaced adapter identity, e.g. `efloud:http`. |
| `adapter_version` | no | Exact adapter-version constraint checked during planning. |
| `description` | no | Human description. |
| `role` | no | Semantic source role. |
| `tags` | no | Semantic source tags. |
| `config` | yes/empty | Adapter-specific declarative configuration. |
| `provider` | collection only | Stable reference to advanced executable collection behavior. |

There is no closed source-kind enum. Unknown namespaced adapters load as a generic
declarative source and can be handled by an explicitly registered adapter. Built-in
adapters receive their normal typed source objects.

Built-in `config` schemas are:

- `efloud:http`: `url`, optional `cache_name`, optional `expected_integrity`.
- `efloud:rest`: `url`, optional `cache_name`, optional `expected_integrity`.
- `efloud:local`: `path`, optional `artifact_key`, optional `media_type`, optional
  `expected_integrity`.
- `efloud:rsync`: `url`, optional `paths`, `local_subpath`, `port`, `include`, and
  `exclude`.
- `efloud:collection`: `url`; executable enumeration behavior is named separately
  by `provider`.

An integrity assertion is represented as:

```toml
expected_integrity = [
  { algorithm = "sha256", digest = "...", required = true, metadata = { origin = "publisher" } },
]
```

A relative `efloud:local` path is always resolved relative to the directory
containing `efloud.toml`, never the process current working directory.

### Advanced collection providers

Python callbacks are never serialized. A collection instead names a stable provider
identity/version plus JSON-compatible parameters:

```toml
[[sources]]
id = "pdb-core-entry"
adapter = "efloud:collection"

[sources.config]
url = "https://data.rcsb.org/rest/v1/core/entry"

[sources.provider]
id = "bvp:pdb-core-entry"
version = "1"
parameters = { holdings_source = "pdb-holdings" }
```

The application supplies an `efloud.project.CollectionProvider` registered under
that identity. Efloud requires the provider's runtime identity and version to match
the declaration exactly and records them in the source definition and lock. The
provider receives a narrow collection source plus declarative parameters and returns
a `CollectionDefinition`; it never receives the repository writer.

### Dataset declaration

Each `[[datasets]]` table has a unique `name`, optional JSON-compatible `metadata`,
optional `constraints`, and one or more `[[datasets.selections]]`. The selection
records are the canonical serialized forms of the Python dataset selectors:

| `kind` | Fields |
| --- | --- |
| `exact` | `observation_id`, optional member `role` |
| `latest` | `artifact_key`, optional member `role` |
| `latest-before` | `artifact_key`, `timestamp`, optional member `role` |
| `latest-all` | optional `before`, optional member `role` |
| `source-selection` | optional `source_id`, `role_filter`, `tags`, `prefix`, `after`, `before`, member `role` |
| `source-snapshot` | `snapshot_id`, optional member `role` |
| `latest-complete-source-snapshot` | `source_id`, optional `before`, optional member `role` |

Temporal values may be finite Unix timestamps, TOML offset datetimes, or RFC 3339
strings. They normalize to repository-observation timestamps, which is the same
semantic representation used by `DatasetSpec`.

Dataset constraints map directly to `DatasetConstraints`:

```toml
constraints = {
  same_run = true,
  max_observation_skew = 60.0,
  complete_snapshots = true,
  validations = [["validator-id", "validator-version"]]
}
```

`Project.dataset(name)` returns the corresponding `DatasetSpec` and
`Project.resolve_datasets(repo)` resolves the declared datasets using the ordinary
public dataset boundary.

### Sync intent

`[sync]` maps one-to-one to `SyncRequest`: `source_ids`, `include_derived`,
`dry_run`, `max_concurrency`, `refresh`, and `refresh_source_ids`. Omitting a field
uses the same default as `SyncRequest`.

## `efloud.lock`

`efloud.lock` is canonical JSON generated from a project after acquisition. It is
not hand-edited. Version 1 contains:

```json
{
  "version": 1,
  "lock_id": "...",
  "declaration_id": "...",
  "declaration": { "...normalized efloud.toml intent...": "..." },
  "sources": [
    {
      "source_id": "catalog",
      "definition_id": "...",
      "definition": { "...": "..." },
      "adapter": { "id": "efloud:http", "version": "1" },
      "snapshot": { "snapshot_id": "...", "complete": true, "...": "..." },
      "resolution": { "...detached dataset manifest for exact source membership...": "..." }
    }
  ],
  "datasets": [
    {
      "name": "analysis",
      "specification_id": "...",
      "dataset_id": "...",
      "content_identity": "...",
      "manifest": { "...detached dataset manifest...": "..." }
    }
  ],
  "signatures": []
}
```

`declaration_id` is computed over the normalized declaration, so comments, TOML
whitespace, table ordering, and equivalent temporal syntax do not change semantic
identity. `lock_id` is computed over the entire unsigned resolved payload. The
`signatures` array is deliberately excluded from `lock_id` so authentication can be
added or rotated without changing what was resolved.

By default, lock creation requires every declared source to have a complete exact
snapshot. `require_complete=False` permits an evidence lock containing an incomplete
snapshot, but `ProjectLock.complete` is then false and the missing exact source
resolution is explicit. Incomplete evidence never proves absence or complete
reproducibility.

Source locks record source-definition revision identity, exact adapter version,
optional provider identity/version/parameters, exact snapshot evidence, and a
detached source-membership manifest containing artifact/observation/content
identities. Dataset locks reuse the detached dataset-manifest v1 format and therefore
retain exact membership, source-revision evidence, specification identity, dataset
identity, and content identity.

## Signatures

Lock integrity and authenticity are separate:

- deterministic IDs and SHA-256 content identities establish integrity;
- an Ed25519 signature establishes that a holder of an externally trusted key
  attested to that exact lock payload.

The lock never embeds a trusted public key. Each signature contains only
`algorithm`, `key_id`, and the base64 signature. `ProjectLock.verify_signatures()`
receives trusted public keys from the caller and an optional `SignaturePolicy`.
Unsigned locks remain supported. Signing support is installed with
`efloud[signing]`.

```python
from efloud.lockfile import ProjectLock, SignaturePolicy

lock = ProjectLock.load("efloud.lock")
assert lock.verify_signatures(
    {"release-key": trusted_raw_ed25519_public_key},
    policy=SignaturePolicy(require_signed=True, required_key_ids=("release-key",)),
)
```

Raw private/public key material is intentionally not generated, persisted, or
managed by Efloud; key lifecycle belongs to the calling application or deployment.
