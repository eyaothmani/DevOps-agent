"""
Accès DynamoDB bas niveau pour l'outil manage_table.

Ce module est la seule couche qui parle directement à boto3 : connexion à
la table, scan paginé et reconstruction de la clé primaire d'un item à
partir du key_schema réel de la table.
"""

from __future__ import annotations

from typing import Any

import boto3

from .config import TABLE_NAME, validate_table_name


def get_table() -> Any:
    """Retourne la table DynamoDB configurée après validation."""
    validated_table_name = validate_table_name(TABLE_NAME)

    return boto3.resource("dynamodb").Table(validated_table_name)


def scan_all(table: Any) -> list[dict[str, Any]]:
    """Scanne toutes les écritures de la table DynamoDB."""
    items: list[dict[str, Any]] = []

    response = table.scan()
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    return items


def key_from_item(table: Any, item: dict[str, Any]) -> dict[str, Any]:
    """
    Construit la clé DynamoDB à partir du key_schema réel.

    Gère notamment incident_id + node_timestamp.
    """
    key: dict[str, Any] = {}

    for schema_item in table.key_schema:
        attribute_name = schema_item["AttributeName"]

        if attribute_name not in item:
            raise KeyError(f"Champ de clé '{attribute_name}' absent de l'item.")

        key[attribute_name] = item[attribute_name]

    return key