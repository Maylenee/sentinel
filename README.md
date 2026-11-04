# SENTINEL (Python)

Analisis postingan **publik** Facebook, Instagram, dan TikTok dengan alur **konteks video dulu, baru bedah komentar**.

## Arsitektur
```text
frontend/          EdgeOne Pages: HTML dashboard
cloud-functions/   EdgeOne Cloud Functions: proxy /api/* ke backend
backend/           FastAPI: engine, ASR/OCR, sumber publik, LLM
```

Frontend memanggil path relatif `/api/context`, `/api/job?id={id}`, dan `/api/analyze`. Di EdgeOne, path itu ditangani `cloud-functions/api/<fitur>/index.js`, lalu diteruskan ke backend VPS. Backend tidak perlu CORS karena browser hanya berbicara dengan EdgeOne (same-origin), dan URL backend tidak terekspos ke browser.

## Jalankan lokal (backend + frontend)
Butuh Python 3.9 atau lebih baru.

```bash
cd backend
python start.py
```

`start.py` otomatis membuat `backend/.venv`, memasang dependensi inti, mencoba pustaka opsional, menyiapkan `backend/.env`, lalu menjalankan API di http://127.0.0.1:8787. Backend juga menyajikan `frontend/index.html` untuk development. Opsi: `--no-install`, `--no-venv`, `--no-optional`, `--no-browser`, `--host`, `--port`, `--test`.

## Deploy frontend + cloud functions di EdgeOne
Project root EdgeOne tetap **root repo** (`./`), bukan `frontend/`.

- **Root Directory**: `./`
- **Output Directory**: `frontend`
- **Build Command**: kosong (situs statis)
- **Environment Variables**:

```env
SENTINEL_API_URL=https://api.domain-anda.com
SENTINEL_API_TOKEN=token-yang-sama-dengan-backend
SENTINEL_PROXY_TIMEOUT_MS=110000
```

Struktur cloud function mengikuti nama fitur:

```text
cloud-functions/
  _lib/proxy.js
  api/
    context/index.js    -> POST /api/context
    job/index.js        -> GET  /api/job?id={id}
    analyze/index.js    -> POST /api/analyze
    post/index.js       -> POST /api/post
    health/index.js     -> GET  /api/health
```

Set `maxDuration` Cloud Functions ke `120` detik (sudah diatur di `edgeone.json`). `/api/analyze` harus selesai di bawah batas itu; kalau LLM/ASR lebih lama, kecilkan `LLM_MAX_ACCOUNTS`/`LLM_TOTAL_TIMEOUT` atau pindahkan analisis ke job async.

## Deploy backend di VPS (systemd)
Jangan jalankan `start.py` di server produksi; gunakan ASGI `app:app`. Gunakan **1 worker/proses** karena `JOBS` disimpan di memori.

```bash
cd /home/lighthouse/hackathon/sentinel/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-server.txt
cp .env.example .env
chmod 600 .env
```

Isi `.env` minimal:

```env
MAKERS_MODELS_KEY=...
LLM_ENABLED=1
LLM_MODEL=@makers/deepseek-v4-flash
LLM_MAX_TOKENS=6144
LLM_DISABLE_THINKING=1
SENTINEL_API_TOKEN=token-yang-sama-dengan-edgeone
```

Contoh systemd `/etc/systemd/system/sentinel.service`:

```ini
[Unit]
Description=SENTINEL Backend
After=network.target

[Service]
User=lighthouse
Group=lighthouse
WorkingDirectory=/home/lighthouse/hackathon/sentinel/backend
EnvironmentFile=/home/lighthouse/hackathon/sentinel/backend/.env
ExecStart=/home/lighthouse/hackathon/sentinel/backend/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8787 --workers 1 --proxy-headers --ws none
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel
sudo systemctl status sentinel
```

Backend hanya bind `127.0.0.1`. Supaya cloud function bisa menjangkau, pasang Nginx + HTTPS (`api.domain-anda.com`), lalu isi `SENTINEL_API_URL` di EdgeOne. Timeout proxy Nginx 180–300 detik.

Alternatif panel Python project: project path `.../sentinel/backend`, entry `app.py`, protocol **ASGI**, application `app`, dependency `requirements-server.txt`, startup command:

```bash
uvicorn app:app --host 127.0.0.1 --port 8787 --workers 1 --ws none
```

Startup user `www` (pastikan `.cache` writable). Jika memakai gunicorn `-w 1`, tambahkan `websockets<14` atau gunakan uvicorn langsung karena API ini tidak memakai WebSocket.

## Alur pakai
1. Tempel tautan postingan publik (TikTok/Instagram/Facebook), klik **1. Ambil konteks video**.
2. SENTINEL mengambil caption, mengunduh media **sementara**, menjalankan ASR lokal dan OCR (bila tersedia), lalu menampilkan ringkasan, klaim, dan bukti timestamp.
3. Periksa/edit ringkasan, lalu klik **2. Konfirmasi konteks & bedah komentar**.
4. Dashboard menampilkan sikap komentar terhadap klaim, klaim yang diamplifikasi, clique waktu-lokal, akun urut risiko, dan dossier bukti JSON.

