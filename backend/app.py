from pathlib import Path
from fastapi import FastAPI, APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
import os
import requests
from twilio.rest import Client


load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER", "")

if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    print("Twilio client initialized successfully")
else:
    twilio_client = None
    print("Warning: Twilio credentials not found. Calls will not work.")


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
destination_coords: dict[str, float | None] = {"lat": None, "lng": None}
current_coords: dict[str, float | None] = {"lat": None, "lng": None}

# call function
def make_twilio_call():
    if not twilio_client:
        print("Error: Twilio client not configured. Check environment variables.")
        return
    
    try:
        call = twilio_client.calls.create(
            to=MY_PHONE_NUMBER,
            from_=TWILIO_PHONE_NUMBER,
            url="https://handler.twilio.com/twiml/EH717d0e56cd5b9578b06f3f7446f15a46"
        )
        print("Call SID:", call.sid)
    except Exception as e:
        print(f"Error making Twilio call: {e}")
# distance computation function

def compute_distance(coord1, coord2) -> bool:
    if None in coord1.values() or None in coord2.values():
        print("One or both coordinates are None")
        return False

    print(f"Computing distance between {coord1} and {coord2}")
    from geopy.distance import geodesic
    distance = geodesic((coord1['lat'], coord1['lng']), (coord2['lat'], coord2['lng'])).meters
    print(f"Computed distance: {distance} meters")
    if distance <= 2000:
        return True
    return False

router = APIRouter()

class LocationRequest(BaseModel):
    location_name: str

class LocationTrackingRequest(BaseModel):
    latitude: float
    longitude: float
    timestamp: str

class destinationRequest(BaseModel):
    place_id: str


@router.get("/")
def read_root():
    return {"Hello": "Jolly"}


@router.post("/set_destination")
def set_destination(data: destinationRequest):
    body = {
        "place_id": data.place_id,
        "key": GOOGLE_API_KEY,
    }

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params=body,
            verify=False
        )
        result = response.json()
        location = result['result']['geometry']['location']
        destination_coords['lat'] = location['lat']
        destination_coords['lng'] = location['lng']
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

    return JSONResponse(content={
        "status": "success",
        "destination_coordinates": destination_coords
    })


@router.post("/autocomplete_location")
def autocomplete_location(data: LocationRequest):
    body = {
        "input": data.location_name,
        "components": "country:in",
        "key": GOOGLE_API_KEY
    }
    try:
        print(body)
        response = requests.get(
            "https://maps.googleapis.com/maps/api/place/autocomplete/json",
            params=body
            # verify=False
        )
        result = response.json()
        print(f"Autocomplete result: {result}") 
    
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

    return JSONResponse(content=result)


@router.post("/track_location")
def track_location(data: LocationTrackingRequest):
    print(f"Received location: Lat {data.latitude}, Lon {data.longitude} at {data.timestamp}")
    current_coords['lat'] = data.latitude
    current_coords['lng'] = data.longitude

    if compute_distance(current_coords, destination_coords):
        make_twilio_call()
        return JSONResponse(content={
            "status": "alert",
            "message": "You have arrived within 2 km of your destination! Calling you now..."
        })


    return JSONResponse(content={
        "status": "success",
        "message": "Location received",
        "data": {
            "latitude": data.latitude,
            "longitude": data.longitude,
            "timestamp": data.timestamp
        }
    })


app = FastAPI(
    title="Location-based Notifier API",
    description="API for Location-based Notifier Application",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# app.mount("/static", StaticFiles(directory="../frontend"), name="static")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")




@app.get("/")
def redirect_to_home():
    return RedirectResponse(url="/static/home.html")


app.include_router(router, prefix="/api", tags=["Location-based Notifier"])

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8008)
    print("Server started at http://localhost:8008")


# syntax=docker/dockerfile:1
