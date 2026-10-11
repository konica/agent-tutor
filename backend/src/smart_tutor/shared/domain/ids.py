"""Typed identifiers shared across modules."""

from typing import NewType

UserId = NewType("UserId", str)  # Keycloak `sub`
ThreadId = NewType("ThreadId", str)
SubjectId = NewType("SubjectId", str)  # UUID in the shared subject catalog; never changes, names are separate
DocumentId = NewType("DocumentId", str)  # a learner's library entry
ContentId = NewType("ContentId", str)  # one unique file (SHA-256), shared by all documents with the same bytes
UploadId = NewType("UploadId", str)  # one presigned upload; binds uploads/<user_id>/<upload_id>.pdf to its document
RunId = NewType("RunId", str)  # an ask's LangSmith root run (UUID); minted by the API, kept with its turn
