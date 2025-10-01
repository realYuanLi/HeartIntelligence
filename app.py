import os
import json
import uuid
import threading
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

# --------------------------------------------------------------------------------
# Attempt to import the user's Agent class (from functions/agent.py)
# If unavailable, fall back to a minimal dummy Agent so the app still runs.
# --------------------------------------------------------------------------------
try:
    import sys
    # sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from functions.agent import Agent, get_status
except Exception as e:
    class _Resp:
        def __init__(self, content: str):
            self.content = content
    class Agent:
        def __init__(self, role: str, llm: str, temperature: float, sys_message: str):
            self.role = role
            self.llm = llm
            self.temperature = temperature
            self.sys_message = sys_message
        def llm_reply(self, messages: list[dict]):
            last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            return _Resp(f"(dummy {self.llm}) You said: {last_user}")
    
    def get_status():
        return "idle"

# --------------------------------------------------------------------------------
# Paths & config
# --------------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "chat_history"
CONFIG_PATH = APP_DIR / "config" / "configs.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# Patient data is now handled through EHR data
PATIENT_DATA = None

# Load EHR test data
EHR_DATA_PATH = APP_DIR / "data" / "test_file" / "ehr_test_data.json"
try:
    if EHR_DATA_PATH.exists() and EHR_DATA_PATH.is_file():
        with open(EHR_DATA_PATH, "r", encoding="utf-8") as f:
            EHR_DATA = json.load(f)
        print(f"Loaded EHR data with {EHR_DATA.get('metadata', {}).get('summary', {}).get('total_records', 0)} records")
    else:
        EHR_DATA = None
        print("EHR data file not found")
except Exception as e:
    EHR_DATA = None
    print(f"Could not load EHR data: {e}")

# Simple system prompt
system_prompt = """You are a helpful AI assistant."""

Chatbot = Agent(
    role="AI Assistant",
    llm=CONFIG["chatbot"]["llm_model"],
    temperature=0.7,
    sys_message=system_prompt,
    ehr_data=EHR_DATA
)

SummaryBot = Agent(
    role="Summary assistant",
    llm="gpt-4o",
    temperature=0.1,
    sys_message="You are a summarizer. You must create a 3-5 word title that summarizes the main topic of the conversation. Be specific and concise. Return ONLY the title words, no explanations, no prefixes, no quotes."
)

# --------------------------------------------------------------------------------
# Flask setup
# --------------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "replace-with-your-secret-key")

# ---- "account name": password  ----
USERS = {"Kevin": "123456", "Yuan": "3456", "test": "111"}

def _username() -> str | None:
    return session.get("username")

def _require_login() -> bool:
    u = session.get("username")
    if not u or u not in USERS:
        return False
    return True

def _user_dir(user: str) -> Path:
    d = DATA_DIR / user
    d.mkdir(parents=True, exist_ok=True)
    return d

def _session_path(user: str, session_id: str) -> Path:
    return _user_dir(user) / f"{session_id}.json"

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _load_session(user: str, session_id: str) -> dict:
    p = _session_path(user, session_id)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_session(user: str, payload: dict):
    p = _session_path(user, payload["session_id"])
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def _generate_summary_async(user: str, session_id: str, conversation: list):
    def generate_summary():
        try:
            print(f"Starting summary generation for session {session_id}")
            user_messages = [msg for msg in conversation if msg.get("role") == "user"]
            assistant_messages = [msg for msg in conversation if msg.get("role") == "assistant"]
            
            print(f"Found {len(user_messages)} user messages, {len(assistant_messages)} assistant messages")
            
            if len(user_messages) >= 1 and len(assistant_messages) >= 2:
                user_msg = user_messages[0]['content'][:100]  # Limit length
                assistant_msg = assistant_messages[1]['content'][:200]  # Limit length
                summary_prompt = f"Create a 2-5 word title for this chat:\nUser: {user_msg}\nAssistant: {assistant_msg}\n\nTitle:"
                messages = [{"role": "user", "content": summary_prompt}]
                
                print(f"Calling SummaryBot with prompt: {summary_prompt[:100]}...")
                resp = SummaryBot.llm_reply(messages)
                print(f"SummaryBot response: {resp}")
                
                if resp and hasattr(resp, "content"):
                    summary = resp.content.strip()
                    
                    # Clean up the summary - remove any prefixes or extra text
                    summary = summary.replace("Title:", "").strip()
                    summary = summary.replace('"', '').replace("'", "").strip()
                    
                    # If it still contains the user's message, create a fallback
                    if "User:" in summary or len(summary) > 50:
                        summary = "General chat"
                    
                    # Ensure it's not too long
                    words = summary.split()
                    if len(words) > 5:
                        summary = " ".join(words[:5])
                    if len(words) < 2:
                        summary = "Chat session"
                    
                    print(f"Generated summary: {summary}")
                    
                    d = _load_session(user, session_id)
                    if d:
                        d["title"] = summary
                        d["updated_at"] = _now_iso()
                        _save_session(user, d)
                        print(f"Updated session title to: {summary}")
                else:
                    print("No valid response from SummaryBot")
            else:
                print("Not enough messages for summary generation")
        except Exception as e:
            print(f"Summary generation failed: {e}")
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=generate_summary)
    thread.daemon = True
    thread.start()

