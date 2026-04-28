from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.database import engine, Base
from api.auth.router import router as auth_router
from api.compute.router import router as compute_router
from api.compute.autoscaler import autoscaler
from api.storage.router import router as storage_router
from api.containers.router import router as containers_router
from api.database_service.router import router as databases_router

# Import models so SQLAlchemy registers them before create_all
import api.auth.models
import api.compute.models
import api.database_service.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create DB tables and start the autoscaler background thread
    Base.metadata.create_all(bind=engine)
    autoscaler.start()
    yield
    # Shutdown: stop the autoscaler
    autoscaler.stop()


app = FastAPI(title="My Cloud API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(compute_router)
app.include_router(storage_router)
app.include_router(containers_router)
app.include_router(databases_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "Cloud API is running"}
