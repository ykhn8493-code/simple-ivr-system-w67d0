import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response
from twilio.twiml.voice_response import VoiceResponse, Gather

app = Flask(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "ivr_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "company_name": "Our Company",
        "greeting_message": "Thank you for calling. Press 1 for Sales, 2 for Support, 3 for Hours, 4 for Voicemail, 0 for Operator.",
        "business_hours": "We are open Monday to Friday, 9am to 5pm.",
        "sales_message": "Connecting to sales.",
        "support_message": "Support is currently busy. Please wait.",
        "operator_message": "Transferring to operator.",
        "voicemail_prompt": "Please leave a message after the beep.",
        "invalid_choice_message": "Invalid choice. Please try again."
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# In-memory store for call history and voicemails
call_logs = []
voicemails = []

def add_log(caller, event, details=""):
    entry = {
        "id": len(call_logs) + 1,
        "caller": caller or "Simulator / Anonymous",
        "event": event,
        "details": details,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    call_logs.insert(0, entry)
    if len(call_logs) > 50:
        call_logs.pop()

# =====================================================================
# WEB INTERFACE ROUTES
# =====================================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        updated = request.get_json() or {}
        cfg = load_config()
        cfg.update(updated)
        save_config(cfg)
        return jsonify({"status": "ok", "config": cfg})
    return jsonify(load_config())

@app.route("/api/logs")
def api_logs():
    return jsonify({"logs": call_logs, "voicemails": voicemails})

@app.route("/api/save-voicemail", methods=["POST"])
def api_save_voicemail():
    data = request.get_json() or {}
    vm = {
        "id": len(voicemails) + 1,
        "caller": data.get("caller", "Web Simulator"),
        "message": data.get("message", "(No text recording)"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    voicemails.insert(0, vm)
    add_log(vm["caller"], "Voicemail Left", vm["message"][:40] + "...")
    return jsonify({"status": "ok", "voicemail": vm})

# =====================================================================
# TWILIO COMPATIBLE IVR WEBHOOK ROUTES
# =====================================================================

@app.route("/voice/welcome", methods=["GET", "POST"])
def voice_welcome():
    caller = request.values.get("From", "Simulator")
    add_log(caller, "Call Started", "Caller reached Main Menu")

    cfg = load_config()
    response = VoiceResponse()
    gather = Gather(num_digits=1, action="/voice/menu-select", method="POST", timeout=5)
    gather.say(cfg["greeting_message"], voice="Polly.Amy", language="en-US")
    response.append(gather)

    # If caller enters no input within timeout
    response.say("We didn't receive any input. Good bye!", voice="Polly.Amy")
    response.hangup()

    return Response(str(response), mimetype="text/xml")

@app.route("/voice/menu-select", methods=["GET", "POST"])
def voice_menu_select():
    digit = request.values.get("Digits", "").strip()
    caller = request.values.get("From", "Simulator")
    cfg = load_config()
    response = VoiceResponse()

    if digit == "1":
        add_log(caller, "Menu Selected: 1 (Sales)")
        response.say(cfg["sales_message"], voice="Polly.Amy")
        response.play("https://demo.twilio.com/docs/classic.mp3")
        response.hangup()
    elif digit == "2":
        add_log(caller, "Menu Selected: 2 (Support)")
        response.say(cfg["support_message"], voice="Polly.Amy")
        response.play("https://demo.twilio.com/docs/classic.mp3")
        response.hangup()
    elif digit == "3":
        add_log(caller, "Menu Selected: 3 (Business Hours)")
        response.say(cfg["business_hours"], voice="Polly.Amy")
        # Allow repeating or returning to menu
        gather = Gather(num_digits=1, action="/voice/menu-select", method="POST")
        gather.say("Press 9 to return to the main menu, or hang up now.", voice="Polly.Amy")
        response.append(gather)
        response.hangup()
    elif digit == "4":
        add_log(caller, "Menu Selected: 4 (Voicemail Prompt)")
        response.say(cfg["voicemail_prompt"], voice="Polly.Amy")
        response.record(
            action="/voice/recording-callback",
            method="POST",
            max_length=60,
            finish_on_key="#",
            play_beep=True
        )
        response.say("Thank you. Your message has been saved. Goodbye.", voice="Polly.Amy")
        response.hangup()
    elif digit == "0":
        add_log(caller, "Menu Selected: 0 (Operator)")
        response.say(cfg["operator_message"], voice="Polly.Amy")
        response.play("https://demo.twilio.com/docs/classic.mp3")
        response.hangup()
    elif digit == "9":
        # Return to main menu
        response.redirect("/voice/welcome")
    else:
        add_log(caller, f"Invalid Input: '{digit}'")
        response.say(cfg["invalid_choice_message"], voice="Polly.Amy")
        response.redirect("/voice/welcome")

    return Response(str(response), mimetype="text/xml")

@app.route("/voice/recording-callback", methods=["GET", "POST"])
def recording_callback():
    caller = request.values.get("From", "Unknown Phone")
    recording_url = request.values.get("RecordingUrl", "")
    transcription = request.values.get("TranscriptionText", "(Voice recording stored in Twilio)")

    vm = {
        "id": len(voicemails) + 1,
        "caller": caller,
        "message": transcription,
        "recording_url": recording_url,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    voicemails.insert(0, vm)
    add_log(caller, "Twilio Voicemail Received", recording_url or transcription)

    response = VoiceResponse()
    response.say("Your recording has been saved. Goodbye!", voice="Polly.Amy")
    response.hangup()
    return Response(str(response), mimetype="text/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n* Simple IVR is running on http://127.0.0.1:{port}")
    print("* Open your browser to test the interactive phone simulator!\n")
    app.run(host="0.0.0.0", port=port, debug=True)
