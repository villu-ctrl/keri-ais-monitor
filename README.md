# AIS Monitor - Gulf of Finland

Automated AIS (Automatic Identification System) monitoring for vessels entering restricted areas near Keri island.

## Features

- ?? Monitors ALL vessels in Gulf of Finland
- ?? Geofence breach detection
- ?? Email alerts via Office365
- ??? Interactive Leaflet map with vessel trails
- ?? 3-hour position history tracking
- ? Runs automatically every 5 minutes via GitHub Actions

## Files

### Core Files
- `ais_monitor.py` - Main monitoring script
- `piiratud.geojson` - Production restricted area polygon
- `piiratud_test.geojson` - Larger test area polygon
- `requirements.txt` - Python dependencies

### Output Files (auto-generated)
- `out/vessels.geojson` - Current vessel positions
- `out/trails.geojson` - Vessel movement trails (3h)
- `out/restricted.geojson` - Copy of geofence polygon
- `out/ais_monitor.html` - Interactive map viewer
- `ais_trails.db` - SQLite database with position history
- `ais_monitor.log` - Monitoring log

### Configuration
- `.github/workflows/ais-monitor.yml` - GitHub Actions workflow

## Setup

### 1. Fork/Clone Repository

```bash
git clone <your-repo-url>
cd Keri_piiratud
```

### 2. Configure GitHub Secrets

Go to your GitHub repository ? Settings ? Secrets and variables ? Actions

Add secret:
- `AIS_EMAIL_PASSWORD` - Your email password for alerts

### 3. Enable GitHub Actions

- Go to Actions tab in your repository
- Enable workflows if prompted
- The monitor will run automatically every 5 minutes

### 4. Manual Trigger (Optional)

- Go to Actions ? AIS Monitor workflow
- Click "Run workflow" to trigger immediately

## Local Development

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run once
python ais_monitor.py --once

# Run continuously (5 min intervals)
python ais_monitor.py
```

## Configuration

Edit `ais_monitor.py` to change:

```python
CONFIG = {
    'geofence': 'piiratud.geojson',  # or piiratud_test.geojson
    'check_interval_seconds': 300,     # 5 minutes
    'trail_hours': 3,                  # Trail history duration
    'bbox': {                          # Gulf of Finland area
        'latmin': 59.0, 'latmax': 60.5,
        'lonmin': 24.0, 'lonmax': 27.0
    }
}
```

## View Results

- **Map**: Open `out/ais_monitor.html` in browser
- **Logs**: Check `ais_monitor.log` or GitHub Actions logs
- **Data**: GeoJSON files in `out/` directory

## Data Sources

- AIS positions: [digitraffic.fi](https://meri.digitraffic.fi/api/ais/v1/locations)
- Vessel metadata: [digitraffic.fi vessels API](https://meri.digitraffic.fi/api/ais/v1/vessels)

## License

MIT License
