from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return the API health status."""
    return {"status": "ok"}