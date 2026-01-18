import os
import json
import uuid
import threading
import time
import base64
import io
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_file, Response
import numpy as np
import nibabel as nib
from PIL import Image

try:
    import sys
    # sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from functions.agent import Agent, get_status
    from functions.auto_form_fill import init_pdf_forms
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
    
    def init_pdf_forms(*args, **kwargs):
        pass

# --------------------------------------------------------------------------------
# Paths & config
# --------------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "chat_history"
CONFIG_PATH = APP_DIR / "config" / "configs.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# Patient data is now handled through patient.json
PATIENT_DATA = None

# Load patient profile data
PATIENT_DATA_PATH = APP_DIR / "data" / "test_file" / "patient.json"

try:
    if PATIENT_DATA_PATH.exists() and PATIENT_DATA_PATH.is_file():
        print(f"Loading patient data from {PATIENT_DATA_PATH}...")
        with open(PATIENT_DATA_PATH, "r", encoding="utf-8") as f:
            PATIENT_DATA = json.load(f)
        print(f"Loaded patient profile: {PATIENT_DATA.get('patient_profile', {}).get('demographics', {}).get('name', 'Unknown')}")
    else:
        PATIENT_DATA = None
        print("Patient data file not found - health data features will be limited")
except Exception as e:
    PATIENT_DATA = None
    print(f"Could not load patient data: {e}")

# Load my body data
MY_BODY_DATA_PATH = APP_DIR / "data" / "my_body"
MY_BODY_STATS_PATH = MY_BODY_DATA_PATH / "statistics.json"
MY_BODY_CT_PATH = MY_BODY_DATA_PATH / "CT.nii.gz"
MY_BODY_SEG_PATH = MY_BODY_DATA_PATH / "seg_map_clean" / "s1038_seg.nii.gz"
ORGAN_STATS = {}

# Load organ statistics
try:
    if MY_BODY_STATS_PATH.exists():
        with open(MY_BODY_STATS_PATH, "r", encoding="utf-8") as f:
            ORGAN_STATS = json.load(f)
        print(f"Loaded organ statistics with {len(ORGAN_STATS)} organs")
    else:
        ORGAN_STATS = {}
        print("Organ statistics file not found")
except Exception as e:
    ORGAN_STATS = {}
    print(f"Could not load organ statistics: {e}")

# Load health information
HEALTH_INFO_PATH = APP_DIR / "data" / "health_info.json"
HEALTH_INFO = {}
try:
    if HEALTH_INFO_PATH.exists():
        with open(HEALTH_INFO_PATH, "r", encoding="utf-8") as f:
            HEALTH_INFO = json.load(f)
        print(f"Loaded health information for {len(HEALTH_INFO)} organs")
    else:
        HEALTH_INFO = {}
        print("Health information file not found")
except Exception as e:
    HEALTH_INFO = {}
    print(f"Could not load health information: {e}")

# Load mobile health data
MOBILE_HEALTH_DATA_PATH = APP_DIR / "data" / "processed_mobile_data.json"
MOBILE_HEALTH_DATA = {}
try:
    if MOBILE_HEALTH_DATA_PATH.exists():
        with open(MOBILE_HEALTH_DATA_PATH, "r", encoding="utf-8") as f:
            MOBILE_HEALTH_DATA = json.load(f)
        date_range = MOBILE_HEALTH_DATA.get('date_range', {})
        print(f"Loaded mobile health data: {date_range.get('start', 'N/A')} to {date_range.get('end', 'N/A')}")
    else:
        MOBILE_HEALTH_DATA = {}
        print("Mobile health data file not found - run process_mobile_data.py to generate it")
except Exception as e:
    MOBILE_HEALTH_DATA = {}
    print(f"Could not load mobile health data: {e}")

# Cache for medical imaging data
_CT_DATA = None
_SEG_DATA = None

# Cache for processed slices to avoid reprocessing
_slice_cache = {}
_cache_max_size = 100  # Maximum number of cached slices

# Simple system prompt
system_prompt = """You are a helpful AI assistant."""

# Verify OpenAI API key is configured
if not os.getenv("OPENAI_API_KEY"):
    print("⚠ WARNING: OPENAI_API_KEY environment variable is not set!")
    print("   The chatbot will not function without an OpenAI API key.")
    print("   Please set OPENAI_API_KEY in your environment variables.")