## Sumber data (gratis, open-source)
| Platform | Metadata/komentar | Media untuk ASR/OCR |
|---|---|---|
| TikTok | `yt-dlp` + `curl_cffi` (komentar via endpoint web) | `yt-dlp` |
| Instagram | `instaloader` (kadang perlu `IG_SESSIONFILE`) | `instaloader`/`yt-dlp` |
| Facebook | `facebook-scraper` | `yt-dlp`/URL video publik |

Pasang: `pip install -r requirements-optional.txt` (otomatis dicoba `start.py`). Tidak ada API key. Hanya konten publik.

## ASR, OCR, ffmpeg
- **ASR**: `faster-whisper` lokal, model `small` int8 (default). Model diunduh sekali ke `.cache/whisper`. Atur `WHISPER_MODEL`, `WHISPER_LANGUAGE`, `WHISPER_DEVICE`, `WHISPER_COMPUTE`.
- **ffmpeg**: memakai `ffmpeg` di PATH atau binary dari `imageio-ffmpeg` (ikut terpasang).
- **OCR**: memakai `pytesseract` + binary **Tesseract** bila tersedia; jika tidak, fallback lokal **RapidOCR** (model ONNX sudah ikut paket, tanpa binary eksternal). Set `TESSERACT_CMD` bila Tesseract tidak di PATH.
- Batas media: `PUBLIC_MAX_MEDIA_SEC` (default 600), `PUBLIC_MAX_MEDIA_MB` (default 80), `OCR_FPS`, `OCR_MAX_FRAMES`.
- Media diunduh ke `.cache/media` sementara dan dihapus setelah diproses. Konteks di-cache 7 hari di `.cache/context`; konteks yang gagal ASR tidak di-cache.

## Struktur proyek
```text
frontend/
  index.html        dashboard (deploy ke EdgeOne)
cloud-functions/
  _lib/proxy.js     helper proxy + CORS + timeout
  api/
    context/index.js
    job/index.js
    analyze/index.js
    post/index.js
    health/index.js
backend/
  app.py            FastAPI + job context/analyze
  start.py          pembuat .venv, installer, launcher lokal
  sentinel/
    analysis/       engine, coordination, narrative, evidence
    context/        builder, media, transcribe, ocr
    llm/            klien EdgeOne Makers + analisis buzzer/bot
    sources/        adapter publik TikTok/Instagram/Facebook
  tests/            uji regresi dan integrasi
```

## Cara kerja
1. `backend/sentinel/sources/public.py` menormalkan metadata + komentar. Metadata mencakup caption penuh, hashtag/mention, durasi, statistik, waktu posting, dan URL media.
2. `backend/sentinel/context/builder.py` membangun konteks: caption + transkrip ASR + teks OCR. Ringkasan **ekstraktif** (skor frekuensi kata + posisi kalimat), ekstraksi klaim heuristik, entitas, indikator persuasi, dan confidence + bukti.
3. `backend/sentinel/analysis/narrative.py` memetakan komentar ke klaim dan memberi label sikap (dukung/tolak/tanya/netral/campur) dengan keyakinan.
4. `backend/sentinel/analysis/coordination.py` hanya menghubungkan akun bila teks mirip **dan** waktunya berdekatan. Kelompok harus berupa **clique** (semua anggota saling terhubung), bukan komponen transitif. Ada uji permutasi untuk membandingkan jumlah pasangan mirip dengan baseline waktu acak. Ini memperbaiki kasus komentar yang tersebar berbulan-bulan namun dulu terbentuk menjadi satu kelompok raksasa.
5. `backend/sentinel/analysis/engine.py` menyusun skor yang bisa dijelaskan. Skor tinggi hanya jika ada clique; teks mirip tanpa clique hanya memberi poin kecil. `backend/sentinel/analysis/evidence.py` membuat dossier bukti.
6. `backend/sentinel/context/media.py`, `transcribe.py`, dan `ocr.py` menangani unduhan sementara, ASR lokal, dan OCR.
7. UI menampilkan konteks lebih dulu, meminta konfirmasi, lalu menampilkan analisis komentar. Setiap label menyertakan alasan dan contoh.
8. Bila `MAKERS_MODELS_KEY` diisi, `backend/sentinel/llm/advanced.py` mengirim ringkasan sinyal + contoh komentar ke EdgeOne Makers untuk memberi indikasi buzzer/bot per akun. Hasilnya terpisah dari skor heuristik dan tidak menimpa label.

