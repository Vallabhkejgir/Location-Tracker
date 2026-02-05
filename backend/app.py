from pathlib import Path
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Cookie, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
import os
import requests
import time
import uuid
from twilio.rest import Client

load_dotenv()

# Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER", "")

# Session Constants (in seconds)
DEFAULT_TIMEOUT = 300      # 5 minutes
SPECIAL_TIMEOUT = 7200     # 2 hours for "jollypolly"

# In-memory session store: {session_id: {"username": str, "expires_at": float}}
sessions = {}

if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
else:
    twilio_client = None

destination_coords: dict[str, float | None] = {"lat": None, "lng": None}
current_coords: dict[str, float | None] = {"lat": None, "lng": None}

# --- Helper Functions ---

def make_twilio_call():
    if not twilio_client: return
    try:
        twilio_client.calls.create(
            to=MY_PHONE_NUMBER,
            from_=TWILIO_PHONE_NUMBER,
            url="https://handler.twilio.com/twiml/EH717d0e56cd5b9578b06f3f7446f15a46"
        )
    except Exception as e:
        print(f"Twilio error: {e}")

def compute_distance(coord1, coord2) -> bool:
    if None in coord1.values() or None in coord2.values(): return False
    from geopy.distance import geodesic
    distance = geodesic((coord1['lat'], coord1['lng']), (coord2['lat'], coord2['lng'])).meters
    return distance <= 2000

# Dependency to check if the session is valid
def verify_session(session_id: str = Cookie(None)):
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    
    session_data = sessions[session_id]
    if time.time() > session_data["expires_at"]:
        if session_id in sessions: del sessions[session_id]
        raise HTTPException(status_code=401, detail="Session expired")
    
    return session_data["username"]

# --- Router & Endpoints ---

router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(data: LoginRequest, response: Response):
    if len(data.username) < 5:
        raise HTTPException(status_code=400, detail="Username too short")
    if data.password != data.username[::-1]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_id = str(uuid.uuid4())
    timeout = SPECIAL_TIMEOUT if data.username == "jollypolly" else DEFAULT_TIMEOUT
    expires_at = time.time() + timeout
    
    sessions[session_id] = {"username": data.username, "expires_at": expires_at}
    
    # Set session cookie
    response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax")
    return {"status": "success", "username": data.username}

# NEW: Endpoint to get remaining session time
@router.get("/session_info")
def get_session_info(session_id: str = Cookie(None)):
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401)
    
    session_data = sessions[session_id]
    remaining = session_data["expires_at"] - time.time()
    
    if remaining <= 0:
        del sessions[session_id]
        raise HTTPException(status_code=401)
        
    return {"username": session_data["username"], "remaining_seconds": remaining}

@router.post("/logout")
def logout(response: Response, session_id: str = Cookie(None)):
    if session_id in sessions:
        del sessions[session_id]
    response.delete_cookie("session_id")
    return {"status": "success"}

@router.post("/set_destination")
def set_destination(data: dict, user: str = Depends(verify_session)):
    body = {"place_id": data.get("place_id"), "key": GOOGLE_API_KEY}
    try:
        res = requests.get("https://maps.googleapis.com/maps/api/place/details/json", params=body).json()
        loc = res['result']['geometry']['location']
        destination_coords.update({"lat": loc['lat'], "lng": loc['lng']})
        return {"status": "success", "destination_coordinates": destination_coords}
    except:
        raise HTTPException(status_code=500, detail="Map error")

@router.post("/autocomplete_location")
def autocomplete_location(data: dict, user: str = Depends(verify_session)):
    body = {"input": data.get("location_name"), "components": "country:in", "key": GOOGLE_API_KEY}
    res = requests.get("https://maps.googleapis.com/maps/api/place/autocomplete/json", params=body).json()
    return res

@router.post("/track_location")
def track_location(data: dict, user: str = Depends(verify_session)):
    current_coords.update({"lat": data.get("latitude"), "lng": data.get("longitude")})
    if compute_distance(current_coords, destination_coords):
        make_twilio_call()
        return {"status": "alert", "message": "Arrived! Calling now..."}
    return {"status": "success"}

# --- App Setup ---

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")

@app.get("/")
def root():
    return RedirectResponse(url="/static/login.html")

app.include_router(router, prefix="/api")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)