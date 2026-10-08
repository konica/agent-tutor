{{- define "api.labels" -}}
app.kubernetes.io/name: api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "api.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
