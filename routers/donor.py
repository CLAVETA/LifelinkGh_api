from fastapi import APIRouter, Form, status, Depends, HTTPException, Query
from datetime import datetime, timezone
from dependencies.authn import authenticated_user
from typing import Annotated, List
from pydantic import EmailStr, BaseModel
from db import donation_responses_collection
from db import donations_records_collection
from db import users_collection
from bson.objectid import ObjectId
from routers.users import create_user_in_db, UserRole 
import math
from geopy.geocoders import Nominatim

# GLOBAL GEOLOCATOR INITIALIZATION 
geolocator = Nominatim(user_agent="BloodDonationApp_FastAPI") 

class DonationResponse(BaseModel):
    id: str
    request_id: str
    donor_id: str
    status: str
    responded_at: str

class DonationRecord(BaseModel):
    id: str
    donation_date: str
    location: str 
    recipient_info: str 
    status: str

donors_router = APIRouter()

# HELPER FUNCTION FOR GEOSPATIAL DISTANCE (Haversine Formula Approximation)
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371 # Radius of Earth in kilometers
    
    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance 

# DONOR MATCHING (GEOLOCATION)
@donors_router.get(
    "/donors/search",
    tags=["Hospitals"],
    status_code=status.HTTP_200_OK
)
def search_available_donors(
    current_user: Annotated[dict, Depends(authenticated_user)],
    blood_type: Annotated[str, Query(description="The blood type to search for (e.g., O+, AB-).")],
    lat: Annotated[float, Query(description="The latitude of the hospital/request location.")],
    lon: Annotated[float, Query(description="The longitude of the hospital/request location.")],
    radius: Annotated[float, Query(description="The search radius in kilometers (km).", ge=1.0, le=100.0)]
):
    # AUTHORIZATION CHECK (Hospital Role Required)
    if current_user["role"] != UserRole.HOSPITAL.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only users with the 'HOSPITAL' role can search for donors."
        )

    # DATABASE QUERY & FILTERING
    potential_donors = users_collection.find({ 
        "role": UserRole.DONOR.value,
        "blood_type": blood_type,
        "availability_status": "available" 
    })
    
    found_donors = []
    
    # GEOSPATIAL FILTERING (Manually filtering via Haversine)
    for donor in potential_donors:
        try:
            lat_value = donor.get("lat")
            lon_value = donor.get("lon")
            
            # Skip donor if coordinates are missing
            if lat_value is None or lon_value is None:
                print(f"Skipping donor {donor.get('_id')}: Missing latitude/longitude data.")
                continue

            # Convert to float for calculation (coordinates are stored as strings)
            donor_lat = float(lat_value)
            donor_lon = float(lon_value)
            
            distance_km = haversine_distance(lat, lon, donor_lat, donor_lon)

            if distance_km <= radius:
                # Donor is within the search radius
                found_donors.append({
                    "id": str(donor["_id"]),
                    "full_name": donor["full_name"],
                    "phone_number": donor["phone_number"],
                    "blood_type": donor["blood_type"],
                    "distance_km": round(distance_km, 2), 
                    "location_details": donor.get("location") 
                })
                
        except ValueError:
            # Handle cases where 'lat' or 'lon' are not valid numbers
            print(f"!!!! ERROR: Coordinate values are not valid numbers for donor {donor.get('_id')}")
            continue
        except Exception as e:
            print(f"!!!! ERROR: Failed to process donor {donor.get('_id')}. Reason: {e}")
            continue

    # RESPONSE
    if not found_donors:
        return {"message": f"No available '{blood_type}' donors found within {radius}km."}
    
    return {
        "message": f"Found {len(found_donors)} available '{blood_type}' donors within {radius}km.",
        "donors": found_donors
    }

@donors_router.post("/donors/register", tags=["Donors"], status_code=status.HTTP_201_CREATED)
def register_donor(
    full_name: Annotated[str, Form()],
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
    phone_number: Annotated[str, Form()],
    blood_type: Annotated[str, Form()],
    date_of_birth: Annotated[str, Form()],
    location: Annotated[str, Form()],
):
    
    # Convert location name to coordinates
    try:
        geo_location = geolocator.geocode(location)
        
        if not geo_location:
            # If the service cannot find the location (e.g., misspelling or vagueness)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not determine coordinates for '{location}'. Please be more specific or check spelling."
            )
        
        # Extract and convert coordinates to strings for safe MongoDB storage
        donor_lat = str(geo_location.latitude)
        donor_lon = str(geo_location.longitude)
        
    except Exception as e:
        # Catch network or API-related errors from geopy/Nominatim
        print(f"Geocoding Error for {location}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing location data due to external service issue. Please try again later."
        )

    user_data = {
        "full_name": full_name,
        "email": email,
        "password": password,
        "role": UserRole.DONOR.value,
        "phone_number": phone_number,
        "blood_type": blood_type,
        "date_of_birth": date_of_birth,
        "location": location,
        "availability_status": "available",
        "lat": donor_lat,
        "lon": donor_lon
    }
    
    create_user_in_db(user_data)

    return {"message": f"Donor '{full_name}' registered successfully and coordinates for '{location}' were saved."}


@donors_router.post(
    "/donors/requests/{request_id}/respond",
    tags=["Donors"],
    status_code=status.HTTP_201_CREATED
)
def respond_to_request(
    request_id: str,
    current_user: Annotated[dict, Depends(authenticated_user)],
    commitment_status: Annotated[str, Form()] = "committed" 
):
    # Check if the request ID is valid
    if not ObjectId.is_valid(request_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid request ID."
        )

    # Check if the donor has already responded to this request
    existing_response = donation_responses_collection.find_one({
        "request_id": ObjectId(request_id),
        "donor_id": current_user["id"]
    })
    if existing_response:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You have already responded to this request."
        )

    # Create the new response document
    response_data = {
        "request_id": ObjectId(request_id),
        "donor_id": current_user["id"],
        "status": commitment_status,
        "responded_at": datetime.now(timezone.utc)
    }
    inserted = donation_responses_collection.insert_one(response_data)
    
    return {
        "message": "Your response has been recorded. The hospital will be notified.",
        "response_id": str(inserted.inserted_id)
    }

@donors_router.get(
    "/donors/me/history",
    tags=["Donors"],
    response_model=List[DonationRecord]
)
def get_my_donation_history(current_user: Annotated[dict, Depends(authenticated_user)]):
    # Fetch donation records for the current donor
    donation_records = donations_records_collection.find({
        "donor_id": current_user["id"],
        "status": "Completed"
    }).sort("donation_date", -1)

    history = []
    for record in donation_records:
        history.append({
            "id": str(record["_id"]),
            "donation_date": record["donation_date"],
            "location": record["hospital_name"],
            "recipient_info": record.get("recipient_info", "N/A"),
            "status": record["status"]
        })
    return history
