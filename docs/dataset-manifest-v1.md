# Detached dataset manifest v1

`DatasetManifest` is Efloud's detached, domain-neutral handoff format. A consumer can validate a materialized dataset using this JSON document and the exported files only; it does not need Efloud, SQLite, the source repository, or knowledge of the repository's content-addressed storage layout.

## Encoding and envelope identity

The serialized manifest is UTF-8 JSON followed by one newline. Canonical JSON for identity calculations uses sorted object keys, no insignificant whitespace, and UTF-8 characters without ASCII escaping.

Stable identities have the form:

```text
<prefix>:sha256(canonical-json(value))
```

where the digest is lowercase hexadecimal.

The top-level `manifest_id` is computed as `stable_id("dataset-manifest-v1", payload)`, where `payload` is the complete top-level object excluding `manifest_id`.

## Top-level fields

A v1 manifest contains:

- `version`: integer `1`.
- `dataset_id`: identity of exact observation membership, including member roles.
- `content_identity`: identity of logical membership plus immutable content identities, including member roles.
- `specification_id`: identity of the complete intensional dataset definition.
- `definition`: the canonical dataset selection/constraint definition that produced this handoff.
- `members`: exact exported members in canonical artifact-key order.
- `resolution`: recorded resolution evidence, including snapshot and constraint evidence when applicable.
- `manifest_id`: digest envelope over all preceding fields.

The identities are computed from:

```text
specification_id = stable_id("dataset-specification", definition)

dataset_id = stable_id("dataset", [
  {
    "artifact_key": member.artifact_key,
    "observation_id": member.observation_id,
    "role": member.role,
  },
  ...
])

content_identity = stable_id("dataset-content", [
  {
    "artifact_key": member.artifact_key,
    "content_id": member.content_id,
    "role": member.role,
  },
  ...
])
```

Member arrays used for those identities are ordered by artifact key. Artifact keys are unique within a dataset.

## Member fields

Each member contains:

- `artifact_key`: logical artifact identity.
- `observation_id`: exact repository observation selected into the dataset.
- `content_id`: immutable content identity, currently `sha256:<64 lowercase hexadecimal characters>`.
- `role`: optional role assigned by the dataset specification.
- `path`: explicit relative POSIX export path.
- `byte_size`: exact byte length.
- `media_type`: optional recorded media type.
- `observation`: detached semantic observation evidence.
- `source_revision`: the exact source-definition revision associated with the observation, or `null` for observations without source-revision evidence.

The detached observation must agree with the member's artifact, observation, and content identities. Its identity is:

```text
observation_id = stable_id("obs", {
  "kind": "content",
  "artifact_key": artifact_key,
  "content_id": content_id,
  "run_id": observation.run_id,
  "operation_id": observation.operation_id,
  "observed_at": observation.observed_at,
  "source_path": observation.source_path or null,
  "upstream_locator": observation.upstream_locator or null,
})
```

When `source_revision` is present, its identity is:

```text
source_revision.revision_id = stable_id("source-definition", {
  "source_id": observation.source_id,
  "definition": source_revision.definition,
})
```

## Byte verification

For every member, a detached consumer should:

1. Resolve `path` beneath the export root and reject any path that escapes that root.
2. Read the referenced regular file through the materialized layout.
3. Check its length against `byte_size`.
4. Compute SHA-256 and require `"sha256:" + digest == content_id`.

A missing export root, missing member, escaping symlink, size mismatch, or digest mismatch is a verification failure.

`DatasetManifest.verify()` implements these checks and returns `False` for unavailable or mismatching exported content. Manifest structural/identity damage is rejected while parsing with `DatasetManifest.from_bytes()`.

## Snapshot and constraint evidence

`resolution` records the evidence used when the dataset was resolved. Snapshot-backed selections include the exact source snapshot records used for resolution; a snapshot's `complete` field and evidence describe whether membership was completely observed. Constraint results record evaluated reproducibility/coherence requirements.

Consumers that require complete source membership should inspect the relevant recorded snapshot/constraint evidence rather than inferring completeness from the presence or absence of files in the export.

## Export safety and independence

Export paths are logical relative paths. They never encode the source repository's SQLite location, CAS path, inode, or other storage placement.

Efloud assembles exports in a sibling staging directory, verifies the staged bytes, writes this manifest, flushes the tree, and publishes without replacing an existing destination. Copy and reflink exports are independent of authoritative repository content. Symlink exports point only to private copied content inside the export's `.content` directory.

The manifest is an integrity record, not a cryptographic signature or proof of authenticity. A party that can replace both the manifest and all exported bytes can construct another internally valid dataset.