# --------------------------------------------------------------------------------
# Routes (pages)
# --------------------------------------------------------------------------------
@app.route("/")
def index():
    # Show welcome page for logged in users, login page for others
    if not _require_login():
        return render_template("base.html")
    
    # For logged in users, show welcome page
    return render_template("welcome.html", username=session.get("username"))

@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "ehr_data_available": EHR_DATA is not None,
        "ehr_records": EHR_DATA.get('metadata', {}).get('summary', {}).get('total_records', 0) if EHR_DATA else 0
    })

@app.route("/api/status")
def api_status():
    """Get current backend processing status"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    status = get_status()
    
    # Map backend status to frontend labels
    status_labels = {
        "idle": "Processing...",
        "processing": "Processing...",
        "searching_web": "Searching the web",
        "retrieving_health_data": "Retrieving health data",
        "analyzing_health_data": "Analyzing health data",
        "analyzing_web_data": "Analyzing web data",
        "summarizing_health_data": "Summarizing health data"
    }
    
    label = status_labels.get(status, "Processing...")
    
    return jsonify(success=True, status=status, label=label)

@app.route("/new")
def new_chat():
    # Show welcome page for new chat
    if not _require_login():
        return redirect(url_for("index"))
    
    # For logged in users, show welcome page
    return render_template("welcome.html", username=session.get("username"))

@app.route("/dashboard")
def dashboard():
    # Show dashboard page
    if not _require_login():
        return redirect(url_for("index"))
    
    # For logged in users, show dashboard page
    return render_template("dashboard.html", username=session.get("username"))

@app.route("/chat/<session_id>")
def chat(session_id: str):
    return render_template("chat.html", username=session.get("username"))

# --------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    u = (data.get("username") or "").strip()
    p = (data.get("password") or "").strip()

    if u not in USERS:
        return jsonify(success=False, message="User not found."), 401
    if USERS[u] != p:
        return jsonify(success=False, message="Incorrect password."), 401

    session["username"] = u
    return jsonify(success=True, username=u)

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("username", None)
    return jsonify(success=True)

# --------------------------------------------------------------------------------
# Conversations (login required)
# --------------------------------------------------------------------------------
@app.route("/api/history")
def api_history():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    items = []
    for fn in sorted(_user_dir(user).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with fn.open("r", encoding="utf-8") as f:
                d = json.load(f)
            sid = d.get("session_id", fn.stem)

            title = d.get("title") or f"Chat {sid[:6]}"
            items.append({
                "session_id": sid,
                "title": title,
                "updated_at": d.get("updated_at") or datetime.fromtimestamp(fn.stat().st_mtime).isoformat(timespec="seconds")
            })
        except Exception:
            continue
    return jsonify(items)

@app.route("/api/new_session", methods=["POST"])
def api_new_session():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    session_id = uuid.uuid4().hex[:12]
    payload = {
        "session_id": session_id,
        "title": f"Chat {session_id[:6]}",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "conversation": [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": CONFIG["chatbot"]["prologue"]}
        ]
    }
    _save_session(user, payload)
    return jsonify(success=True, session_id=session_id)

@app.route("/api/session/<session_id>")
def api_get_session(session_id: str):
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    d = _load_session(user, session_id)
    if not d:
        return jsonify(success=False, message="Session not found"), 404
    # Hide system messages; chat starts from the assistant greeting
    # Also filter out old messages with PATIENT INFORMATION and USER QUESTION labels
    convo = []
    for m in d.get("conversation", []):
        if m.get("role") in {"user", "assistant", "assistant-error"} and m.get("content"):
            content = m.get("content", "")
            # Skip messages that contain the old label format
            if "PATIENT INFORMATION:" in content and "USER QUESTION:" in content:
                # Extract just the user question part
                if m.get("role") == "user":
                    user_question = content.split("USER QUESTION: ", 1)
                    if len(user_question) > 1:
                        convo.append({"role": m.get("role"), "content": user_question[1]})
                # Skip assistant messages that were responses to the old format
                continue
            else:
                convo.append({"role": m.get("role"), "content": content})
    return jsonify(success=True, conversation=convo)

@app.route("/api/message", methods=["POST"])
def api_message():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify(success=False, assistant_message="Please type a message."), 400

    d = _load_session(user, session_id)
    if not d:
        return jsonify(success=False, assistant_message="Session not found."), 404

    # Store user's original message
    d["conversation"].append({"role": "user", "content": text})
    
    # Prepare messages for AI processing
    messages = d["conversation"].copy()
    
    # If patient data exists, modify the system message to include it
    if PATIENT_DATA:
        # Find the system message and update it with patient data
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                original_system = msg["content"]
                patient_info = f"\n\nPatient Information:\n{json.dumps(PATIENT_DATA, indent=2)}"
                messages[i] = {"role": "system", "content": original_system + patient_info}
                break

    try:
        resp = Chatbot.llm_reply(messages)
        assistant_text = resp.content if hasattr(resp, "content") else str(resp)
        d["conversation"].append({"role": "assistant", "content": assistant_text})
        d["updated_at"] = _now_iso()
        _save_session(user, d)
        
        user_messages = [msg for msg in d["conversation"] if msg.get("role") == "user"]
        assistant_messages = [msg for msg in d["conversation"] if msg.get("role") == "assistant"]
        
        print(f"Message count - Users: {len(user_messages)}, Assistants: {len(assistant_messages)}")
        print(f"Total conversation length: {len(d['conversation'])}")
        
        if len(user_messages) == 1 and len(assistant_messages) == 2:
            print("Triggering summary generation...")
            _generate_summary_async(user, session_id, d["conversation"])
        
        return jsonify(success=True, assistant_message=assistant_text)
    except Exception as e:
        err = f"Error from model: {e}"
        d["conversation"].append({"role": "assistant-error", "content": err})
        d["updated_at"] = _now_iso()
        _save_session(user, d)
        return jsonify(success=False, assistant_message=err), 500

@app.route("/api/rename_session", methods=["POST"])
def api_rename_session():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    new_title = (data.get("new_title") or "").strip()
    if not new_title:
        return jsonify(success=False, message="Title cannot be empty.")

    d = _load_session(user, session_id)
    if not d:
        return jsonify(success=False, message="Session not found"), 404
    d["title"] = new_title
    d["updated_at"] = _now_iso()
    _save_session(user, d)
    return jsonify(success=True)

@app.route("/api/delete_session", methods=["POST"])
def api_delete_session():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401

    user = _username()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    p = _session_path(user, session_id)
    if p.exists():
        p.unlink()
        return jsonify(success=True)
    return jsonify(success=False, message="Session not found"), 404

@app.route("/api/patient_info")
def api_patient_info():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    if PATIENT_DATA:
        return jsonify(success=True, patient_data=PATIENT_DATA)
    else:
        return jsonify(success=False, message="No patient data available"), 404

@app.route("/api/dashboard_data")
def api_dashboard_data():
    """Get dashboard health data"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    if not EHR_DATA:
        return jsonify(success=False, message="No health data available"), 404
    
    # Extract relevant health information
    dashboard_data = {
        "demographics": {},
        "vital_signs": [],
        "medications": [],
        "activity": {},
        "lab_results": [],
        "clinical": {},
        "cardiovascular": {},
        "mobility": {}
    }
    
    # Get demographics
    if "demographics" in EHR_DATA:
        demographics_records = EHR_DATA["demographics"]
        if "Demographics" in demographics_records and len(demographics_records["Demographics"]) > 0:
            demo = demographics_records["Demographics"][0]
            dashboard_data["demographics"] = {
                "name": demo.get("DisplayName", "N/A"),
                "birth_date": demo.get("BirthDate", "N/A"),
                "sex": demo.get("BiologicalSex", "N/A"),
                "age": demo.get("Age", "N/A")
            }
    
    # Get vital signs with normal ranges
    if "vital_signs" in EHR_DATA:
        vital_signs_records = EHR_DATA["vital_signs"]
        vital_types = {}
        
        # Collect the most recent vital sign of each type
        for vital_type in ["ClinicalHeartRate", "ClinicalBloodPressure", "ClinicalBodyTemperature", 
                          "ClinicalRespiratoryRate", "ClinicalOxygenSaturation"]:
            if vital_type in vital_signs_records and len(vital_signs_records[vital_type]) > 0:
                vital = vital_signs_records[vital_type][0]  # Most recent
                vital_types[vital_type] = vital
        
        # Format vital signs with normal ranges
        normal_ranges = {
            "ClinicalHeartRate": {"min": 60, "max": 100, "unit": "bpm"},
            "ClinicalBloodPressure": {"systolic": {"min": 90, "max": 120}, "diastolic": {"min": 60, "max": 80}, "unit": "mmHg"},
            "ClinicalBodyTemperature": {"min": 97.0, "max": 99.0, "unit": "°F"},
            "ClinicalRespiratoryRate": {"min": 12, "max": 20, "unit": "breaths/min"},
            "ClinicalOxygenSaturation": {"min": 95, "max": 100, "unit": "%"}
        }
        
        for vital_type, vital in vital_types.items():
            display_name = vital.get("DisplayName", vital_type.replace("Clinical", ""))
            value = vital.get("Value")
            unit = vital.get("Unit", "")
            date = vital.get("Date", "")
            
            vital_info = {
                "name": display_name,
                "value": value,
                "unit": unit,
                "date": date,
                "normal_range": normal_ranges.get(vital_type, {})
            }
            
            dashboard_data["vital_signs"].append(vital_info)
    
    # Get medications (recent 5)
    if "medications" in EHR_DATA:
        medications_records = EHR_DATA["medications"]
        if "ClinicalMedication" in medications_records:
            meds = medications_records["ClinicalMedication"][:5]
            for med in meds:
                dashboard_data["medications"].append({
                    "name": med.get("DisplayName", "N/A"),
                    "date": med.get("Date", "N/A")
                })
    
    # Get activity data (most recent)
    if "activity" in EHR_DATA:
        activity_records = EHR_DATA["activity"]
        
        # Steps
        if "StepCount" in activity_records and len(activity_records["StepCount"]) > 0:
            steps = activity_records["StepCount"][0]
            dashboard_data["activity"]["steps"] = {
                "value": steps.get("Value", "N/A"),
                "unit": steps.get("Unit", "steps"),
                "date": steps.get("Date", "N/A")
            }
        
        # Active Energy
        if "ActiveEnergyBurned" in activity_records and len(activity_records["ActiveEnergyBurned"]) > 0:
            energy = activity_records["ActiveEnergyBurned"][0]
            dashboard_data["activity"]["active_energy"] = {
                "value": energy.get("Value", "N/A"),
                "unit": energy.get("Unit", "Cal"),
                "date": energy.get("Date", "N/A")
            }
        
        # Exercise Time
        if "AppleExerciseTime" in activity_records and len(activity_records["AppleExerciseTime"]) > 0:
            exercise = activity_records["AppleExerciseTime"][0]
            dashboard_data["activity"]["exercise_time"] = {
                "value": exercise.get("Value", "N/A"),
                "unit": exercise.get("Unit", "min"),
                "date": exercise.get("Date", "N/A")
            }
    
    # Get lab results (recent 5)
    if "lab_results" in EHR_DATA:
        lab_records = EHR_DATA["lab_results"]
        if "ClinicalLabResult" in lab_records:
            labs = lab_records["ClinicalLabResult"][:5]
            for lab in labs:
                dashboard_data["lab_results"].append({
                    "name": lab.get("DisplayName", "N/A"),
                    "value": lab.get("Value", "N/A"),
                    "unit": lab.get("Unit", ""),
                    "date": lab.get("Date", "N/A"),
                    "status": lab.get("Status", "")
                })
    
    # Get clinical data
    if "clinical" in EHR_DATA:
        clinical_records = EHR_DATA["clinical"]
        
        # Allergies
        if "ClinicalAllergy" in clinical_records:
            allergies = clinical_records["ClinicalAllergy"][:5]
            dashboard_data["clinical"]["allergies"] = [
                {"name": a.get("DisplayName", "N/A"), "date": a.get("Date", "N/A")}
                for a in allergies
            ]
        
        # Conditions
        if "ClinicalCondition" in clinical_records:
            conditions = clinical_records["ClinicalCondition"][:5]
            dashboard_data["clinical"]["conditions"] = [
                {"name": c.get("DisplayName", "N/A"), "date": c.get("Date", "N/A")}
                for c in conditions
            ]
    
    # Get cardiovascular data
    if "cardiovascular" in EHR_DATA:
        cardio_records = EHR_DATA["cardiovascular"]
        
        # Resting Heart Rate
        if "RestingHeartRate" in cardio_records and len(cardio_records["RestingHeartRate"]) > 0:
            rhr = cardio_records["RestingHeartRate"][0]
            dashboard_data["cardiovascular"]["resting_hr"] = {
                "value": rhr.get("Value", "N/A"),
                "unit": rhr.get("Unit", "bpm"),
                "date": rhr.get("Date", "N/A")
            }
        
        # HRV
        if "HeartRateVariabilitySDNN" in cardio_records and len(cardio_records["HeartRateVariabilitySDNN"]) > 0:
            hrv = cardio_records["HeartRateVariabilitySDNN"][0]
            dashboard_data["cardiovascular"]["hrv"] = {
                "value": hrv.get("Value", "N/A"),
                "unit": hrv.get("Unit", "ms"),
                "date": hrv.get("Date", "N/A")
            }
    
    # Get mobility data
    if "mobility" in EHR_DATA:
        mobility_records = EHR_DATA["mobility"]
        
        # Walking Speed
        if "WalkingSpeed" in mobility_records and len(mobility_records["WalkingSpeed"]) > 0:
            speed = mobility_records["WalkingSpeed"][0]
            dashboard_data["mobility"]["walking_speed"] = {
                "value": speed.get("Value", "N/A"),
                "unit": speed.get("Unit", "mph"),
                "date": speed.get("Date", "N/A")
            }
        
        # Walking Step Length
        if "WalkingStepLength" in mobility_records and len(mobility_records["WalkingStepLength"]) > 0:
            step_length = mobility_records["WalkingStepLength"][0]
            dashboard_data["mobility"]["step_length"] = {
                "value": step_length.get("Value", "N/A"),
                "unit": step_length.get("Unit", "in"),
                "date": step_length.get("Date", "N/A")
            }
    
    return jsonify(success=True, data=dashboard_data)

