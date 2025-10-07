from fastapi import APIRouter, Depends, HTTPException, status, Form
from typing import Annotated, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr
from enum import Enum
import bcrypt
from dependencies.authn import authenticated_user
from dependencies.authz import require_approved_volunteer
from db import users_collection
from db import volunteer_signups_collection
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

# Volunteer Registration and Application Endpoint
@volunteers_router.post(
    "/volunteers/register",
    tags=["Volunteers"],
    status_code=status.HTTP_201_CREATED
)
def register_and_apply_volunteer(
    full_name: Annotated[str, Form()],
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
    location: Annotated[str, Form()],
    contact_number: Annotated[str, Form()],
    skills: Annotated[List[SkillChoice], Form()],
):
    # Check if a user with this email already exists
    if users_collection.find_one({"email": email}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists."
        )

    # Hash the user's password securely
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    # Construct the complete user document in one go
    volunteer_data = {
        "full_name": full_name,
        "email": email,
        "password": hashed_password,
        "role": "volunteer",  
        "created_at": datetime.now(timezone.utc),

        # Application details are nested for clean data structure
        "application_details": {
            "location": location,
            "contact_number": contact_number,
            "skills": [skill.value for skill in skills], 
        },
        
        # The status is set directly to 'pending' for admin review
        "application_status": "pending",
    }

    # Insert the new volunteer document into the database
    users_collection.insert_one(volunteer_data)
    return {"message": "Volunteer application submitted successfully. It is now pending review."}


#  Volunteer Dashboard Endpoint
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


# Endpoint to Get All Approved Volunteers
@volunteers_router.get(
    "/volunteers",
    tags=["Volunteers"],
    response_model=List[VolunteerView],
    dependencies=[Depends(require_approved_volunteer)],
)
def get_all_approved_volunteers():
    # Query the database for users who are volunteers and are approved
    approved_volunteers_cursor = users_collection.find(
        {"role": "volunteer", "application_status": "approved"}
    )
    return [replace_mongo_id(v) for v in approved_volunteers_cursor]

@volunteers_router.post(
    "/campaigns/{campaign_id}/signup",
    tags=["Volunteers"],
    status_code=status.HTTP_201_CREATED
)
def signup_for_campaign(
    campaign_id: str,
    current_user: Annotated[dict, Depends(require_approved_volunteer)]
):
    # Validate the Campaign ID
    if not ObjectId.is_valid(campaign_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid campaign ID."
        )

    # Check if the volunteer is already signed up for this campaign
    existing_signup = volunteer_signups_collection.find_one({
        "campaign_id": ObjectId(campaign_id),
        "volunteer_id": ObjectId(current_user["id"])
    })
    if existing_signup:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You have already signed up for this campaign."
        )
    signup_data = {
        "campaign_id": ObjectId(campaign_id),
        "volunteer_id": ObjectId(current_user["id"]),
        "volunteer_name": current_user["full_name"],
        "status": "confirmed",
        "signed_up_at": datetime.now(timezone.utc)
    }
    inserted = volunteer_signups_collection.insert_one(signup_data)

    return {
        "message": "Successfully signed up for the campaign!",
        "signup_id": str(inserted.inserted_id)
    }
