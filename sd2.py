import cv2
import time
import io
import base64
import json
from PIL import Image
import google.generativeai as genai
import pyttsx3
from collections import deque
import geocoder
import speech_recognition as sr
import asyncio
import websockets
import os  # for environment variable access

# --- CONFIGURE GEMINI ---
genai.configure(api_key="AIzaSyBDzaYAAgBdxpLUsct6NaliSiCuejYUVpY")
model = genai.GenerativeModel(model_name="gemini-1.5-flash")

# --- TTS INIT ---
try:
    engine = pyttsx3.init()
    engine.setProperty('rate', 160)
    engine.setProperty('volume', 0.9)
except Exception as e:
    print(f"⚠️ TTS engine unavailable: {e}. Falling back to console-only speak.")
    engine = None

# --- Global Variables ---
first_capture           = True
weapon_detection_queue  = deque()
empty_cycles            = 0
camera_location         = {"latitude": 28.6139, "longitude": 77.2090}
current_mode            = "surveillance"
system_armed            = True
last_audio_time         = 0
audio_cooldown          = 3
last_detection_time     = 0
detection_interval      = 2
beep_played             = False

# Military Knowledge Base
CANTONMENTS = {
    "Central Command": ["Agra Cantonment Board", "Prayagraj Cantonment Board"],
    "Eastern Command": ["Barrackpore Cantonment Board", "Jalapahar Cantonment Board"],
}

ARMED_FORCES_CHIEFS = {
    "Chief of Defence Staff": {
        "name": "General Anil Chauhan",
        "decorations": ["PVSM", "UYSM", "AVSM", "SM", "VSM"],
        "assumed_office": "September 2022"
    }
}

WEAPON_KNOWLEDGE = {
    "AK-47": {
        "type": "Assault Rifle",
        "caliber": "7.62x39mm",
        "range": "400m",
        "features": "Gas-operated, rotating bolt"
    }
}

# WebSocket server config
connected_clients = set()
WS_HOST = "0.0.0.0"
WS_PORT = int(os.environ.get("PORT", "8765"))  # Render provides PORT env var

# --- Helper Functions ---

def safe_speak(text: str):
    try:
        engine.say(text)
        engine.runAndWait()
    except RuntimeError as e:
        if "run loop already started" in str(e):
            engine.endLoop()
            engine.say(text)
            engine.runAndWait()
        else:
            print(f"⚠️ TTS Error: {e}")
    except Exception as e:
        print(f"⚠️ TTS Error: {e}")

def play_beep():
    try:
        import sys, os
        if sys.platform == 'linux':
            os.system('play -nq -t alsa synth 0.1 sine 1000')
        else:
            print('\a')
    except:
        pass

def get_location():
    try:
        g = geocoder.ip('me', timeout=2.0)
        if g.ok and g.latlng:
            return {"latitude": g.latlng[0], "longitude": g.latlng[1]}
    except:
        pass
    return camera_location

camera_location = get_location()

def capture_image(filename='auto_capture.jpg', delay=5) -> str | None:
    global first_capture
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise IOError("Cannot open webcam")

    wait = delay if first_capture else 1
    print(f"⏳ Capturing image in {wait} seconds…")
    time.sleep(wait)
    first_capture = False

    ret, frame = cap.read()
    cap.release()
    if ret:
        cv2.imwrite(filename, frame)
        print(f"✅ Image captured: {filename}")
        return filename
    else:
        print("❌ Failed to capture image.")
        return None

def encode_image_to_base64(image_path: str) -> tuple[str, str]:
    with Image.open(image_path) as img:
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        data = buf.getvalue()
    return base64.b64encode(data).decode(), "image/jpeg"

def listen_command(timeout=5) -> str | None:
    global beep_played
    r = sr.Recognizer()
    r.pause_threshold = 1.0
    r.phrase_threshold = 0.5
    with sr.Microphone() as src:
        print("🎤 Listening...")
        try:
            if not beep_played:
                play_beep()
                beep_played = True
            audio = r.listen(src, timeout=timeout)
            beep_played = False
            text = r.recognize_google(audio)
            print(f"🎤 Heard: {text}")
            return text.lower()
        except sr.WaitTimeoutError:
            beep_played = False
            return None
        except Exception as e:
            beep_played = False
            print(f"⚠️ Speech recog error: {e}")
            return None

