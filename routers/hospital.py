import re
from fastapi import APIRouter, Depends, HTTPException, status, Form
from typing import Annotated, Optional
from datetime import datetime, timezone
from routers.users import UserRole
from routers.donor import find_nearby_donors
import bcrypt
import math
from pydantic import EmailStr
from bson.objectid import ObjectId
from pydantic import BaseModel
from db import hospital_requests_collection
from db import donation_responses_collection
from db import donations_records_collection
from db import users_collection
from utils import replace_mongo_id
from dependencies.authn import authenticated_user
from dependencies.authz import has_roles
from geopy.geocoders import Nominatim

# GLOBAL GEOLOCATOR INITIALIZATION
geolocator = Nominatim(user_agent="BloodDonationApp_FastAPI") 

class DonationConfirmation(BaseModel):
    donation_date: str
    recipient_info: str 

hospital_requests_router = APIRouter()

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the distance between two geographical points in kilometers."""
    R = 6371  # Radius of Earth in kilometers
    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return distance

def find_next_suitable_donor(
    request_id: str,
    blood_type: str,
    hospital_lat: float,
    hospital_lon: float,
    search_radius_km: float = 50.0 # Default search radius
) -> dict | None:
    """
    Searches for the next available and suitable donor for a request, 
    excluding all donors who have already responded (committed, failed, or completed).
    """
    
    # 2a. Identify all donors already associated with this request (to exclude them)
    existing_responses_cursor = donation_responses_collection.find({"request_id": ObjectId(request_id)})
    excluded_donor_ids = [response["donor_id"] for response in existing_responses_cursor]
    
    # 2b. Query all potential donors who match the blood type and are available
    potential_donors = users_collection.find({
        "role": "donor",
        "blood_type": blood_type,
        "availability_status": "available",
        # Ensure the donor hasn't already attempted this request
        "_id": {"$nin": excluded_donor_ids} 
    })
    
    found_donors = []
    
    # 2c. Geospatial Filtering and Distance Calculation
    for donor in potential_donors:
        try:
            donor_lat = float(donor.get("lat"))
            donor_lon = float(donor.get("lon"))
            
            distance_km = haversine_distance(hospital_lat, hospital_lon, donor_lat, donor_lon)
            
            if distance_km <= search_radius_km:
                found_donors.append({
                    "id": str(donor["_id"]),
                    "distance_km": round(distance_km, 2),
                    "full_name": donor["full_name"],
                })
        except (ValueError, TypeError):
            # Skip donors with invalid coordinates
            continue

    if not found_donors:
        return None

    # Select the closest donor 
    best_match = min(found_donors, key=lambda d: d["distance_km"])
    return best_match


@hospital_requests_router.post(
    "/hospitals/register", 
    tags=["Hospitals"], 
    status_code=status.HTTP_201_CREATED
)
def register_hospital(
    hospital_name: Annotated[str, Form()], 
    email: Annotated[EmailStr, Form()],      
    password: Annotated[str, Form(min_length=8)], 
    location_address: Annotated[str, Form()], 
):
    # Check if a user with the given email already exists
    if users_collection.count_documents({"email": email}) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists."
        )
    
    # Convert location name to coordinates
    try:
        geo_location = geolocator.geocode(location_address)
        
        if not geo_location:
            # If the service cannot find the location (e.g., misspelling or vagueness)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not determine coordinates for '{location_address}'. Please be more specific or check spelling."
            )
        
        # Extract and convert coordinates to strings for safe MongoDB storage
        hospital_lat = str(geo_location.latitude)
        hospital_lon = str(geo_location.longitude)
        
    except Exception as e:
        # Catch network or API-related errors from geopy/Nominatim
        print(f"Hospital Geocoding Error for {location_address}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing hospital location data due to external service issue. Please try again later."
        )

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    user_data = {
        "full_name": hospital_name, 
        "email": email,
        "password": hashed_password,
        "role": UserRole.HOSPITAL.value, 
        "created_at": datetime.now(timezone.utc),
        "location": location_address, 
        "lat": hospital_lat,          
        "lon": hospital_lon
    }

    users_collection.insert_one(user_data)

    return {"message": f"Hospital '{hospital_name}' registered successfully. Coordinates saved."}

# Create a new request (Hospital role)
@hospital_requests_router.post(
    "/requests",
    tags=["Hospitals"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_roles(["hospital"]))],
)
def create_request(
    current_user: Annotated[dict, Depends(authenticated_user)],
    blood_type: Annotated[str, Form()],
    quantity: Annotated[int, Form()],
    patient_condition: Annotated[str, Form()],
):
    request_data = {
        "blood_type": blood_type,
        "quantity": quantity,
        "patient_condition": patient_condition,
        "hospital_id": current_user["id"],
        "status": "active",
    }
    inserted = hospital_requests_collection.insert_one(request_data)
     # --- START NEW LOGIC FOR IMMEDIATE DONOR NOTIFICATION ---
    DEFAULT_SEARCH_RADIUS_KM = 50.0  # Set default radius for initial push/email

    try:
        # Retrieve Hospital Coordinates (stored as strings during registration)
        hospital_lat = float(current_user.get("lat", 0.0))
        hospital_lon = float(current_user.get("lon", 0.0))

        # 1. Find matching donors using the utility function
        matched_donors = find_nearby_donors(
            hospital_lat=hospital_lat,
            hospital_lon=hospital_lon,
            requested_blood_type=blood_type,
            radius_km=DEFAULT_SEARCH_RADIUS_KM
        )

        # 2. Trigger Notification (Simulation for now)
        if matched_donors:
            [d['email'] for d in matched_donors]
            # In a real system: Trigger background task to send emails/push notifications
            print(f"IMMEDIATE ALERT: New request ({blood_type}) matched {len(matched_donors)} donors.")
            # Example of how you would trigger an email or queue a job:
            # notification_queue.send_message(request_id=str(inserted.inserted_id), donors=matched_donors)
            
        else:
            print(f"IMMEDIATE ALERT: No available compatible donors found within {DEFAULT_SEARCH_RADIUS_KM}km for {blood_type}.")

    except ValueError:
        # Handle cases where hospital coordinates are missing or invalid
        print("WARNING: Could not perform immediate geospatial match due to missing hospital coordinates.")
    # --- END NEW LOGIC ---

    return {
        "message": "Blood request created successfully and immediate notifications were attempted.",
        "id": str(inserted.inserted_id),
    }


# Get all requests
@hospital_requests_router.get("/requests/all", tags=["Hospitals"])
def get_all_requests(
    search: str | None = None,
    blood_type: str | None = None,
    status: str | None = None,
    quantity_min: int | None = None,
    quantity_max: int | None = None,
    limit: int = 10,
    skip: int = 0,
):
    print(f"Received blood_type parameter: '{blood_type}'")
    query_filter = {}
    if search:
        query_filter["$or"] = [
            {"blood_type": {"$regex": search, "$options": "i"}},
            {"status": {"$regex": search, "$options": "i"}},
        ]
    if blood_type:
        escaped_blood_type = re.escape(blood_type)
        query_filter["blood_type"] = {
            "$regex": f"^{escaped_blood_type}$",
            "$options": "i",
        }
    if status:
        query_filter["status"] = {"$regex": f"^{status}$", "$options": "i"}
    quantity_filter = {}
    if quantity_min is not None:
        quantity_filter["$gte"] = quantity_min
    if quantity_max is not None:
        quantity_filter["$lte"] = quantity_max
    if quantity_filter:
        query_filter["quantity"] = quantity_filter
    print(f"Constructed MongoDB query filter: {query_filter}")
    requests = list(
        hospital_requests_collection.find(
            filter=query_filter,
            limit=int(limit),
            skip=int(skip),
        )
    )
    return {"data": list(map(replace_mongo_id, requests))}


# Get request by ID
@hospital_requests_router.get("/requests/{request_id}", tags=["Hospitals"])
def get_request_by_id(request_id):
    # check if reuest id is valid
    if not ObjectId.is_valid(request_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid request ID."
        )
    request_doc = hospital_requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request_doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    return replace_mongo_id(request_doc)

# Update a request
@hospital_requests_router.put(
    "/requests/{request_id}",
    tags=["Hospitals"],
    dependencies=[Depends(has_roles(["hospital"]))],
)
def update_request(
    request_id: str,
    blood_type_update: Optional[str] = Form(None),
    status_update: Optional[str] = Form(None),
    quantity_update: Optional[int] = Form(None),
    patient_condition_update: Optional[str] = Form(None),
):
    update_data = {}
    if blood_type_update:
        update_data["blood_type"] = blood_type_update
    if status_update:
        update_data["status"] = status_update
    if quantity_update is not None:
        update_data["quantity"] = quantity_update
    if patient_condition_update:
        update_data["patient_condition"] = patient_condition_update

    if not update_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No update fields provided.")

    result = hospital_requests_collection.update_one(
        {"_id": ObjectId(request_id)}, {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")

    return {"message": "Request updated successfully."}

@hospital_requests_router.put(
    "/responses/{response_id}/in-progress",
    tags=["Hospitals"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["hospital"]))],
)
def set_response_in_progress(
    response_id: str,
    current_user: Annotated[dict, Depends(authenticated_user)],
):
    """
    Sets a specific donor response status to 'in progress'. 
    Used by the hospital when they have confirmed an appointment with the donor.
    """
    if not ObjectId.is_valid(response_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid response ID.")

    # 1. Check if the response exists and is currently committed
    result = donation_responses_collection.update_one(
        {"_id": ObjectId(response_id), "status": "committed"},
        {"$set": {"status": "in progress"}}
    )
    
    if result.matched_count == 0:
        # Check if it was not found, or if the status was already past 'committed'
        response_doc = donation_responses_collection.find_one({"_id": ObjectId(response_id)})
        if not response_doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Donation response not found.")
        elif response_doc.get("status") == "in progress":
            return {"message": "Donation status is already 'in progress'."}
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Cannot move from status '{response_doc.get('status')}' to 'in progress'.")

    return {"message": "Donation status successfully updated to 'in progress'."}



#Delete a request 
@hospital_requests_router.delete(
    "/requests/{request_id}",
    tags=["Hospitals"],
    dependencies=[Depends(has_roles(["hospital", "admin"]))],
)
def delete_request(request_id: str):
    result = hospital_requests_collection.delete_one({"_id": ObjectId(request_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    return {"message": "Request deleted successfully."}

@hospital_requests_router.post(
    "/responses/{response_id}/confirm-donation",
    tags=["Hospitals"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_roles(["hospital"]))],
)
def confirm_donation(
    response_id: str,
    current_user: Annotated[dict, Depends(authenticated_user)],
    confirmation_token: Annotated[str, Form(min_length=4, max_length=4, description="4-digit numerical token to confirm donation")],
    donation_date: Annotated[str, Form()],
    recipient_info: Annotated[str, Form()] = "Patient Matched"
):
    if not ObjectId.is_valid(response_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid response ID.")

    # Find the original donation response from the donor
    response = donation_responses_collection.find_one({"_id": ObjectId(response_id)})
    if not response:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Donation response not found.")
    
    # Store the associated Request ID
    request_id = response["request_id"]
    # VALIDATE CONFIRMATION TOKEN
    stored_token = response.get("confirmation_token")
    if not stored_token or stored_token != confirmation_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid or missing confirmation token."
        )
     # Check to prevent creating duplicate donation records
    existing_record = donations_records_collection.find_one({
        "original_response_id": ObjectId(response_id)
    })
    if existing_record:
        raise HTTPException(status.HTTP_409_CONFLICT, "A donation record for this response already exists.")

    donor_id = response["donor_id"]
        # Create the donation record
    donation_record_data = {
        "donor_id": donor_id,
        "hospital_id": current_user["id"],
        "hospital_name": current_user.get("hospital_name") or current_user.get("full_name"), 
        "donation_date": donation_date,
        "recipient_info": recipient_info,
        "status": "Completed",
        "original_response_id": ObjectId(response_id) 
    }

    # Insert the record into the database
    donations_records_collection.insert_one(donation_record_data)
    
    #  Update the original response status
    donation_responses_collection.update_one(
        {"_id": ObjectId(response_id)},
        {"$set": {"status": "completed"}}
    )

    hospital_requests_collection.update_one(
        {"_id": request_id},
        {"$set": {"status": "fulfilled"}}
    )

    return {"message": "Donation successfully recorded and added to donor's history."}

@hospital_requests_router.get(
    "/requests/{request_id}/responses",
    tags=["Hospitals"],
    dependencies=[Depends(has_roles(["hospital"]))],
)
def get_responses_for_request(request_id: str):
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid request ID.")

    responses = donation_responses_collection.find({"request_id": ObjectId(request_id)})
    
    return [replace_mongo_id(r) for r in responses]
