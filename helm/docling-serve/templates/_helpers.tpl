{{/*
Expand the name of the chart.
*/}}
{{- define "docling-serve.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "docling-serve.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "docling-serve.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "docling-serve.labels" -}}
helm.sh/chart: {{ include "docling-serve.chart" . }}
{{ include "docling-serve.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "docling-serve.selectorLabels" -}}
app.kubernetes.io/name: {{ include "docling-serve.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API component labels
*/}}
{{- define "docling-serve.apiLabels" -}}
{{ include "docling-serve.labels" . }}
component: {{ include "docling-serve.name" . }}-api
{{- end }}

{{/*
RQ Worker component labels
*/}}
{{- define "docling-serve.workerLabels" -}}
app.kubernetes.io/name: {{ include "docling-serve.name" . }}-rq-workers
app.kubernetes.io/instance: {{ .Release.Name }}
component: {{ include "docling-serve.name" . }}-rq-worker
{{- end }}

{{/*
Redis component labels
*/}}
{{- define "docling-serve.redisLabels" -}}
app.kubernetes.io/name: {{ include "docling-serve.name" . }}-redis
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
