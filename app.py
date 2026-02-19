import pandas as pd
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr
import os
import json
import gspread
from google.oauth2 import service_account
from io import StringIO

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Global dataframes
pilot_df = drone_df = mission_df = None
today = datetime(2026, 2, 19)

def parse_date(dstr):
    return datetime.strptime(dstr, '%Y-%m-%d')

def days_duration(start, end):
    return (parse_date(end) - parse_date(start)).days + 1

def pilot_available(pilot, start, end):
    if pilot['status'] != 'Available': return False
    avail_from = parse_date(pilot['availablefrom'])
    return avail_from <= parse_date(start)

def skills_match(pilot_skills, req_skills):
    return any(s.strip() in pilot_skills.split(',') for s in req_skills.split(','))

def certs_match(pilot_certs, req_certs):
    return any(c.strip() in pilot_certs.split(',') for c in req_certs.split(','))

def weather_ok(weather_res, forecast):
    if 'IP43' in weather_res: return True
    if 'None' in weather_res and forecast == 'Sunny': return True
    return False

def conflicts(pilot_id, drone_id, mission_id):
    pilot = pilot_df[pilot_df['pilotid'] == pilot_id].iloc[0]
    drone = drone_df[drone_df['droneid'] == drone_id].iloc[0]
    mission = mission_df[mission_df['projectid'] == mission_id].iloc[0]
    
    alerts = []
    # Skill/Cert checks
    if not skills_match(pilot['skills'], mission['requiredskills']): 
        alerts.append("Skill mismatch")
    if not certs_match(pilot['certifications'], mission['requiredcerts']): 
        alerts.append("Cert mismatch")
    
    # Location checks
    if pilot['location'] != mission['location']: 
        alerts.append("Pilot location mismatch")
    if drone['location'] != mission['location']: 
        alerts.append("Drone location mismatch")
    
    # Cost check
    cost = pilot['dailyrateinr'] * days_duration(mission['startdate'], mission['enddate'])
    if cost > int(mission['missionbudgetinr']): 
        alerts.append(f"Budget overrun: {cost} > {mission['missionbudgetinr']}")
    
    # Drone checks
    if drone['status'] != 'Available': 
        alerts.append("Drone not available")
    if not weather_ok(drone['weatherresistance'], mission['weatherforecast']): 
        alerts.append("Weather incompatible")
    
    return alerts

def query_pilots(skill=None, loc=None, cert=None):
    avail = pilot_df[
        (pilot_df['status'] == 'Available') & 
        (pilot_df['availablefrom'] <= today.strftime('%Y-%m-%d'))
    ]
    if skill: 
        avail = avail[avail['skills'].str.contains(skill, na=False)]
    if loc: 
        avail = avail[avail['location'] == loc]
    if cert: 
        avail = avail[avail['certifications'].str.contains(cert, na=False)]
    return avail[['pilotid', 'name', 'location', 'dailyrateinr']]

def query_drones(cap=None, loc=None, weather=None):
    avail = drone_df[drone_df['status'] == 'Available']
    if cap: 
        avail = avail[avail['capabilities'].str.contains(cap, na=False)]
    if loc: 
        avail = avail[avail['location'] == loc]
    return avail[['droneid', 'model', 'location', 'weatherresistance']]

def assign_pilot_drone_to_mission(pilot_id, drone_id, mission_id):
    alerts = conflicts(pilot_id, drone_id, mission_id)
    if alerts:
        return f"Conflicts: {'; '.join(alerts)}"
    
    # Update dataframes (sync to sheets in production)
    pilot_df.loc[pilot_df['pilotid'] == pilot_id, 'status'] = 'Assigned'
    pilot_df.loc[pilot_df['pilotid'] == pilot_id, 'currentassignment'] = mission_id
    drone_df.loc[drone_df['droneid'] == drone_id, 'status'] = 'Assigned'
    drone_df.loc[drone_df['droneid'] == drone_id, 'currentassignment'] = mission_id
    return f"✅ Assigned {pilot_id}/{drone_id} to {mission_id}. No conflicts."

def update_pilot_status(pilot_id, status):
    pilot_df.loc[pilot_df['pilotid'] == pilot_id, 'status'] = status
    if status == 'Available':
        pilot_df.loc[pilot_df['pilotid'] == pilot_id, 'currentassignment'] = '-'
    return f"Pilot {pilot_id} status: {status}"

# Load demo data on startup
@app.on_event("startup")
async def load_demo_data():
    global pilot_df, drone_df, mission_df
    pilot_df = pd.read_csv(StringIO('''pilotid,name,skills,certifications,location,status,currentassignment,availablefrom,dailyrateinr
P001,Arjun,"Mapping, Survey",DGCA Night Ops,Bangalore,Available,-,2026-02-05,1500
P002,Neha,Inspection,DGCA,Mumbai,Assigned,Project-A,2026-02-12,3000
P003,Rohit,"Inspection, Mapping",DGCA,Mumbai,Available,-,2026-02-05,1500
P004,Sneha,"Survey, Thermal",DGCA Night Ops,Bangalore,On Leave,-,2026-02-15,5000'''))
    
    drone_df = pd.read_csv(StringIO('''droneid,model,capabilities,status,location,currentassignment,maintenancedue,weatherresistance
D001,DJI M300,"LiDAR, RGB",Available,Bangalore,-,2026-03-01,IP43 Rain
D002,DJI Mavic 3,RGB,Maintenance,Mumbai,-,2026-02-01,None Clear Sky Only
D003,DJI Mavic 3T,Thermal,Available,Mumbai,-,2026-04-01,IP43 Rain
D004,Autel Evo II,"Thermal, RGB",Available,Bangalore,-,2026-03-15,None Clear Sky Only'''))
    
    mission_df = pd.read_csv(StringIO('''projectid,client,location,requiredskills,requiredcerts,startdate,enddate,priority,missionbudgetinr,weatherforecast
PRJ001,Client A,Bangalore,Mapping,DGCA,2026-02-06,2026-02-08,High,10500,Rainy
PRJ002,Client B,Mumbai,Inspection,"DGCA, Night Ops",2026-02-07,2026-02-09,Urgent,10500,Sunny
PRJ003,Client C,Bangalore,Thermal,DGCA,2026-02-10,2026-02-12,Standard,10500,Cloudy'''))
    print("✅ Demo data loaded!")

@app.get("/")
async def root():
    return {"msg": "Skylark Drone Agent ready! Visit /docs"}

@app.get("/query_pilots")
async def api_query_pilots(skill: str = None, loc: str = None):
    return query_pilots(skill, loc, None).to_dict('records')

@app.get("/query_drones")
async def api_query_drones(cap: str = None, loc: str = None):
    return query_drones(cap, loc, None).to_dict('records')

@app.post("/assign")
async def api_assign(data: dict):
    return {"result": assign_pilot_drone_to_mission(data['pilot_id'], data['drone_id'], data['mission_id'])}

@app.post("/update_pilot")
async def api_update(data: dict):
    return {"result": update_pilot_status(data['pilot_id'], data['status'])}

# Gradio chat (simple)
def chat_interface(message, history):
    if "assign" in message.lower():
        parts = message.split()
        if len(parts) >= 4:
            return assign_pilot_drone_to_mission(parts[1], parts[2], parts[3])
    elif "query pilots" in message.lower():
        return str(query_pilots())
    return "Use: 'query pilots Mapping Bangalore' or 'assign P001 D001 PRJ001'"

demo = gr.ChatInterface(chat_interface)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
