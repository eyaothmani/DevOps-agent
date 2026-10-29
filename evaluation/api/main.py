"""
evaluation/api/main.py

Point d'entrée FastAPI — assemble les routers
(health, incidents, overview, performance, resources) en une
seule application servant les KPIs de l'agent (dashboard Grafana).
"""

from __future__ import annotations

from fastapi import FastAPI

from evaluation.api.routes import health, incidents, overview, performance, resources

app = FastAPI(
    title="Agent DevOps — API d'évaluation",
    description="Métriques MTTR, incidents et performance de l'agent AIOps.",
    version="1.0.0",
)

app.include_router(health.router)
app.include_router(incidents.router)
app.include_router(overview.router)
app.include_router(performance.router)
app.include_router(resources.router)
