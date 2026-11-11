# SENTINEL di EdgeOne Pages

Semua berjalan di EdgeOne: `index.html` (statis) + `cloud-functions/api/[[default]].py` (FastAPI, Python 3.10).

## Deploy
1. Push folder ini ke repo, buat proyek EdgeOne Pages (framework preset: Other, tanpa build command).
2. Isi Environment Variables dari `.env.example` (minimal `MAKERS_MODELS_KEY` bila ingin analisis LLM).
3. Lokal: `edgeone pages dev`.

## Alur (semua stateless, tiap request < 120 dtk)
`POST /api/context` -> `POST /api/analyze` (heuristik) -> `POST /api/llm` (penilaian LLM, request terpisah).

## Uji
`pip install fastapi httpx pytest && python tests/test_api.py && python tests/test_llm.py`
