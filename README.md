# RyyderBros Field Pilot

AI crop scouting for Alabama corn and cotton fields. It combines satellite imagery, weather, soil surveys, and county yield history, and an AI agent explains the results. Every number in an AI answer is checked against the source data.

**Live demo:** https://ryyderbros-fieldpilot.onrender.com/

## Architecture

```mermaid
flowchart LR
    subgraph Tools["Data tools"]
        S2[Sentinel-2<br/>NDVI and NDRE]
        Z[Productivity zones]
        W[Weather<br/>Open-Meteo]
        SO[Soil<br/>USDA SSURGO]
        Y[Yield model<br/>USDA NASS + NASA POWER]
    end
    Tools --> C[Field context<br/>parallel run + JSON cache]
    C --> R[Report graph<br/>write, verify, rewrite]
    C --> A[Chat agent<br/>tool calling + verify]
    R --> API[FastAPI]
    A --> API
    API --> UI[React frontend]
```

**Stack:** Python, FastAPI, LangGraph, Groq, scikit-learn, React, Docker, Render