# --------------------------------------------------------------------------------
# Speech-to-Text endpoints
# --------------------------------------------------------------------------------
# Global transcriber instance (per user session)
transcriber_instances = {}

@app.route("/api/speech/start", methods=["POST"])
def api_speech_start():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    user = _username()
    
    try:
        # Import here to avoid errors if module is not installed
        from functions.speech_to_text import SpeechToText
        
        # Stop existing transcriber if any
        if user in transcriber_instances:
            try:
                transcriber_instances[user].stop()
            except:
                pass
        
        # Create new transcriber
        transcriber = SpeechToText(model='base.en')
        transcriber.start()
        transcriber_instances[user] = transcriber
        
        return jsonify(success=True, message="Recording started")
    except ImportError:
        return jsonify(success=False, message="Speech-to-text module not installed"), 500
    except Exception as e:
        return jsonify(success=False, message=f"Failed to start recording: {str(e)}"), 500

@app.route("/api/speech/stop", methods=["POST"])
def api_speech_stop():
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    user = _username()
    
    if user not in transcriber_instances:
        return jsonify(success=False, message="No active recording"), 400
    
    try:
        transcriber = transcriber_instances[user]
        
        # Get all transcribed text
        transcriber.process_pending_audio()
        time.sleep(0.5)  # Wait for any final audio processing
        transcriber.process_pending_audio()
        
        history = transcriber.get_transcription_history()
        
        # Combine all transcriptions
        all_text = " ".join([entry["text"] for entry in history])
        
        # Stop and cleanup
        transcriber.stop()
        del transcriber_instances[user]
        
        return jsonify(success=True, transcribed_text=all_text)
    except Exception as e:
        return jsonify(success=False, message=f"Failed to stop recording: {str(e)}"), 500

@app.route("/api/speech/poll", methods=["GET"])
def api_speech_poll():
    """Poll for new transcribed text while recording"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    user = _username()
    
    if user not in transcriber_instances:
        return jsonify(success=False, is_recording=False, text="")
    
    try:
        transcriber = transcriber_instances[user]
        transcriber.process_pending_audio()
        
        # Get latest text from history
        history = transcriber.get_transcription_history()
        latest_text = " ".join([entry["text"] for entry in history])
        
        return jsonify(success=True, is_recording=True, text=latest_text)
    except Exception as e:
        return jsonify(success=False, message=f"Polling failed: {str(e)}"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
