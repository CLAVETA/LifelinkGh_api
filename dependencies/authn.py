import os
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from db import users_collection
from utils import replace_mongo_id
from bson.objectid import ObjectId


def is_authenticated(
    authorization: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
):
    try:
        payload = jwt.decode(
            jwt=authorization.credentials,
            key=os.getenv("JWT_SECRET_KEY"),
            algorithms=["HS256"],
        )
        print(payload)
        return payload["user_id"]
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


def authenticated_user(user_id: Annotated[str, Depends(is_authenticated)]):
    user = users_collection.find_one(filter={"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user missing from database!",
        )
    return replace_mongo_id(user)
