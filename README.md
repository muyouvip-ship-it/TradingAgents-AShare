# TradingAgents-AShare

## Quick Start

### Backend

```bash
python -m pip install -r requirements.txt
uvicorn api.app:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Testing

```bash
pytest -q
cd frontend
npm test
```

## Architecture

See `architecture.md` for the backend/frontend layering and execution flow.
