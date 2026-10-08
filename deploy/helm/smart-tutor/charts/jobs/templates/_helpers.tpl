{{- define "jobs.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
