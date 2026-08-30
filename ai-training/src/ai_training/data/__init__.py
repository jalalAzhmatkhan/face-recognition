"""Data engineering: S3 dataset snapshots (manifests, not copies) - TR-04.

Rule: media bytes never rest on local disk; workers stream S3 objects
in-memory/tmpfs and delete immediately (NFR-SEC-02).
"""