def parse_detection(response_text: str):
    try:
        clean = response_text.replace('```json', '').replace('```', '').replace('*', '').strip()
        data = json.loads(clean)
        weapons = [w for w in data.get("weapons_detected", []) if w.get("confidence", 0) > 0.70]
        crowd = data.get("crowd_analysis", {})
        return (
            weapons,
            crowd.get("total_people", 0),
            crowd.get("armed_people", 0),
            crowd.get("age_groups", {})
        )
    except Exception as e:
        print(f"⚠️ JSON parse error: {e}")
        return [], 0, 0, {}

def analyze_image(image_part: dict) -> str:
    prompt = """Analyze this security image with military-grade precision and return strict JSON without extra text:
{
  "weapons_detected":[{"type":"","confidence":0.0,"bbox":[x1,y1,x2,y2]}],
  "crowd_analysis":{"total_people":0,"armed_people":0,"age_groups":{},"crowd_density":""}
}"""
    try:
        resp = model.generate_content([{"text": prompt}, image_part])
        return resp.text
    except Exception as e:
        print(f"⚠️ Image analysis failed: {e}")
        return '{"weapons_detected":[],"crowd_analysis":{}}'

def analyze_weapon_details(weapon: dict, image_part: dict) -> dict:
    prompt = f"""Provide JSON with exact model, range, caliber, threat_level, countermeasures, engagement_distance for this {weapon.get('type','weapon')}.
"""
    try:
        resp = model.generate_content([{"text": prompt}, image_part])
        txt = resp.text.strip("```json\n").strip("\n```")
        return json.loads(txt)
    except Exception as e:
        print(f"⚠️ Weapon detail error: {e}")
        return {
            "model":"Unknown","range":"Unknown","caliber":"Unknown",
            "threat_level":"Unknown","countermeasures":["Unknown"],
            "engagement_distance":"Unknown"
        }

def generate_tactical_commands(weapons: list, crowd_data: dict) -> dict:
    primary = weapons[0] if weapons else {}
    cmds = [
        f"Establish {primary.get('engagement_distance','500m')} perimeter",
        "Snipers take positions",
        "QRF standby",
        f"Verify {crowd_data['armed_people']} hostiles",
        "Medics prepare trauma kits"
    ]
    return {"commands": cmds, "threat_level": primary.get("threat_level","Unknown")}

def create_verbal_report(weapons: list, crowd_data: dict, commands: dict) -> str:
    p = weapons[0] if weapons else {}
    report = (
        f"Visual: {len(weapons)} armed. Over.\n"
        f"Weapon: {p.get('model','Unknown')} range {p.get('range','Unknown')}. Over.\n"
        f"Crowd: {crowd_data['total_people']} total, {crowd_data['armed_people']} armed. Over.\n"
        "Commands: " + "; ".join(commands["commands"])
    )
    print("📄 Verbal report:", report)
    return report

# --- WebSocket Functions ---

async def websocket_handler(ws, path):
    connected_clients.add(ws)
    try:
        await ws.wait_closed()
    finally:
        connected_clients.remove(ws)

async def broadcast_data(data: dict, image_path: str = None):
    print("🔗 Broadcast:", json.dumps(data, indent=2))
    if connected_clients:
        # Send JSON data first
        await asyncio.gather(
            *(c.send(json.dumps(data)) for c in connected_clients),
            return_exceptions=True
        )
        # If an image path is provided, send the image as binary
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                await asyncio.gather(
                    *(c.send(image_data) for c in connected_clients),
                    return_exceptions=True
                )
                print("📷 Image sent over WebSocket")
            except Exception as e:
                print(f"⚠️ Error sending image: {e}")

# --- Conversation Handler (now async!) ---

