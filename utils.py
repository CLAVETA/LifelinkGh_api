from bson.objectid import ObjectId
from google import genai
from dotenv import load_dotenv

load_dotenv()

genai_client = genai.Client()

# def replace_mongo_id(doc):
#     doc["id"] = str(doc["_id"])
#     del doc["_id"]
#     return doc



def replace_mongo_id(doc):
    
    if isinstance(doc, dict):
        # Handle the primary _id field
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        
        # check all other key-value pairs
        for key, value in doc.items():
            doc[key] = replace_mongo_id(value)
            
    elif isinstance(doc, list):
        # Recursively check items in lists 
        doc = [replace_mongo_id(item) for item in doc]
        
    elif isinstance(doc, ObjectId):
        # Direct conversion for any ObjectId found deep in the structure
        doc = str(doc)
        
    return doc
