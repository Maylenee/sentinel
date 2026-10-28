# SENTINEL (Python)

Analisis postingan **publik** Facebook, Instagram, dan TikTok dengan alur **konteks video dulu, baru bedah komentar**. Backend FastAPI, dashboard web satu halaman.

## Jalankan (satu perintah)
Butuh Python 3.9 atau lebih baru.

- Windows: `py start.py` atau `python start.py`
- Mac/Linux: `python3 start.py`

`start.py` otomatis membuat `.venv`, memasang dependensi inti, mencoba pustaka opsional (best-effort), menyiapkan `.env`, lalu menjalankan dashboard. Opsi: `--no-install`, `--no-venv`, `--no-optional`, `--no-browser`, `--host`, `--port`, `--test`.

Browser terbuka di http://127.0.0.1:8787. Bila port dipakai, `start.py` berhenti dengan peringatan; hentikan instance lama atau pakai `--port 8788`.

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
sentinel/
  analysis/   engine, coordination, narrative, evidence
  context/    builder, media, transcribe, ocr
  sources/    adapter publik TikTok/Instagram/Facebook
app.py        FastAPI + job context/analyze
start.py      pembuat .venv, installer, launcher
static/       dashboard satu halaman
tests/        uji regresi dan integrasi
```

## Cara kerja
1. `sentinel/sources/public.py` menormalkan metadata + komentar. Metadata mencakup caption penuh, hashtag/mention, durasi, statistik, waktu posting, dan URL media.
2. `sentinel/context/builder.py` membangun konteks: caption + transkrip ASR + teks OCR. Ringkasan **ekstraktif** (skor frekuensi kata + posisi kalimat), ekstraksi klaim heuristik, entitas, indikator persuasi, dan confidence + bukti.
3. `sentinel/analysis/narrative.py` memetakan komentar ke klaim dan memberi label sikap (dukung/tolak/tanya/netral/campur) dengan keyakinan.
4. `sentinel/analysis/coordination.py` hanya menghubungkan akun bila teks mirip **dan** waktunya berdekatan. Kelompok harus berupa **clique** (semua anggota saling terhubung), bukan komponen transitif. Ada uji permutasi untuk membandingkan jumlah pasangan mirip dengan baseline waktu acak. Ini memperbaiki kasus komentar yang tersebar berbulan-bulan namun dulu terbentuk menjadi satu kelompok raksasa.
5. `sentinel/analysis/engine.py` menyusun skor yang bisa dijelaskan. Skor tinggi hanya jika ada clique; teks mirip tanpa clique hanya memberi poin kecil. `sentinel/analysis/evidence.py` membuat dossier bukti.
6. `sentinel/context/media.py`, `transcribe.py`, dan `ocr.py` menangani unduhan sementara, ASR lokal, dan OCR.
7. UI menampilkan konteks lebih dulu, meminta konfirmasi, lalu menampilkan analisis komentar. Setiap label menyertakan alasan dan contoh.

## Konfigurasi `.env`
`PUBLIC_MAX_COMMENTS`, `PUBLIC_ASR`, `PUBLIC_OCR`, `PUBLIC_MAX_MEDIA_SEC`, `PUBLIC_MAX_MEDIA_MB`, `WHISPER_MODEL`, `WHISPER_LANGUAGE`, `OCR_FPS`, `OCR_MAX_FRAMES`, `OCR_LANG`, `TESSERACT_CMD`, `IG_*`.

## Uji
`python tests/test_public.py` menguji deteksi platform, normalisasi, konteks caption, stance, clique vs rantai transitif, dan integrasi engine. Atau `python start.py --test`.

## Catatan jujur
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
