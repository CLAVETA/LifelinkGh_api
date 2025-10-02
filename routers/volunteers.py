from fastapi import APIRouter, Depends, HTTPException, status, Form
from typing import Annotated, List
from pydantic import BaseModel, Field, EmailStr
from enum import Enum
from dependencies.authn import authenticated_user
from dependencies.authz import has_roles, require_approved_volunteer
from db import users_collection
from utils import replace_mongo_id
from bson.objectid import ObjectId


#  Enum for Skill Choices ---
class SkillChoice(str, Enum):
    AWARENESS = "Awareness Campaigns"
    EDUCATION = "Education & Outreach"
    ORGANIZATION = "Event Organization"


#  Model for the application form data ---
class VolunteerApplicationForm(BaseModel):
    location: str = Field(..., description="e.g., City, State")
    contact_number: str
    skills: List[SkillChoice] = Field(..., description="Areas of contribution.")


# Pydantic model for displaying public volunteer info ---
class VolunteerPublicProfile(BaseModel):
    id: str = Field(..., alias="_id")
    full_name: str
    skills: List[str]

    class Config:
        populate_by_name = True
        json_encoders = {"ObjectId": str}


class VolunteerDashboardResponse(BaseModel):
    id: str = Field(..., alias="_id")
    full_name: str
    email: EmailStr
    role: str
    application_status: str

    class Config:
        populate_by_name = True
        json_encoders = {"ObjectId": str}


class ApplicationDetails(BaseModel):
    location: str
    contact_number: str
    skills: List[str]


class VolunteerView(BaseModel):
    id: str = Field(..., alias="_id")
    full_name: str
    email: EmailStr
    application_status: str
    application_details: ApplicationDetails

    class Config:
        populate_by_name = True


#  Create the router
volunteers_router = APIRouter()

#  Application Submission Endpoint ---
@volunteers_router.put(
    "/volunteers/me/apply",
    tags=["Volunteers"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["volunteer"]))],
)
def submit_volunteer_application(
    current_user: Annotated[dict, Depends(authenticated_user)],
    location: Annotated[str, Form()],
    contact_number: Annotated[str, Form()],
    skills: Annotated[List[SkillChoice], Form()],
):
    if current_user.get("application_status") != "not_applied":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You cannot apply. Your current status is: {current_user.get('application_status')}",
        )

    application_data = {
        "application_details": {
            "location": location,
            "contact_number": contact_number,
            "skills": [skill.value for skill in skills],
        },
        "application_status": "pending",
    }

    users_collection.update_one(
        {"_id": ObjectId(current_user["id"])},
        {"$set": application_data}
    )
    return {"message": "Application submitted successfully. It is now pending review."}


#  Volunteer Dashboard Endpoint ---
@volunteers_router.get(
    "/volunteers/me/dashboard",
    tags=["Volunteers"],
    response_model=VolunteerDashboardResponse,
    dependencies=[Depends(require_approved_volunteer)],
)
def get_volunteer_dashboard(
    current_volunteer: Annotated[dict, Depends(authenticated_user)],
):
    return current_volunteer


# Endpoint to Get All Approved Volunteers ---
@volunteers_router.get(
    "/volunteers",
    tags=["Volunteers"],
    # The response will be a list of public profiles
    response_model=List[VolunteerView],
    dependencies=[Depends(require_approved_volunteer)],
)
def get_all_approved_volunteers():
    # Query the database for users who are volunteers AND are approved
    approved_volunteers_cursor = users_collection.find(
        {"role": "volunteer", "application_status": "approved"}
    )
    return [replace_mongo_id(v) for v in approved_volunteers_cursor]
