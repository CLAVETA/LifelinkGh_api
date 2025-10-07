from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

# connect to mongo atlas cluster
mongo_client = MongoClient(os.getenv("MONGO_URI"))


# Access database
LifelinkGh_db = mongo_client["LifelinkGh_db"]

# Pick a connection to operate on
users_collection = LifelinkGh_db["users"]

volunteer_signups_collection = LifelinkGh_db["volunteer_signups"]

hospital_requests_collection = LifelinkGh_db["hospital_requests"]

donation_responses_collection = LifelinkGh_db["donation_responses"]

donations_records_collection = LifelinkGh_db["donation_records"]

campaigns_collection = LifelinkGh_db["campaigns"]