import re
from fastapi import APIRouter, Depends, HTTPException, status, Form, Query
from typing import Annotated, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from bson.objectid import ObjectId
from db import educational_resources_collection 
from dependencies.authn import authenticated_user
from dependencies.authz import has_roles
from utils import replace_mongo_id 
from dotenv import load_dotenv

load_dotenv()

class EducationalResource(BaseModel):
    id: str 
    title: str
    content: str
    category: str
    author_id: str
    created_at: datetime
    external_url: Optional[str] = None 


educational_router = APIRouter()


@educational_router.post(
    "/resources",
    tags=["Educational Resources"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_roles(["hospital", "admin"]))],
)
def create_resource(
    current_user: Annotated[dict, Depends(authenticated_user)],
    title: Annotated[str, Form(min_length=5)],
    content: Annotated[str, Form(min_length=20)],
    category: Annotated[str, Form(description="e.g., Eligibility, Post-Care, Facts, Q&A")],
    external_url: Annotated[Optional[str], Form(description="Optional link to an external resource.")] = None,
):
    resource_data = {
        "title": title,
        "content": content,
        "category": category,
        "author_id": current_user["id"],
        "author_name": current_user.get("full_name") or current_user.get("hospital_name"),
        "created_at": datetime.now(timezone.utc),
    }

    if external_url:
        resource_data["external_url"] = external_url

    try:
        inserted = educational_resources_collection.insert_one(resource_data)
    except Exception as e:
        print(f"Database insertion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save resource to the database."
        )

    return {
        "message": "Educational resource created successfully.",
        "id": str(inserted.inserted_id),
    }

@educational_router.get(
    "/resources/all",
    tags=["Educational Resources"],
    response_model=List[EducationalResource],
)
def get_all_resources(
    category: Annotated[Optional[str], Query(description="Filter by resource category.")] = None,
    search: Annotated[Optional[str], Query(description="Search in title or content.")] = None,
):
    query_filter = {}

    if category:
        query_filter["category"] = {"$regex": re.escape(category), "$options": "i"}
    
    if search:
        search_regex = {"$regex": re.escape(search), "$options": "i"}
        query_filter["$or"] = [
            {"title": search_regex},
            {"content": search_regex},
        ]
    resources = educational_resources_collection.find(query_filter).sort("created_at", -1)
    
    return [replace_mongo_id(r) for r in resources]

@educational_router.get(
    "/resources/{resource_id}",
    tags=["Educational Resources"],
    response_model=EducationalResource
)
def get_resource_by_id(resource_id: str):
    if not ObjectId.is_valid(resource_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid resource ID format."
        )
    
    resource_doc = educational_resources_collection.find_one({"_id": ObjectId(resource_id)})
    
    if not resource_doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Educational resource not found.")
    
    return replace_mongo_id(resource_doc)

@educational_router.put(
    "/resources/{resource_id}",
    tags=["Educational Resources"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["hospital", "admin"]))],
)
def update_resource(
    current_user: Annotated[dict, Depends(authenticated_user)],
    resource_id: str,
    title: Annotated[str, Form(min_length=5)],
    content: Annotated[str, Form(min_length=20)],
    category: Annotated[str, Form(description="e.g., Eligibility, Post-Care, Facts, Q&A")],
    external_url: Annotated[Optional[str], Form(description="Optional link to an external resource.")] = None,
):
    if not ObjectId.is_valid(resource_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid resource ID format."
        )

    update_data = {
        "title": title,
        "content": content,
        "category": category,
        "external_url": external_url,
    }

    try:
        result = educational_resources_collection.update_one(
            {"_id": ObjectId(resource_id)},
            {"$set": update_data}
        )
    except Exception as e:
        print(f"Database update error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update resource in the database."
        )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Educational resource not found.")
    
    return {
        "message": "Educational resource updated successfully.",
        "id": resource_id,
    }

@educational_router.delete(
    "/resources/{resource_id}",
    tags=["Educational Resources"],
    dependencies=[Depends(has_roles(["hospital", "admin"]))],
)
def delete_resource(resource_id: str):
    if not ObjectId.is_valid(resource_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid resource ID format."
        )

    result = educational_resources_collection.delete_one({"_id": ObjectId(resource_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Educational resource not found.")
        
    return {"message": "Educational resource deleted successfully."}