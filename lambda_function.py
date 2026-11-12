"""
Função AWS Lambda: lê o JSON de métricas enviado ao S3 pelo ExemploS3Metrics
e publica uso de CPU, memória e disco como métricas customizadas no CloudWatch.

Encadeamento:
    ExemploS3Metrics (Java) --PUT--> S3 (metrics/*.json) --evento--> Lambda --PutMetricData--> CloudWatch

JSON esperado (gerado pelo ExemploS3Metrics):
{
  "timestamp": "2026-11-12T23:05:29.482533556Z",
  "hostname": "ip-172-31-10-20",
  "cpu":    { "usagePercent": 2.85 },
  "memory": { "total": 16867414016, "used": 602529792, "usagePercent": 3.57 },
  "disk":   { "mountPoint": "/", "total": 270553174016, "used": 238429499392, "usagePercent": 88.13 }
}
"""

import json
import os
import re
import urllib.parse
from datetime import datetime, timezone

import boto3

# Namespace onde as métricas aparecem no CloudWatch (pode ser alterado por variável de ambiente)
NAMESPACE = os.environ.get("NAMESPACE", "ExemploS3Metrics")

s3 = boto3.client("s3")
cloudwatch = boto3.client("cloudwatch")


def lambda_handler(event, context):
    """Ponto de entrada da Lambda. O S3 pode enviar um ou mais registros por evento."""
    published = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # A chave chega codificada em URL no evento (ex.: espaço vira '+')
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        print(f"Lendo s3://{bucket}/{key}")
        obj = s3.get_object(Bucket=bucket, Key=key)
        metrics = json.loads(obj["Body"].read())

        metric_data = build_metric_data(metrics)
        cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data)

        summary = {m["MetricName"]: m["Value"] for m in metric_data}
        print(f"Publicado em {NAMESPACE}: {json.dumps(summary)}")
        published.append({"key": key, "metrics": summary})

    return {"statusCode": 200, "body": json.dumps(published)}


def build_metric_data(metrics):
    """Converte o JSON do ExemploS3Metrics na lista MetricData do CloudWatch."""
    timestamp = parse_timestamp(metrics.get("timestamp"))
    dimensions = [{"Name": "Host", "Value": metrics.get("hostname") or "desconhecido"}]

    values = {
        "CPUUsage": metrics["cpu"]["usagePercent"],
        "MemoryUsage": metrics["memory"]["usagePercent"],
        "DiskUsage": metrics["disk"]["usagePercent"],
    }

    return [
        {
            "MetricName": name,
            "Dimensions": dimensions,
            "Timestamp": timestamp,
            "Value": float(value),
            "Unit": "Percent",
        }
        for name, value in values.items()
    ]


def parse_timestamp(value):
    """
    Converte o timestamp ISO-8601 do Java (ex.: 2026-11-12T20:05:29.482533556-03:00)
    para datetime. O Java gera até 9 casas decimais; o Python aceita no máximo 6.
    Se não houver timestamp válido, usa o horário atual.
    """
    if not value:
        return datetime.now(timezone.utc)
    value = value.replace("Z", "+00:00")
    value = re.sub(r"(\.\d{6})\d+", r"\1", value)  # trunca para microssegundos
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        print(f"Timestamp inválido '{value}', usando horário atual")
        return datetime.now(timezone.utc)
