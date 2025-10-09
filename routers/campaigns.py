from fastapi import APIRouter, Depends, HTTPException, status, Form
from typing import List, Annotated, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from bson.objectid import ObjectId
from db import campaigns_collection, volunteer_signups_collection
from utils import replace_mongo_id
from dependencies.authz import has_roles, require_approved_volunteer
from routers.volunteers import SkillChoice

campaigns_router = APIRouter()
class CampaignAdminView(BaseModel):
    id: str = Field(..., alias="_id")
    title: str
    description: str
    campaign_date: str
    required_skills: List[SkillChoice]
    status: str  # e.g., "active", "planned", "completed"
    created_at: datetime

    class Config:
        populate_by_name = True
        json_encoders = {"ObjectId": str}


@campaigns_router.get(
    "/campaigns",
    tags=["Volunteers"],
    response_model=List[CampaignAdminView],
    # Only approved volunteers can see ALL campaigns
    dependencies=[Depends(require_approved_volunteer)]
)
def get_all_campaigns():
    """ Retrieves a list of ALL campaigns. Accessible to approved volunteers. """
    campaigns = campaigns_collection.find() 
    return [replace_mongo_id(c) for c in campaigns]


# Create a New Campaign
@campaigns_router.post(
    "/admin/campaigns",
    tags=["Admin - Campaigns"],
    status_code=status.HTTP_201_CREATED,
    response_model=CampaignAdminView,
    dependencies=[Depends(has_roles(["admin"]))]
)
def create_campaign(
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    campaign_date: Annotated[str, Form()],
    required_skills: Annotated[List[SkillChoice], Form()],
    status: Annotated[str, Form()] = "planned"  # Defaults to 'planned'
):
    # Check for duplicate campaign title
    if campaigns_collection.find_one({"title": title}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A campaign with the title '{title}' already exists."
        )

    campaign_data = {
        "title": title,
        "description": description,
        "campaign_date": campaign_date,
        "required_skills": [skill.value for skill in required_skills],
        "status": status,
        "created_at": datetime.utcnow()
    }
    result = campaigns_collection.insert_one(campaign_data)
    created_campaign = campaigns_collection.find_one({"_id": result.inserted_id})
    return replace_mongo_id(created_campaign)


# Get All Campaigns
@campaigns_router.get(
    "/admin/campaigns/all",
    tags=["Admin - Campaigns"],
    response_model=List[CampaignAdminView],
    dependencies=[Depends(has_roles(["admin"]))]
)
def get_all_campaigns_for_admin():
    all_campaigns = list(campaigns_collection.find())
    return [replace_mongo_id(c) for c in all_campaigns]


#  Update an Existing Campaign
@campaigns_router.put(
    "/admin/campaigns/{campaign_id}",
    tags=["Admin - Campaigns"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["admin"]))]
)
def update_campaign(
    campaign_id: str,
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    campaign_date: Optional[str] = Form(None),
    status: Optional[str] = Form(None)
):
    if not ObjectId.is_valid(campaign_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid campaign ID.")

    update_data = {}
    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if campaign_date is not None:
        update_data["campaign_date"] = campaign_date
    if status is not None:
        update_data["status"] = status

    if not update_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No update fields provided.")

    result = campaigns_collection.update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found.")

    return {"message": "Campaign updated successfully."}


# --- 4. Delete a Campaign (Admin Only) ---
@campaigns_router.delete(
    "/admin/campaigns/{campaign_id}",
    tags=["Admin - Campaigns"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["admin"]))]
)
def delete_campaign(campaign_id: str):
    if not ObjectId.is_valid(campaign_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid campaign ID.")

    # delete the campaign document
    result = campaigns_collection.delete_one({"_id": ObjectId(campaign_id)})

    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found to delete.")

    # delete any volunteer signups associated with this campaign
    volunteer_signups_collection.delete_many({"campaign_id": ObjectId(campaign_id)})

    return {"message": "Campaign and all associated signups deleted successfully."}

