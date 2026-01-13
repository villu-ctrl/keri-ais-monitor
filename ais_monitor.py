#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple AIS Monitor - Gulf of Finland
Monitors ALL ships in Gulf of Finland, alerts on geofence breach
"""

import json
import logging
import os
import smtplib
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests
from shapely.geometry import Point, shape

# Configuration
CONFIG = {
    'geofence': 'piiratud.geojson',
    'ais_url': 'https://meri.digitraffic.fi/api/ais/v1/locations',
    'vessels_url': 'https://meri.digitraffic.fi/api/ais/v1/vessels',
    'bbox': {'latmin': 59.0, 'latmax': 60.5, 'lonmin': 24.0, 'lonmax': 27.0},
    'max_age_minutes': 10,  # Only show vessels with data from last 10 minutes (uses timestampExternal)
    'fixed_points': [
        {'name': 'Keri station', 'lat': 59.7178, 'lon': 25.0164}
    ],
    'email': {
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'sender': 'villukikas@gmail.com',  # Change to your Gmail
        'recipient': 'villu.kikas@taltech.ee',  # Keep this as recipient
        'password': os.environ.get('AIS_EMAIL_PASSWORD', ''),
        'cooldown_hours': 1,
        'min_speed_knots': 0.2  # Don't alert for stationary/anchored vessels
    },
    'export_dir': 'out',
    'check_interval_seconds': 300,
    'log_file': 'ais_monitor.log',
    'db_file': 'ais_trails.db',
    'trail_hours': 3
}

# Global cache for vessel metadata
_vessel_metadata = {}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG['log_file'], encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class Vessel:
    def __init__(self, data):
        self.mmsi = data.get('mmsi', 0)
        self.name = data.get('name') or f'MMSI-{self.mmsi}'
        self.lat = data.get('lat', 0.0)
        self.lon = data.get('lon', 0.0)
        self.sog = data.get('sog', 0.0)
        self.cog = data.get('cog', 0.0)
        self.heading = data.get('heading', 0)
        self.timestamp = str(data.get('timestamp', ''))
    
    def to_geojson_feature(self):
        return {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [self.lon, self.lat]},
            'properties': {
                'mmsi': self.mmsi,
                'name': self.name,
                'sog': self.sog,
                'cog': self.cog,
                'heading': self.heading,
                'timestamp': self.timestamp
            }
        }

def fetch_vessel_metadata():
    """Fetch vessel metadata (names, types, etc.) from digitraffic API"""
    try:
        logging.info("Fetching vessel metadata...")
        response = requests.get(CONFIG['vessels_url'], timeout=60)
        response.raise_for_status()
        data = response.json()
        
        metadata = {}
        if isinstance(data, list):
            for vessel in data:
                mmsi = vessel.get('mmsi')
                if mmsi:
                    metadata[mmsi] = {
                        'name': vessel.get('name', '').strip(),
                        'shipType': vessel.get('shipType', 0),
                        'callSign': vessel.get('callSign', ''),
                        'imo': vessel.get('imo', 0),
                        'destination': vessel.get('destination', ''),
                        'eta': vessel.get('eta', 0)
                    }
        
        logging.info(f"Loaded metadata for {len(metadata)} vessels")
        return metadata
    
    except Exception as e:
        logging.error(f"Error fetching vessel metadata: {e}")
        return {}

def fetch_vessels():
    """Fetch ALL vessels from digitraffic.fi in Gulf of Finland"""
    global _vessel_metadata
    
    # Refresh metadata if empty or stale (refresh every run)
    if not _vessel_metadata:
        _vessel_metadata = fetch_vessel_metadata()
    
    try:
        logging.info("Fetching AIS data...")
        response = requests.get(CONFIG['ais_url'], timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not data or 'features' not in data:
            logging.warning("No data from API")
            return []
        
        vessels = []
        bbox = CONFIG['bbox']
        
        for feature in data['features']:
            try:
                geom = feature.get('geometry', {})
                props = feature.get('properties', {})
                
                if geom.get('type') != 'Point':
                    continue
                
                coords = geom.get('coordinates', [])
                if len(coords) < 2:
                    continue
                
                lon, lat = coords[0], coords[1]
                
                # Filter: only in bbox
                if not (bbox['latmin'] <= lat <= bbox['latmax'] and 
                        bbox['lonmin'] <= lon <= bbox['lonmax']):
                    continue
                
                mmsi = props.get('mmsi', 0)
                timestamp_ext = props.get('timestampExternal', 0)
                
                # Filter: only vessels with recent data (using timestampExternal)
                if timestamp_ext:
                    age_minutes = (time.time() - timestamp_ext / 1000) / 60
                    if age_minutes > CONFIG['max_age_minutes']:
                        continue
                
                # Get name from metadata if available, otherwise use API name
                vessel_name = props.get('name')
                if mmsi in _vessel_metadata and _vessel_metadata[mmsi]['name']:
                    vessel_name = _vessel_metadata[mmsi]['name']
                
                vessels.append(Vessel({
                    'mmsi': mmsi,
                    'name': vessel_name,
                    'lat': lat,
                    'lon': lon,
                    'sog': props.get('sog', 0),
                    'cog': props.get('cog', 0),
                    'heading': props.get('heading', 0),
                    'timestamp': props.get('timestampExternal', 0)
                }))
            
            except (ValueError, TypeError, KeyError):
                continue
        
        logging.info(f"Found {len(vessels)} vessels in Gulf of Finland")
        return vessels
    
    except Exception as e:
        logging.error(f"Error fetching AIS: {e}")
        return []

def load_geofence(geojson_path):
    """Load polygon from GeoJSON"""
    try:
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if data['type'] == 'FeatureCollection' and data['features']:
            feature = data['features'][0]
            polygon = shape(feature['geometry'])
            name = feature['properties'].get('name', 'Unknown')
            logging.info(f"Loaded geofence: {name}")
            return polygon
        raise ValueError("Invalid GeoJSON")
    except Exception as e:
        logging.error(f"Cannot load geofence: {e}")
        raise

def init_db():
    """Initialize SQLite database for trail tracking"""
    db_path = Path(__file__).parent / CONFIG['db_file']
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            mmsi INTEGER,
            timestamp TEXT,
            lat REAL,
            lon REAL,
            sog REAL,
            cog REAL,
            PRIMARY KEY (mmsi, timestamp)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mmsi ON positions(mmsi)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON positions(timestamp)')
    conn.commit()
    conn.close()
    logging.info(f"Database ready: {db_path}")

def save_positions(vessels):
    """Save vessel positions to database"""
    if not vessels:
        return
    
    db_path = Path(__file__).parent / CONFIG['db_file']
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    for v in vessels:
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (mmsi, timestamp, lat, lon, sog, cog)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (v.mmsi, now, v.lat, v.lon, v.sog, v.cog))
        except Exception as e:
            logging.debug(f"Error saving MMSI {v.mmsi}: {e}")
    
    conn.commit()
    
    # Cleanup old positions
    cutoff = (datetime.utcnow() - timedelta(hours=CONFIG['trail_hours'])).isoformat()
    cursor.execute('DELETE FROM positions WHERE timestamp < ?', (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted > 0:
        logging.info(f"Saved positions, cleaned {deleted} old records")

def build_trails():
    """Build trail GeoJSON from database"""
    db_path = Path(__file__).parent / CONFIG['db_file']
    if not db_path.exists():
        return {'type': 'FeatureCollection', 'features': []}
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all MMSIs with multiple positions
    cursor.execute('''
        SELECT mmsi, COUNT(*) as cnt 
        FROM positions 
        GROUP BY mmsi 
        HAVING cnt > 1
    ''')
    mmsis = [row[0] for row in cursor.fetchall()]
    
    features = []
    for mmsi in mmsis:
        cursor.execute('''
            SELECT lat, lon, timestamp 
            FROM positions 
            WHERE mmsi = ? 
            ORDER BY timestamp
        ''', (mmsi,))
        
        positions = cursor.fetchall()
        if len(positions) < 2:
            continue
        
        coordinates = [[lon, lat] for lat, lon, _ in positions]
        
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'properties': {
                'mmsi': mmsi,
                'points': len(positions),
                'start': positions[0][2],
                'end': positions[-1][2]
            }
        })
    
    conn.close()
    return {'type': 'FeatureCollection', 'features': features}

def check_geofence(vessels, polygon):
    """Return vessels inside polygon with speed above threshold"""
    breaches = []
    min_speed = CONFIG['email']['min_speed_knots']
    
    for v in vessels:
        if polygon.contains(Point(v.lon, v.lat)):
            if v.sog < min_speed:
                logging.info(f"SKIP: {v.name} (MMSI {v.mmsi}) in area but stationary (speed: {v.sog} knots)")
            else:
                breaches.append(v)
                logging.warning(f"BREACH: {v.name} (MMSI {v.mmsi}) in restricted area (speed: {v.sog} knots)")
    return breaches

_alert_cache = {}

def send_alert(vessel):
    """Send email alert with cooldown"""
    now = time.time()
    cooldown = CONFIG['email']['cooldown_hours'] * 3600
    
    if vessel.mmsi in _alert_cache:
        if now - _alert_cache[vessel.mmsi] < cooldown:
            logging.info(f"Cooldown active for MMSI {vessel.mmsi}")
            return False
    
    email_cfg = CONFIG['email']
    if not email_cfg['password']:
        logging.warning("Email not configured")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = email_cfg['sender']
        msg['To'] = email_cfg['recipient']
        msg['Subject'] = f"ALERT: {vessel.name} entered restricted area"
        
        body = f"""
