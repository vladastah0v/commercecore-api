from fastapi import FastAPI

app = FastAPI(title="CommerceCore API", version="0.1.0")


@app.get("/api/v1/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
