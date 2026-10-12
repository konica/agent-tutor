"""Sends one test span to a Phoenix and fails unless it appears in the given project (#288, ADR 0017).

Phoenix takes OTLP/HTTP as protobuf only, so this runs on the Phoenix image's own Python, which has the OpenTelemetry
protobuf classes. It reads the script on stdin, so nothing needs to be copied into a container:

  docker run --rm -i --network <network> --entrypoint /usr/bin/python3.13 [-e PHOENIX_API_KEY] <Phoenix image> - \
    http://phoenix:6006 <project> < send-test-span.py

The key, when the Phoenix has sign-in on, is the environment variable PHOENIX_API_KEY, so it is on no command line.
Runbooks: docs/runbooks/on-premise-deploy.md ("Phoenix") and the README ("Local development").
"""

import datetime
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

collector, project = sys.argv[1].rstrip("/"), sys.argv[2]
now = time.time_ns()
span = Span(
    trace_id=secrets.token_bytes(16),
    span_id=secrets.token_bytes(8),
    name="test-span",
    kind=Span.SPAN_KIND_INTERNAL,
    start_time_unix_nano=now - 1_000_000,
    end_time_unix_nano=now,
)
# Phoenix files a span under the project its resource names.
resource = Resource(attributes=[KeyValue(key="openinference.project.name", value=AnyValue(string_value=project))])
body = ExportTraceServiceRequest(
    resource_spans=[ResourceSpans(resource=resource, scope_spans=[ScopeSpans(spans=[span])])]
).SerializeToString()

headers = {"content-type": "application/x-protobuf"}
if key := os.environ.get("PHOENIX_API_KEY"):
    headers["authorization"] = f"Bearer {key}"
request = urllib.request.Request(f"{collector}/v1/traces", data=body, headers=headers, method="POST")
try:
    urllib.request.urlopen(request, timeout=10).close()
except urllib.error.HTTPError as error:
    sys.exit(f"Phoenix answered {error.code}: {error.read().decode(errors='replace')[:200]}")

# Phoenix writes spans in batches: look for this one in the project for up to 30 s. Only spans that started in the
# last minute are listed (the spans route filters on start_time), so a busy project can't push this one off the page.
since = datetime.datetime.fromtimestamp(now / 1e9 - 60, datetime.timezone.utc).isoformat()
query = urllib.parse.urlencode({"limit": 100, "start_time": since})
spans = urllib.request.Request(f"{collector}/v1/projects/{project}/spans?{query}", headers=headers)
for _ in range(15):
    time.sleep(2)
    try:
        with urllib.request.urlopen(spans, timeout=10) as response:
            found = json.load(response)["data"]
    except urllib.error.HTTPError as error:
        if error.code != 404:  # the project appears with its first span
            sys.exit(f"Phoenix answered {error.code} when listing the spans of {project}")
        continue
    if any(s["context"]["span_id"] == span.span_id.hex() for s in found):
        print(f"test-span (trace {span.trace_id.hex()}) is in the Phoenix project {project}")
        sys.exit(0)
sys.exit(f"Phoenix accepted test-span but it is not in the project {project} after 30 s")
