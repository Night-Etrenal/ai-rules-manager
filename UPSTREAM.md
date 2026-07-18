# Upstream Relationship

AI Rules Manager is an independent MIT-licensed derivative project, not an official fork distribution of `planning-with-files`.

## What was retained conceptually

- Persistent planning files as durable agent memory
- Separate plan, findings and progress records
- Context recovery after agent resets or compaction
- Plan integrity attestation
- Isolated planning directories for concurrent tasks

## What was replaced

- Product name, package metadata and installation flow
- Cross-IDE compatibility matrix
- Claude-specific commands and plugin packaging
- High-frequency plan recitation defaults
- Original rule text and marketing material
- Original repository support, security and release links

## Sync policy

Upstream changes are reviewed manually. They are never merged automatically into a release branch. Security-relevant ideas may be independently reimplemented after code review and tests. This prevents an unreviewed upstream hook or shell script from entering trusted development environments.
