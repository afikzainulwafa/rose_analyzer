# ROSE Analyzer — PMSE Estate Road & Accelerometer Analytics

An interactive, high-performance web analytics application for monitoring palm oil estate road conditions, surface roughness (IRI), vehicle speeds, and 3-axis accelerometer telemetry (shocks and vibrations) across oil palm plantations.

---

## 🌟 Key Features

- **Interactive Estate GIS Map**: Leaflet-based map rendering with satellite imagery, dark canvas, and OpenStreetMap basemaps. Integrates estate block polygons (`PMSE.json`, Divisions 1–6).
- **Multi-Date Road Survey Analytics**:
  - **03 Nov 2026**: 1,317 segments (30.5 km)
  - **04 Nov 2026**: 1,745 segments (40.7 km)
  - **05 Nov 2026**: 2,806 segments (65.5 km)
  - **06 Nov 2026**: 1,263 segments (29.3 km)
  - **Combined**: 7,131 road segments spanning ~166 km
- **Multi-Metric Visualization**:
  - 🚦 **Road Condition (Status)**: Normal (Good), Rusak Ringan, Rusak Sedang, Rusak Berat
  - 🏎️ **Vehicle Speed**: Color-graded speed ranges (<15 km/h to >35 km/h)
  - 📉 **Roughness Index (IRI)**: Smooth (<2.0) to very rough (>8.0)
  - ⚡ **Z-Vibration Shock**: Visualizing vertical bumps and pothole impacts
  - 📅 **Survey Date**: Color classification by date
- **Interactive Time Filtering**:
  - Dual-range time slider and time inputs to filter surveys by exact hours (`HH:MM:SS`).
  - Quick time presets (Semua Jam, Pagi 09–12, Siang 12–15, Sore 15–19).
- **Spatial Search & Division Filtering**:
  - Instant estate block search (e.g. `E-17`, `B-16`) and division filtering (Div 1 to Div 6).
- **Telemetry Inspector & Charts**:
  - Live 3-axis accelerometer chart (X Lateral, Y Longitudinal, Z Vertical shock) and speed profiles.
  - Interactive route simulation with scrubber and vehicle telemetry HUD.
- **Analytics Dashboard**:
  - Road condition breakdown donut chart.
  - Speed histogram and daily survey comparison stacked bar chart.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+ (standard library only; no external dependencies required for the server)

### Running the App
1. Clone the repository:
   ```bash
   git clone https://github.com/afikzainulwafa/rose_analyzer.git
   cd rose_analyzer
   ```
2. Launch the application:
   - On Windows: double-click `start_app.bat` or run:
     ```bash
     python app.py
     ```
3. Open your browser at:
   ```
   http://127.0.0.1:8088
   ```

---

## 📂 Project Structure

```
├── app.py              # Lightweight HTTP server & segment detail API
├── data_prep.py        # Data pipeline processing raw CSVs into web JSON
├── start_app.bat       # Windows launcher script
├── PMSE.json           # Estate block boundary polygons (GeoJSON)
├── PMSE.qgz            # QGIS project file
├── Peta Kebun PMSE.pdf # Estate plantation overview map
├── web/
│   ├── index.html      # Main single-page analytics application
│   ├── static/         # Leaflet & Chart.js offline vendor libraries
│   └── data/           # Pre-processed survey datasets and summary stats
└── .gitignore          # Excludes large raw sensor files, videos, and archives
```

---

## 📄 License
Internal Estate Operations & Analytics — All Rights Reserved.

