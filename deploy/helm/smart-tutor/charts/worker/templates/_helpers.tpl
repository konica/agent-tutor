{{- define "worker.labels" -}}
app.kubernetes.io/name: api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "worker.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
