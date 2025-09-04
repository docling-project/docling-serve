# Leveraging Application Metrics with Prometheus

This guide explains how to configure Prometheus to scrape metrics from Docling Serve running in Kubernetes. It assumes you already have Prometheus and the Prometheus Operator installed and configured in your cluster.

## Overview

Our application exposes a wide range of metrics in the Prometheus format at the `/metrics` endpoint. To make Prometheus aware of this endpoint, we use a `ServiceMonitor` Custom Resource Definition (CRD), which is provided by the Prometheus Operator. The `ServiceMonitor` tells Prometheus which services to monitor and how to scrape their metrics.

## 1. Creating the `ServiceMonitor`

First, you need to create a `ServiceMonitor` resource. This resource selects Docling Serve's `Service` based on labels and defines the endpoint to scrape.

```
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: docling-serve-metrics
  labels:
    release: prometheus-operator
spec:
  selector:
    matchLabels:
      app: docling-serve
      component: docling-serve-api
  endpoints:
    - interval: 30s
      path: /metrics
      scheme: http
      port: http
```

Install the servicemonitor resource with:

```sh
oc apply -f docs/deploy-examples/servicemonitor.yaml
```

### How It Works:

* **`metadata.labels`**: The `release: prometheus-operator` label is the standard way for the Prometheus Operator to discover new `ServiceMonitor`s. Your Prometheus installation might use a different label, so be sure to check its configuration.

* **`spec.selector.matchLabels`**: This is the most important part for connecting the monitor to your app. The labels here (`app: docling-serve`, `component: docling-serve-api`) must **exactly match** the labels on the Kubernetes `Service` object that fronts Docling Serve pods.

* **`spec.endpoints`**: This section specifies *how* to scrape the metrics from the pods targeted by the service.

  * `port: http`: The name of the port defined in Docling Serve's `Service` definition.

  * `path: /metrics`: The URL path where Docling Serve exposes its metrics.

  * `interval: 30s`: How frequently Prometheus should scrape the endpoint.

## 2. Verifying the Connection

After applying the `ServiceMonitor`, Prometheus will automatically detect the configuration and start scraping Docling Serve's `/metrics` endpoint.

## 3. Understanding Docling Serve Metrics

Docling Serve provides several useful metrics out of the box. Here is a breakdown of the key metrics and what they represent.

### Process & Python VM Metrics

These metrics give you insight into the health and resource consumption of the application process itself.

* `process_resident_memory_bytes`: The actual physical memory (RAM) being used by the application. This is crucial for monitoring memory leaks and setting resource limits.

* `process_cpu_seconds_total`: A counter for the total CPU time spent. You can use the `rate()` function in Prometheus to see the CPU usage over time.

* `python_gc_collections_total`: A counter for garbage collection events. A sudden spike might indicate memory pressure.

### HTTP Request Metrics

These metrics are essential for understanding traffic patterns, performance, and error rates.

* **`http_requests_total` (Counter)**: This counts every request, labeled by HTTP method, status code (2xx, 4xx, etc.), and the API handler.

  * **Use Case**: You can easily calculate the request rate and error rate for your entire application or for specific endpoints. For example, `rate(http_requests_total{status="5xx"}[5m])` will show you the rate of server errors.

* **`http_request_duration_seconds` (Histogram)**: This tracks the latency of HTTP requests. A histogram is powerful because it groups observations into configurable buckets and allows you to calculate statistical quantiles.

  * **Use Case**: Instead of just calculating an average latency (which can be misleading), you can calculate the 95th or 99th percentile latency. For example: `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler))` gives you the 99th percentile latency for each API handler.

  * **Advanced Use Case**: To monitor the median (50th percentile) latency for a specific group of critical endpoints, you can use a more complex query with regex matching. This is useful for creating targeted performance dashboards or alerts.

    ```
    histogram_quantile(0.50, sum by (le, handler) (rate(http_request_duration_seconds_bucket{job="docling-serve", handler=~"/v1/convert/file/?|/v1/convert/source/?|/v1/convert/source/async/?|/v1/convert/file/async/?|/v1/result/{task_id}/?"}[5m])))
    
    ```

### RQ (Redis Queue) Worker Metrics

These metrics monitor the health and throughput of your background job workers.

* **`rq_workers` (Gauge)**: Shows the current number of workers and their state (`idle`, `busy`, etc.).

  * **Use Case**: Monitor if you have enough workers to handle the job load. You can create an alert if the number of `idle` workers is zero for an extended period.

* **`rq_workers_failed_total` (Counter)**: A critical metric that counts the total number of failed jobs.

  * **Use Case**: This is a primary candidate for alerting. A non-zero rate of failed jobs almost always requires investigation. `rate(rq_workers_failed_total[5m]) > 0` is a simple but effective alert rule.

* **`rq_jobs` (Gauge)**: Shows the number of jobs in each queue by their status (e.g., `queued`, `finished`, `failed`).

  * **Use Case**: Track queue length to understand if your workers can keep up with the rate of new jobs being enqueued. An ever-growing queue size is a sign that you need to scale up your workers.
