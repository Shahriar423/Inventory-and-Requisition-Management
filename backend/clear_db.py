import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# আপনার MongoDB URI (যদি Atlas হয় তবে Atlas URI দিন, লোকাল হলে এটাই থাকবে)
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "it_requisition_db"  # আপনার ব্যাকএন্ডের আসল DB Name (server.py এর সাথে মিলিয়ে নিন)

async def clear_database():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    # যে যে কালেকশনের ডামি ডেটা মুছতে চান
    collections_to_clear = [
        "requisitions",
        "handovers",
        "Requisition History",
        "Stock List",
        "Approve Requisition",
        "assets",
        "grns",
        "histories",
        "File Purchase Requisition",
        "notifications"
    ]
    
    print("🧹 Cleaning dummy data from database...")
    for collection in collections_to_clear:
        result = await db[collection].delete_many({})
        print(f"✅ Cleared {result.deleted_count} documents from '{collection}'")
        
    print("\n🎉 Database successfully cleaned! (User accounts remain intact).")

if __name__ == "__main__":
    asyncio.run(clear_database())