else:
    print("✓ OpenAI API key is configured")

try:
    Chatbot = Agent(
        role="AI Assistant",
        llm=CONFIG["chatbot"]["llm_model"],
        temperature=0.7,
        sys_message=system_prompt,
        ehr_data=PATIENT_DATA,
        mobile_data=MOBILE_HEALTH_DATA
    )
    print(f"✓ Chatbot initialized with model: {CONFIG['chatbot']['llm_model']}")
except Exception as e:
    print(f"⚠ Error initializing Chatbot: {e}")
    # Create a fallback dummy chatbot
    class DummyAgent:
        def llm_reply(self, messages):
            class Response:
                content = "The AI service is currently unavailable. Please check the server configuration."
            return Response()
    Chatbot = DummyAgent()
    print("⚠ Using fallback dummy chatbot")

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
        "patient_data_available": PATIENT_DATA is not None,
        "patient_name": PATIENT_DATA.get('patient_profile', {}).get('demographics', {}).get('name', 'N/A') if PATIENT_DATA else 'N/A'
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

@app.route("/my-body")
def my_body():
    # Show my body page
    if not _require_login():
        return redirect(url_for("index"))
    
    # For logged in users, show my body page
    return render_template("my_body.html", username=session.get("username"))

@app.route("/pdf-forms")
def pdf_forms():
    # Show PDF forms page
    if not _require_login():
        return redirect(url_for("index"))
    
    # For logged in users, show PDF forms page
    return render_template("pdf_forms.html", username=session.get("username"))

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
    """Get dashboard health data from patient profile"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    if not PATIENT_DATA:
        return jsonify(success=False, message="No patient data available"), 404
    
    try:
        # Extract patient profile data
        analytics = {
            "summary": _extract_patient_summary(),
            "demographics": _extract_demographics(),
            "diagnosis": _extract_diagnosis(),
            "medications": _extract_medications(),
            "symptoms": _extract_symptoms(),
            "comorbidities": _extract_comorbidities(),
            "wearable_data": _extract_wearable_data(),
            "recent_care": _extract_recent_care()
        }
        
        return jsonify(success=True, data=analytics)
    except Exception as e:
        print(f"Error generating dashboard data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify(success=False, message=f"Error processing data: {str(e)}"), 500

@app.route("/api/mobile_health_data")
def api_mobile_health_data():
    """Get mobile health data for dashboard visualization"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    if not MOBILE_HEALTH_DATA:
        return jsonify(success=False, message="No mobile health data available"), 404
    
    try:
        # Extract key metrics for dashboard
        heart_data = MOBILE_HEALTH_DATA.get('heart_data', {})
        
        # Heart rate summary
        heart_rate_info = heart_data.get('heart_rate', {})
        hr_stats = heart_rate_info.get('daily_stats', [])
        hr_trends = heart_rate_info.get('trends', {})
        
        # Blood pressure summary
        bp_info = heart_data.get('blood_pressure', {})
        bp_readings = bp_info.get('readings', [])
        bp_trends = bp_info.get('trends', {})
        
        # HRV summary
        hrv_info = heart_data.get('hrv', {})
        hrv_averages = hrv_info.get('daily_averages', [])
        hrv_trends = hrv_info.get('trends', {})
        
        # Activity summary
        activity_data = MOBILE_HEALTH_DATA.get('activity_data', {})
        steps_data = activity_data.get('daily_steps', [])
        
        dashboard_summary = {
            'date_range': MOBILE_HEALTH_DATA.get('date_range', {}),
            'heart_rate': {
                'daily_stats': hr_stats[-14:] if len(hr_stats) > 14 else hr_stats,  # Last 2 weeks
                'trends': hr_trends,
                'has_data': len(hr_stats) > 0
            },
            'blood_pressure': {
                'readings': bp_readings[:14],  # Most recent 14 readings
                'trends': bp_trends,
                'has_data': len(bp_readings) > 0
            },
            'hrv': {
                'daily_averages': hrv_averages[-14:] if len(hrv_averages) > 14 else hrv_averages,  # Last 2 weeks
                'trends': hrv_trends,
                'has_data': len(hrv_averages) > 0
            },
            'activity': {
                'daily_steps': steps_data[-14:] if len(steps_data) > 14 else steps_data,  # Last 2 weeks
                'has_data': len(steps_data) > 0
            }
        }
        
        return jsonify(success=True, data=dashboard_summary)
    except Exception as e:
        print(f"Error generating mobile health data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify(success=False, message=f"Error processing data: {str(e)}"), 500

# --------------------------------------------------------------------------------
# Patient Profile Helper Functions
# --------------------------------------------------------------------------------

def _extract_patient_summary():
    """Extract patient summary information"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    profile = PATIENT_DATA['patient_profile']
    return {
        "ui_summary": profile.get('ui_summary_sentence', ''),
        "name": profile.get('demographics', {}).get('name', 'N/A'),
        "age": profile.get('demographics', {}).get('age', 'N/A'),
        "sex": profile.get('demographics', {}).get('sex', 'N/A')
    }

def _extract_demographics():
    """Extract patient demographics"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    demographics = PATIENT_DATA['patient_profile'].get('demographics', {})
    return {
        "age": demographics.get('age', 'N/A'),
        "sex": demographics.get('sex', 'N/A'),
        "name": demographics.get('name', 'N/A'),
        "living_situation": demographics.get('living_situation', 'N/A'),
        "baseline_functional_status": demographics.get('baseline_functional_status', 'N/A')
    }

def _extract_diagnosis():
    """Extract primary cardiac diagnosis information"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    diagnosis = PATIENT_DATA['patient_profile'].get('primary_cardiac_diagnosis', {})
    return {
        "condition": diagnosis.get('condition', 'N/A'),
        "echocardiogram": diagnosis.get('echocardiogram', {})
    }

def _extract_medications():
    """Extract medications list"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    meds_data = PATIENT_DATA['patient_profile'].get('medications', {})
    
    medications = {
        "cardiovascular_hf": meds_data.get('cardiovascular_hf', []),
        "metabolic": meds_data.get('metabolic', []),
        "other": meds_data.get('other', []),
        "supplements": meds_data.get('supplements', [])
    }
    
    return medications

def _extract_symptoms():
    """Extract symptoms information"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    symptoms = PATIENT_DATA['patient_profile'].get('symptoms', {})
    return {
        "chronic_baseline": symptoms.get('chronic_baseline', []),
        "intermittent_recent": symptoms.get('intermittent_recent', []),
        "negative_findings": symptoms.get('negative_findings', [])
    }

def _extract_comorbidities():
    """Extract comorbidities information"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    comorbidities = PATIENT_DATA['patient_profile'].get('comorbidities', {})
    return {
        "cardiovascular": comorbidities.get('cardiovascular', []),
        "metabolic_systemic": comorbidities.get('metabolic_systemic', []),
        "respiratory_sleep": comorbidities.get('respiratory_sleep', []),
        "other": comorbidities.get('other', [])
    }

def _extract_wearable_data():
    """Extract wearable data summary"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    wearable = PATIENT_DATA['patient_profile'].get('wearable_data_summary', {})
    return {
        "ecg": wearable.get('ecg', []),
        "activity": wearable.get('activity', ''),
        "sleep": wearable.get('sleep', '')
    }

def _extract_recent_care():
    """Extract recent healthcare utilization information"""
    if not PATIENT_DATA or 'patient_profile' not in PATIENT_DATA:
        return {}
    
    recent_care = PATIENT_DATA['patient_profile'].get('recent_healthcare_utilization', {})
    return {
        "last_hospitalization": recent_care.get('last_hospitalization', {}),
        "last_cardiology_clinic_visit": recent_care.get('last_cardiology_clinic_visit', {})
    }

def _get_user_ehr_data(user):
    """Get patient data for a user (currently global PATIENT_DATA)"""
    return PATIENT_DATA

def _get_demographics():
    """Get patient demographics (compatibility function)"""
    return _extract_demographics()

def _analyze_cardiovascular():
    """Get cardiovascular data (compatibility function)"""
    return _extract_diagnosis()

def _analyze_clinical():
    """Get clinical data (compatibility function)"""
    return {
        "medications": _extract_medications(),
        "comorbidities": _extract_comorbidities(),
        "symptoms": _extract_symptoms()
    }

# --------------------------------------------------------------------------------
# Initialize PDF Form Filling Blueprint
# --------------------------------------------------------------------------------
init_pdf_forms(app, _require_login, _username, Chatbot, _get_user_ehr_data, 
               _analyze_cardiovascular, _analyze_clinical, _get_demographics)

# --------------------------------------------------------------------------------
# Speech-to-Text endpoints
# --------------------------------------------------------------------------------
# Global transcriber instance (per user session)
transcriber_instances = {}
# Track the last polled index for each user to avoid duplicate text
transcriber_last_index = {}

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
        # Reset the last polled index for this user
        transcriber_last_index[user] = 0
        
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
        # Clean up the last polled index
        if user in transcriber_last_index:
            del transcriber_last_index[user]
        
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
        
        # Get the last index we sent to the client
        last_index = transcriber_last_index.get(user, 0)
        
        # Only return new text since the last poll
        new_entries = history[last_index:]
        new_text = " ".join([entry["text"] for entry in new_entries])
        
        # Update the last index for this user
        transcriber_last_index[user] = len(history)
        
        return jsonify(success=True, is_recording=True, text=new_text)
    except Exception as e:
        return jsonify(success=False, message=f"Polling failed: {str(e)}"), 500

# --------------------------------------------------------------------------------
# Medical Imaging Viewer endpoints
# --------------------------------------------------------------------------------

def _load_ct_data():
    """Load CT data from NIfTI file"""
    global _CT_DATA
    if _CT_DATA is None and MY_BODY_CT_PATH.exists():
        try:
            ct_img = nib.load(str(MY_BODY_CT_PATH))
            _CT_DATA = {
                'data': ct_img.get_fdata(),
                'affine': ct_img.affine,
                'header': ct_img.header,
                'shape': ct_img.shape
            }
            print(f"Loaded CT data with shape {_CT_DATA['shape']}")
        except Exception as e:
            print(f"Failed to load CT data: {e}")
            _CT_DATA = None
    return _CT_DATA

def _load_seg_data():
    """Load segmentation data from NIfTI file"""
    global _SEG_DATA
    if _SEG_DATA is None and MY_BODY_SEG_PATH.exists():
        try:
            seg_img = nib.load(str(MY_BODY_SEG_PATH))
            _SEG_DATA = {
                'data': seg_img.get_fdata(),
                'affine': seg_img.affine,
                'header': seg_img.header,
                'shape': seg_img.shape
            }
            print(f"Loaded segmentation data with shape {_SEG_DATA['shape']}")
        except Exception as e:
            print(f"Failed to load segmentation data: {e}")
            _SEG_DATA = None
    return _SEG_DATA

def _normalize_slice(slice_data, window_center=0, window_width=400):
    """Normalize slice data for display with window/level and enhanced contrast"""
    if slice_data is None:
        return None
    
    # Apply window/level
    min_val = window_center - window_width // 2
    max_val = window_center + window_width // 2
    
    # Clip values
    slice_data = np.clip(slice_data, min_val, max_val)
    
    # Normalize to 0-255 with enhanced contrast
    if max_val > min_val:
        # Apply gamma correction for better contrast
        normalized = (slice_data - min_val) / (max_val - min_val)
        # Gamma correction (gamma < 1 makes images brighter, gamma > 1 makes them darker)
        gamma = 0.8  # Slightly brighter for better visibility
        normalized = np.power(normalized, gamma)
        slice_data = (normalized * 255).astype(np.uint8)
    else:
        slice_data = np.zeros_like(slice_data, dtype=np.uint8)
    
    return slice_data

def _get_cache_key(axis, slice_idx, window_center, window_width, show_segmentation, segmentation_opacity, show_ct=True):
    """Generate cache key for slice parameters"""
    return f"{axis}_{slice_idx}_{window_center}_{window_width}_{show_segmentation}_{segmentation_opacity}_{show_ct}"

def _manage_cache_size():
    """Manage cache size by removing oldest entries if needed"""
    if len(_slice_cache) > _cache_max_size:
        # Remove oldest entries (simple FIFO)
        keys_to_remove = list(_slice_cache.keys())[:len(_slice_cache) - _cache_max_size + 10]
        for key in keys_to_remove:
            del _slice_cache[key]

def _apply_colormap_to_segmentation(seg_slice, organ_colors):
    """Apply colormap to segmentation slice"""
    if seg_slice is None:
        return None
    
    # Create RGB image
    rgb_slice = np.zeros((*seg_slice.shape, 3), dtype=np.uint8)
    
    # Apply colors for each organ
    for organ_id, color in organ_colors.items():
        mask = seg_slice == organ_id
        rgb_slice[mask] = color
    
    return rgb_slice

@app.route("/api/my-body/metadata")
def api_my_body_metadata():
    """Get my body metadata"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    ct_data = _load_ct_data()
    seg_data = _load_seg_data()
    
    if ct_data is None:
        return jsonify(success=False, message="CT data not available"), 404
    
    metadata = {
        'ct_shape': ct_data['shape'],
        'seg_shape': seg_data['shape'] if seg_data else None,
        'organ_stats': ORGAN_STATS,
        'available_organs': list(ORGAN_STATS.keys()) if ORGAN_STATS else []
    }
    
    return jsonify(success=True, metadata=metadata)

@app.route("/api/my-body/slice")
def api_my_body_slice():
    """Get 2D slice data with caching for improved performance"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    # Get parameters
    axis = request.args.get('axis', 'z')  # x, y, or z
    slice_idx = int(request.args.get('slice', 0))
    window_center = int(request.args.get('window_center', 0))
    window_width = int(request.args.get('window_width', 400))
    show_segmentation = request.args.get('show_segmentation', 'true').lower() == 'true'
    segmentation_opacity = float(request.args.get('segmentation_opacity', 0.5))
    show_ct = request.args.get('show_ct', 'true').lower() == 'true'
    
    # Check cache first
    cache_key = _get_cache_key(axis, slice_idx, window_center, window_width, show_segmentation, segmentation_opacity, show_ct)
    if cache_key in _slice_cache:
        return jsonify(success=True, data=_slice_cache[cache_key])
    
    ct_data = _load_ct_data() if show_ct else None
    seg_data = _load_seg_data()
    
    # Need at least one data source
    if ct_data is None and seg_data is None:
        return jsonify(success=False, message="No data available"), 404
    
    # Use whichever data is available for shape information
    data_source = ct_data if ct_data else seg_data
    
    try:
        # Extract slice based on axis
        if axis == 'x':
            ct_slice = ct_data['data'][slice_idx, :, :] if ct_data else None
            seg_slice = seg_data['data'][slice_idx, :, :] if seg_data else None
        elif axis == 'y':
            ct_slice = ct_data['data'][:, slice_idx, :] if ct_data else None
            seg_slice = seg_data['data'][:, slice_idx, :] if seg_data else None
        else:  # z axis
            ct_slice = ct_data['data'][:, :, slice_idx] if ct_data else None
            seg_slice = seg_data['data'][:, :, slice_idx] if seg_data else None
        
        response_data = {}
        
        # Add CT image if requested and available
        if show_ct and ct_slice is not None:
            # Normalize CT slice
            ct_normalized = _normalize_slice(ct_slice, window_center, window_width)
            
            # Convert to PIL Image - use original dimensions
            ct_image = Image.fromarray(ct_normalized, mode='L')
            
            # Create base64 encoded image with optimized settings
            img_buffer = io.BytesIO()
            ct_image.save(img_buffer, format='PNG', optimize=True, compress_level=6)
            img_buffer.seek(0)
            ct_base64 = base64.b64encode(img_buffer.getvalue()).decode()
            
            response_data['ct_image'] = ct_base64
            response_data['slice_shape'] = ct_slice.shape
        elif seg_slice is not None:
            response_data['slice_shape'] = seg_slice.shape
        
        response_data['max_slices'] = data_source['shape'][{'x': 0, 'y': 1, 'z': 2}[axis]]
        
        # Add segmentation if requested and available
        if show_segmentation and seg_slice is not None:
            # Create organ colors (simplified - using hash of organ names)
            organ_colors = {}
            for i, organ in enumerate(ORGAN_STATS.keys()):
                # Generate consistent colors
                hue = (i * 137.5) % 360  # Golden angle for good distribution
                rgb = _hsv_to_rgb(hue, 0.8, 0.9)
                organ_colors[i + 1] = rgb  # Organ IDs start from 1
            
            seg_rgb = _apply_colormap_to_segmentation(seg_slice, organ_colors)
            if seg_rgb is not None:
                seg_image = Image.fromarray(seg_rgb, mode='RGB')
                
                seg_buffer = io.BytesIO()
                seg_image.save(seg_buffer, format='PNG', optimize=True, compress_level=6)
                seg_buffer.seek(0)
                seg_base64 = base64.b64encode(seg_buffer.getvalue()).decode()
                response_data['segmentation_image'] = seg_base64
                response_data['segmentation_opacity'] = segmentation_opacity
        
        # Cache the result
        _manage_cache_size()
        _slice_cache[cache_key] = response_data
        
        return jsonify(success=True, data=response_data)
        
    except Exception as e:
        return jsonify(success=False, message=f"Failed to extract slice: {str(e)}"), 500

@app.route("/api/my-body/organ-info")
def api_my_body_organ_info():
    """Get organ information for hover/tooltip"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    organ_name = request.args.get('organ')
    if not organ_name or organ_name not in ORGAN_STATS:
        return jsonify(success=False, message="Organ not found"), 404
    
    organ_data = ORGAN_STATS[organ_name]
    return jsonify(success=True, organ_data=organ_data)

@app.route("/api/my-body/click-organ")
def api_my_body_click_organ():
    """Get organ information at a specific pixel coordinate"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    try:
        # Get parameters
        axis = request.args.get('axis', 'z')
        slice_idx = int(request.args.get('slice', 0))
        x = int(request.args.get('x', 0))
        y = int(request.args.get('y', 0))
        
        seg_data = _load_seg_data()
        if seg_data is None:
            return jsonify(success=False, message="Segmentation data not available"), 404
        
        # Extract the segmentation slice
        if axis == 'x':
            seg_slice = seg_data['data'][slice_idx, :, :]
        elif axis == 'y':
            seg_slice = seg_data['data'][:, slice_idx, :]
        else:  # z axis
            seg_slice = seg_data['data'][:, :, slice_idx]
        
        # Get the organ label at the clicked position
        # Note: y coordinate maps to rows (first dimension), x to columns (second dimension)
        if 0 <= y < seg_slice.shape[0] and 0 <= x < seg_slice.shape[1]:
            organ_label = int(seg_slice[y, x])
            
            if organ_label == 0:
                return jsonify(success=True, organ_name=None, message="No organ at this location")
            
            # Map organ label to organ name
            organ_names = list(ORGAN_STATS.keys())
            if 1 <= organ_label <= len(organ_names):
                organ_name = organ_names[organ_label - 1]
                organ_data = ORGAN_STATS[organ_name]
                
                # Get health information if available
                health_info = HEALTH_INFO.get(organ_name, {})
                
                return jsonify(
                    success=True,
                    organ_name=organ_name,
                    organ_label=organ_label,
                    volume=organ_data.get('volume', 0),
                    intensity=organ_data.get('intensity', 0),
                    health_info=health_info
                )
            else:
                return jsonify(success=False, message=f"Unknown organ label: {organ_label}")
        else:
            return jsonify(success=False, message="Coordinates out of bounds")
            
    except Exception as e:
        return jsonify(success=False, message=f"Error: {str(e)}"), 500

@app.route("/api/my-body/health-info")
def api_my_body_health_info():
    """Get health information for a specific organ"""
    if not _require_login():
        return jsonify(success=False, message="Login required"), 401
    
    organ_name = request.args.get('organ')
    if not organ_name:
        return jsonify(success=False, message="Organ name required"), 400
    
    if organ_name not in HEALTH_INFO:
        return jsonify(success=False, message="Health information not available for this organ"), 404
    
    return jsonify(success=True, health_info=HEALTH_INFO[organ_name])

def _hsv_to_rgb(h, s, v):
    """Convert HSV to RGB"""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h/360, s, v)
    return (int(r*255), int(g*255), int(b*255))

# --------------------------------------------------------------------------------
# PDF Form Filling endpoints - now in functions/auto_form_fill.py
# --------------------------------------------------------------------------------
 

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)