{{- define "agent.labels" -}}
app.kubernetes.io/name: agent
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agent.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
