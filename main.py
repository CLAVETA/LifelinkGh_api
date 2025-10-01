from fastapi import FastAPI


app = FastAPI(
    title = "LifeLink GH PLATFORM",
    description = "A voluntary blood donation and sickle cell education website"
)

# Homepage
@app.get("/", tags=["Home"])
def get_home():
    return {"message": "WELCOME TO LifeLink GH!"}