# In routers/auth.py

from enum import Enum
from fastapi import APIRouter, Form, HTTPException, status
from typing import Annotated
from pydantic import EmailStr
from db import users_collection  
import bcrypt
import jwt
import os
from datetime import datetime, timezone, timedelta

class UserRole(str, Enum):
    DONOR = "donor"
    HOSPITAL = "hospital"
    VOLUNTEER = "volunteer"
    ADMIN = "admin"

users_router = APIRouter()

def create_user_in_db(user_data: dict):
    email = user_data.get("email")
    password = user_data.get("password")

    # Check if a user with the given email already exists
    if users_collection.count_documents({"email": email}) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists."
        )

    # Hash the user's password securely using bcrypt
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    user_data["password"] = hashed_password

    # Add creation timestamp
    user_data["created_at"] = datetime.now(timezone.utc)
    
    # Save the new user into the database
    users_collection.insert_one(user_data)

    return create_user_in_db


# User Login Endpoint 
@users_router.post("/users/login", tags=["Users"])
def login_user(
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
):
    # Find the user in the database by their email
    user_in_db = users_collection.find_one({"email": email})

    # Check if the user exists
    if not user_in_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incorrect email or password.",
        )

    # Verify the provided password against the stored hash
    if not bcrypt.checkpw(password.encode("utf-8"), user_in_db["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    #  Prepare the JWT Payload
    payload = {
        "user_id": str(user_in_db["_id"]),
        "role": user_in_db["role"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60) 
    }

    # Encode the JWT
    encoded_jwt = jwt.encode(
        payload,
        os.getenv("JWT_SECRET_KEY"),
        algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    )

    return {
        "message": "User logged in successfully!",
        "access_token": encoded_jwt
    }
