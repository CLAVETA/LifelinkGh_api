from fastapi import FastAPI
from routers.users import users_router
from routers.volunteers import volunteers_router
from routers.admin import admin_router
from routers.requests import requests_router


app = FastAPI(
    title = "LifeLink GH PLATFORM",
    description = "A voluntary blood donation and sickle cell education website"
)

# Homepage
@app.get("/", tags=["Home"])
def get_home():
    return {"message": "Welcome to LifeLink GH!!"}

# Include routers
app.include_router(users_router)

app.include_router(volunteers_router)

app.include_router(admin_router)

app.include_router(requests_router)