async def handle_conversation():
    global current_mode, last_audio_time, empty_cycles, last_detection_time

    now = time.time()
    if now - last_audio_time < audio_cooldown:
        return

    last_audio_time = now
    safe_speak("Listening now")

    query = listen_command()
    if query:
        print("🗨️ Query:", query)
        if "switch to surveillance" in query:
            current_mode = "surveillance"
            safe_speak("Switching to surveillance mode. Over and out.")
            empty_cycles = 0
            await broadcast_data({"mode": current_mode})
            return

        response = None
        if "cantonment" in query:
            response = "Indian Army Cantonments: " + ", ".join(CANTONMENTS.keys())
        elif "chief" in query:
            response = "; ".join(f"{r}: {i['name']}" for r,i in ARMED_FORCES_CHIEFS.items())
        elif any(w in query for w in ["weapon","grenade","rifle"]):
            for w, info in WEAPON_KNOWLEDGE.items():
                if w.lower() in query:
                    response = f"{w}: Type {info['type']}, {info['caliber']} range {info['range']}"
                    break

        if not response:
            try:
                prompt = f"Answer concisely: {query}" 
                resp = model.generate_content(prompt)
                response = resp.text.replace("*", "")
            except Exception as e:
                print(f"⚠️ Gemini error: {e}")
                response = "Error processing request."

        print("🗨️ Response:", response)
        safe_speak(response)
        await broadcast_data({"verbal_report": response, "mode": current_mode})
    else:
        safe_speak("Standing by")
        await broadcast_data({"verbal_report":"Standing by","mode":current_mode})

# --- Detection Loop (sync, uses create_task for broadcasts) ---

def perform_detection() -> tuple[bool, dict|None]:
    global first_capture, empty_cycles, current_mode, last_detection_time

    if current_mode == "surveillance":
        safe_speak("Performing surveillance check")

    img = capture_image(delay=5 if first_capture else 1)
    if not img:
        return False, None

    b64, mime = encode_image_to_base64(img)
    raw = analyze_image({"inline_data":{"mime_type":mime,"data":b64}})
    weapons, total, armed, ages = parse_detection(raw)

    if not weapons:
        empty_cycles += 1
        print(f"✅ No weapons – Empty cycles: {empty_cycles}/3")
        if empty_cycles == 3 and current_mode != "conversation":
            current_mode = "conversation"
            safe_speak("Conversation mode activated.")
            last_detection_time = time.time()
            asyncio.create_task(broadcast_data({"mode": current_mode}))
        return False, None

    if current_mode != "surveillance":
        current_mode = "surveillance"
        safe_speak("Weapon detected! Switching to surveillance mode.")
        asyncio.create_task(broadcast_data({"mode": current_mode}))

    empty_cycles = 0
    enriched = []
    for w in weapons:
        det = analyze_weapon_details(w, {"inline_data":{"mime_type":mime,"data":b64}})
        enriched.append({**w, **det})

    crowd = {"total_people": total, "armed_people": armed, "age_groups": ages}
    cmds = generate_tactical_commands(enriched, crowd)
    report = create_verbal_report(enriched, crowd, cmds)

    safe_speak(report)

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "mode": current_mode,
        "commands": cmds,
        "weapons": enriched,
        "location": camera_location,
        "timestamp": timestamp,
        "threat_level": cmds["threat_level"]
    }
    print("📡 Payload:", json.dumps(payload, indent=2))
    weapon_detection_queue.append(payload)
    asyncio.create_task(broadcast_data(payload, image_path=img))

    return True, payload

# --- Main Async Loop ---

async def main():
    global empty_cycles, last_detection_time

    server = await websockets.serve(websocket_handler, WS_HOST, WS_PORT)
    print(f"✅ WebSocket server listening on ws://{WS_HOST}:{WS_PORT}")

    safe_speak("System initialized. Beginning surveillance operations.")
    await broadcast_data({"mode": current_mode})

    try:
        while True:
            now = time.time()
            if (current_mode == "surveillance"
                or (current_mode == "conversation" and now - last_detection_time >= detection_interval)):
                last_detection_time = now
                print("🔄 Performing threat assessment…")
                detected, data = perform_detection()
                if detected:
                    print(f"🚨 Threat detected! Queue size: {len(weapon_detection_queue)}")

                if empty_cycles >= 5 and weapon_detection_queue:
                    print("♻️ Clearing detection queue")
                    weapon_detection_queue.clear()
                    empty_cycles = 0

            if current_mode == "conversation":
                await handle_conversation()

            await asyncio.sleep(0.5)

    except KeyboardInterrupt:
        print("\n🛑 Program stopped by user")
        safe_speak("System shutdown initiated. Over and out.")
    finally:
        server.close()
        await server.wait_closed()
        engine.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    asyncio.run(main())
