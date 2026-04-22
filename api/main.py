from contextlib import asynccontextmanager
from fastapi import FastAPI
from api.database import engine, Base
from api.auth.router import router as auth_router
from api.compute.router import router as compute_router
from api.compute.autoscaler import autoscaler
from api.storage.router import router as storage_router

# Import models so SQLAlchemy registers them before create_all
import api.auth.models
import api.compute.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create DB tables and start the autoscaler background thread
    Base.metadata.create_all(bind=engine)
    autoscaler.start()
    yield
    # Shutdown: stop the autoscaler
    autoscaler.stop()


app = FastAPI(title="My Cloud API", version="1.0.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(compute_router)
app.include_router(storage_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "Cloud API is running"}
