from fastapi import FastAPI
from api.database import engine, Base
from api.auth.router import router as auth_router

# Create all DB tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="My Cloud API", version="1.0.0")

app.include_router(auth_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "Cloud API is running"}
