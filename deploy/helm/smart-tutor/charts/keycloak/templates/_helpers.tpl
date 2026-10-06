{{- define "keycloak.labels" -}}
app.kubernetes.io/name: keycloak
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "keycloak.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
