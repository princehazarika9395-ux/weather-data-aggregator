# Weather Data Aggregator with Historical Analysis

An advanced Python academic project with a Streamlit dashboard, Open-Meteo API integration, SQLite persistence, historical weather analysis, Plotly visualizations, and CSV export.

## Requirements

- Python 3.10 or newer
- VS Code
- Internet connection (for weather API requests)

## Project structure

```text
weather_data_aggregator/
├── app.py
├── requirements.txt
├── README.md
└── data/
    └── weather_history.db   # created automatically after first run
```

## Run in VS Code

1. Extract the ZIP file.
2. Open the `weather_data_aggregator` folder in VS Code.
3. Open **Terminal → New Terminal**.
4. Create a virtual environment:

   Windows:
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use Command Prompt:
   ```bat
   .venv\Scripts\activate.bat
   ```

   macOS/Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

5. Install packages:
   ```bash
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

6. Start the dashboard:
   ```bash
   streamlit run app.py
   ```

7. A browser tab should open. If it does not, open the local URL printed in the terminal (usually `http://localhost:8501`).

## Use the application

1. The dashboard initially attempts to show Guwahati.
2. In the sidebar, enter a city name and click **Search city**.
3. Select the correct matching city from the results.
4. Select a start and end date. The archive API has a delay; this app asks for an end date at least six days in the past.
5. Click **Fetch & save history**.
6. Review the statistics and charts, then export the visible records as CSV.

## Data sources and limitations

- Geocoding: `https://geocoding-api.open-meteo.com/v1/search`
- Current weather: `https://api.open-meteo.com/v1/forecast`
- Historical archive: `https://archive-api.open-meteo.com/v1/archive`
- Ordinary non-commercial use of Open-Meteo is available without an API key; check the provider's current terms for your use case.
- Internet access is needed for new API data. Previously saved SQLite records remain local.
- Historical API data can be revised by the provider.
- The daily mean shown in this app is an estimate calculated as (daily maximum + daily minimum) / 2; it is not an hourly mean.
- The SQLite database is created at `data/weather_history.db`.

## Troubleshooting

- `streamlit is not recognized`: activate `.venv`, then run `python -m pip install -r requirements.txt`.
- PowerShell activation error: use Command Prompt activation, or run the environment's Python directly with `.venv\Scripts\python.exe -m streamlit run app.py`.
- City not found: check spelling or try a nearby larger city.
- API/network error: check internet connectivity and try again later.
- No charts: fetch and save historical records first.
- Date range error: choose an end date at least six days in the past.

## Viva points

- Streamlit creates the web interface from Python.
- Requests sends HTTP GET requests to the Open-Meteo APIs.
- Pandas converts JSON daily arrays into tabular data and calculates statistics.
- SQLite provides local persistent storage.
- A UNIQUE constraint prevents duplicate city/date/coordinate records.
- Plotly creates interactive line, bar, and area charts.
