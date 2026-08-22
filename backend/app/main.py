from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import allocation, market_data, performance, positions, risk, trades

app = FastAPI(title="Portfolio Analytic Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(positions.router)
app.include_router(performance.router)
app.include_router(risk.router)
app.include_router(allocation.router)


@app.get("/health")
def health():
    return {"status": "ok"}
