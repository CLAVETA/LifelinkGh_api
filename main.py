from fastapi import FastAPI
from routers.users import users_router
from routers.volunteers import volunteers_router
from routers.admin import admin_router
from routers.donor import donors_router
from routers.hospital import hospital_requests_router
from routers.campaigns import campaigns_router
from routers.educational_resources import educational_router
from routers.genai import genai_router


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

app.include_router(hospital_requests_router)

app.include_router(donors_router)

app.include_router(volunteers_router)

app.include_router(admin_router)

app.include_router(campaigns_router)

app.include_router(educational_router)

app.include_router(genai_router)