VESSEL BREACH ALERT

Vessel: {vessel.name}
MMSI: {vessel.mmsi}
Position: {vessel.lat:.6f}, {vessel.lon:.6f}
Speed: {vessel.sog} knots
Course: {vessel.cog} degrees

MarineTraffic: https://www.marinetraffic.com/en/ais/details/ships/mmsi:{vessel.mmsi}
VesselFinder: https://www.vesselfinder.com/?mmsi={vessel.mmsi}

---
Automated AIS Monitor
"""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        with smtplib.SMTP(email_cfg['smtp_server'], email_cfg['smtp_port']) as server:
            server.starttls()
            server.login(email_cfg['sender'], email_cfg['password'])
            server.send_message(msg)
        
        _alert_cache[vessel.mmsi] = now
        logging.info(f"Alert sent for MMSI {vessel.mmsi}")
        return True
    
    except Exception as e:
        logging.error(f"Email error: {e}")
        return False

def export_geojson(vessels, out_dir):
    """Write vessels.geojson, trails.geojson, restricted.geojson and fixed_points.geojson"""
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Current vessels
    vessels_fc = {
        'type': 'FeatureCollection',
        'features': [v.to_geojson_feature() for v in vessels]
    }
    (out_dir / 'vessels.geojson').write_text(
        json.dumps(vessels_fc, ensure_ascii=False, indent=2), 
        encoding='utf-8'
    )
    
    # Trails
    trails_fc = build_trails()
    (out_dir / 'trails.geojson').write_text(
        json.dumps(trails_fc, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    
    # Restricted area
    try:
        geofence_src = Path(__file__).parent / CONFIG['geofence']
        restricted = geofence_src.read_text(encoding='utf-8')
        (out_dir / 'restricted.geojson').write_text(restricted, encoding='utf-8')
    except Exception as e:
        logging.debug(f"Could not export restricted: {e}")
    # Fixed points
    if 'fixed_points' in CONFIG and CONFIG['fixed_points']:
        fixed_points_fc = {
            'type': 'FeatureCollection',
            'features': [
                {
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [pt['lon'], pt['lat']]},
                    'properties': {'name': pt['name']}
                }
                for pt in CONFIG['fixed_points']
            ]
        }
        (out_dir / 'fixed_points.geojson').write_text(
            json.dumps(fixed_points_fc, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    
    logging.info(f"Exported GeoJSON to {out_dir} (trails: {len(trails_fc['features'])})")

def run_check(polygon):
    """Single monitoring cycle"""
    logging.info("--- Starting check ---")
    
    vessels = fetch_vessels()
    if not vessels:
        logging.info("No vessels found")
        return
    
    # Save positions to database for trail tracking
    save_positions(vessels)
    
    breaches = check_geofence(vessels, polygon)
    
    # Export for map
    export_geojson(vessels, Path(CONFIG['export_dir']))
    
    # Send alerts
    for vessel in breaches:
        send_alert(vessel)
    
    if not breaches:
        logging.info("No breaches detected")

def monitor_loop(polygon):
    """Continuous monitoring"""
    logging.info("Starting continuous monitoring...")
    logging.info(f"Geofence: {CONFIG['geofence']}")
    logging.info(f"Check interval: {CONFIG['check_interval_seconds']}s")
    
    while True:
        try:
            run_check(polygon)
            time.sleep(CONFIG['check_interval_seconds'])
        except KeyboardInterrupt:
            logging.info("Stopped by user")
            break
        except Exception as e:
            logging.error(f"Error in loop: {e}")
            time.sleep(60)

if __name__ == '__main__':
    geofence_path = Path(__file__).parent / CONFIG['geofence']
    polygon = load_geofence(geofence_path)
    init_db()
    
    if '--once' in sys.argv:
        run_check(polygon)
    else:
        monitor_loop(polygon)



