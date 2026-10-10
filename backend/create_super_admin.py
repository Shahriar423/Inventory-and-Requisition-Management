import sys
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def init_data(email, password):
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "irm_db")
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Ensure base departments exist
    depts = ["IT", "HR", "Finance", "Operations", "Admin"]
    for d in depts:
        await db.departments.update_one(
            {"name": d},
            {"$setOnInsert": {"name": d, "code": d.upper()}},
            upsert=True
        )

    # Create or update Super Admin
    hashed = pwd_context.hash(password)
    await db.users.update_one(
        {"email": email},
        {"$set": {
            "email": email,
            "full_name": "System Super Admin",
            "role": "super_admin",
            "hashed_password": hashed,
            "is_active": True,
            "department": "IT"
        }},
        upsert=True
    )
    print("Base departments and Super Admin setup completed successfully!")
    client.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python create_super_admin.py <email> <password>")
        sys.exit(1)
    email_arg = sys.argv[1]
    pass_arg = sys.argv[2]
    asyncio.run(init_data(email_arg, pass_arg))