## Analisis lanjutan LLM (opsional)
SENTINEL bisa memakai **EdgeOne Makers Models** (endpoint OpenAI-compatible) untuk menilai akun mana yang indikatif **buzzer**, **bot**, **organic**, atau **tidak jelas**. LLM hanya menganalisis sinyal yang sudah dihitung (clique, risiko, duplikasi, contoh komentar); label heuristik tetap dipakai dan LLM tidak menimpa keputusan secara diam-diam.

1. Buat API Key di [Makers Console](https://console.tencentcloud.com/edgeone/makers?tab=models&subTab=apikey).
2. Isi `backend/.env`: `MAKERS_MODELS_KEY=...` (jangan di-commit).
3. Opsional: `LLM_MODEL` (default `@makers/deepseek-v4-flash`), `LLM_BASE_URL`, `LLM_TIMEOUT`, `LLM_MAX_TOKENS` (default 6144), `LLM_MAX_ACCOUNTS`, `LLM_MAX_SAMPLES`.
4. Set `LLM_ENABLED=0` untuk mematikan. Bila kunci kosong, analisis LLM dilewati.
5. `LLM_DISABLE_THINKING=1` (default) mematikan reasoning model agar token tidak habis sebelum JSON selesai. Set `0` bila ingin memakai reasoning penuh.

Hasil LLM muncul di bagian **Analisis lanjutan (LLM)** pada dashboard, kolom tabel akun, detail akun, `/api/health`, dan dossier. Ini indikasi probabilistik, bukan tuduhan atau bukti pembayaran. Saat LLM aktif, ringkasan konteks dan contoh komentar publik (termasuk handle) dikirim ke EdgeOne; aktifkan hanya bila sesuai kebijakan privasi Anda.

## Konfigurasi `.env`
Backend (`backend/.env`): `PUBLIC_MAX_COMMENTS`, `PUBLIC_ASR`, `PUBLIC_OCR`, `PUBLIC_MAX_MEDIA_SEC`, `PUBLIC_MAX_MEDIA_MB`, `WHISPER_MODEL`, `WHISPER_LANGUAGE`, `OCR_FPS`, `OCR_MAX_FRAMES`, `OCR_LANG`, `TESSERACT_CMD`, `IG_*`, `MAKERS_MODELS_KEY`, `LLM_*`, `SENTINEL_API_TOKEN`, `CORS_ORIGINS`, `CORS_ORIGIN_REGEX`.

EdgeOne (Project Settings → Environment Variables): `SENTINEL_API_URL`, `SENTINEL_API_TOKEN`, `SENTINEL_PROXY_TIMEOUT_MS`, opsional `CORS_ORIGINS`.

## Uji
```bash
cd backend
python tests/test_public.py
python tests/test_llm.py
```

`test_public.py` menguji deteksi platform, normalisasi, konteks caption, stance, clique vs rantai transitif, dan integrasi engine. `test_llm.py` menguji parsing JSON, payload, dan integrasi LLM tanpa jaringan. Atau `python start.py --test` dari folder `backend`.

## Catatan
- Ini **bukan** API resmi dan bukan pencarian kata kunci; hanya analisis satu postingan publik lewat tautan.
- Ringkasan ekstraktif tidak memahami ironi/konteks visual. ASR/OCR bisa salah; selalu periksa bukti timestamp.
- Label sikap memakai leksikon, belum dilatih pada data berlabel. Sarkasme bisa salah.
- Skor adalah indikasi untuk ditinjau analis, bukan vonis. Tidak ada bukti pembayaran/intent dari data publik.
- Komentar yang mirip bisa berasal dari kutipan viral yang wajar. Karena itu clique + waktu + uji statistik ditampilkan, bukan hanya persentase kemiripan.
- Komentar bisa tidak lengkap (batas `PUBLIC_MAX_COMMENTS`, urutan platform). Data pengikut/umur akun sering tidak tersedia.
- Patuhi ToS platform dan UU PDP; gunakan untuk riset/kajian, bukan doxing/harassment.

## Rujukan metodologi
- Meta, Inauthentic Behavior: https://transparency.meta.com/policies/community-standards/inauthentic-behavior/
- Giglietto et al., Coordinated Link Sharing Behavior: https://dl.acm.org/doi/fullHtml/10.1145/3400806.3400817
- Magelinski, Ng, Carley, Synchronized Action Framework: https://arxiv.org/abs/2105.07454v2
- Temporal Nuances of Coordination Networks: https://arxiv.org/html/2107.02588v1
- Rauchfleisch & Kaiser, Botometer false positives: https://pmc.ncbi.nlm.nih.gov/articles/PMC7580919/
- Berkeley Protocol on Digital Open Source Investigations: https://humanrights.berkeley.edu/wp-content/uploads/2024/02/Berkeley-Protocol.pdf
- CSIS Indonesia, Cybertroops: https://www.csis.or.id/publication/cybertroops-and-public-opinion-manipulation-through-social-media-in-indonesia-cybertroops-and-public-opinion-manipulation-through-social-media-in-indonesia
