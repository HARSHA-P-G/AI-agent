import pandas as pd
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr
import gspread
from io import StringIO

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Load data (dynamic: from Sheets or CSV URLs/paths)
def load_data(pilot_url, drone_url, mission_url):
    global pilot_df, drone_df, mission_df
    gc = gspread.service_account()  # Setup creds.json
    pilot_df = pd.DataFrame(gc.open_by_url(pilot_url).sheet1.get_all_records())
    drone_df = pd.DataFrame(gc.open_by_url(drone_url).sheet1.get_all_records())
    mission_df = pd.DataFrame(gc.open_by_url(mission_url).sheet1.get_all_records())
    return "Data loaded!"



@app.post("/load_data")
def api_load(pilot_url: str, drone_url: str, mission_url: str):
    load_data(pilot_url, drone_url, mission_url)
    return {"status": "loaded"}

@app.get("/query_pilots")
def api_query_pilots(skill: str = None, loc: str = None):
    return query_pilots(skill, loc, None).to_dict('records')

@app.post("/assign")
def api_assign(pilot_id: str, drone_id: str, mission_id: str):
    return {"result": assign_pilot_drone_to_mission(pilot_id, drone_id, mission_id)}

@app.post("/update_pilot")
def api_update(pilot_id: str, status: str):
    return {"result": update_pilot_status(pilot_id, status)}

# Gradio chat interface
def chat_interface(message, history):
    # Parse commands e.g., "assign P001 D001 PRJ001" -> call api_assign
    if "assign" in message.lower():
        parts = message.split()
        return assign_pilot_drone_to_mission(parts[1], parts[2], parts[3])
    elif "query pilots" in message.lower():
        # Parse args, call query_pilots
        return str(query_pilots())
    # Add more parsers...
    return "Command processed."

demo = gr.ChatInterface(chat_interface)

@app.get("/")
def root():
    return {"msg": "Skylark API ready. Use /docs for endpoints."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
