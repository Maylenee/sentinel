# Proposal Solusi: SENTINEL

*Sistem Peringatan Dini Manipulasi Opini di Ruang Digital*

| **Kegiatan** | Kartika Cyber Hackathon |
| :--- | :--- |
| **Tema** | Deteksi Buzzer dan Bot |
| **Tim** | [nama tim] |
| **Anggota** | [nama anggota] |
| **Status** | Prototipe Python, diselaraskan dengan implementasi |

## 1. Latar Belakang

Ruang digital menjadi arena utama pembentukan opini publik.
Di balik percakapan yang tampak alami, sering terdapat akun otomatis (bot) maupun akun yang dikelola manusia secara terorganisir (buzzer) untuk menggiring narasi, menyebarkan disinformasi, atau menciptakan kesan dukungan yang semu.
Pola ini dikenal sebagai *coordinated inauthentic behavior* dan merupakan bagian dari operasi pengaruh yang dapat mengganggu kepercayaan publik.

Persoalannya, komentar tidak pernah muncul dalam ruang kosong.
Sebuah potongan video dapat dipotong, diberi caption menyesatkan, lalu komentarnya dinilai tanpa mengetahui isi pidato, teks di layar, atau konteks aslinya.
Akibatnya, analisis komentar yang hanya berbasis kemiripan teks mudah salah menuduh, terutama ketika sebuah kalimat viral dikutip secara wajar oleh banyak orang.

SENTINEL dibangun untuk menjawab masalah tersebut dengan urutan yang berbeda: **pahami konteks video terlebih dahulu, konfirmasi bersama manusia, baru bedah komentar**.
Fokusnya bukan memvonis akun sebagai bot, melainkan menemukan pola koordinasi yang dapat diaudit dan menjelaskan mengapa suatu akun patut diperiksa.

## 2. Rumusan Masalah

1. Bagaimana mengekstrak konteks postingan video publik secara cepat dan lokal, mencakup caption, ucapan, dan teks yang tampil di layar?
2. Bagaimana mengenali komentar yang bergerak terkoordinasi tanpa terjebak pada kemiripan teks yang tersebar berbulan-bulan atau kutipan viral yang wajar?
3. Bagaimana menyajikan hasil analisis agar dapat diperiksa analis non-teknis dan tidak menjadi tuduhan otomatis?
4. Bagaimana menjaga sistem tetap gratis, berjalan lokal, dan tidak bergantung pada API berbayar?

## 3. Tujuan

- Membangun dashboard yang menganalisis satu postingan publik TikTok, Instagram, atau Facebook dengan alur konteks terlebih dahulu.
- Menjalankan ASR dan OCR lokal agar konteks tidak hanya bergantung pada caption.
- Mendeteksi kelompok akun yang menulis teks mirip dalam jendela waktu pendek dengan metode clique waktu-lokal.
- Memberikan skor risiko yang dapat dijelaskan, bukan vonis, beserta dossier bukti yang dapat diunduh.
- Menyediakan jalan satu perintah untuk menjalankan sistem di komputer analis.

## 4. Solusi yang Diusulkan

SENTINEL adalah aplikasi web satu halaman dengan backend FastAPI.
Pengguna menempelkan tautan postingan publik, lalu menjalani dua langkah: **ambil konteks** dan **konfirmasi konteks untuk membedah komentar**.
Tidak ada pemantauan kata kunci, tidak ada pencarian massal, dan tidak ada klaim bahwa sistem dapat membuktikan pembayaran atau niat di balik sebuah komentar.

### 4.1 Akuisisi Konteks Video

- **Media:** sistem mengambil metadata dan komentar publik, lalu mengunduh media sementara.
  Batas default adalah 600 detik dan 80 MB; unduhan lewat `yt-dlp` dibatasi 720p.
- **ASR:** audio diekstrak dengan ffmpeg dan ditranskripsi memakai `faster-whisper` model `small` int8 di CPU.
- **OCR:** frame video dibaca memakai Tesseract bila tersedia, atau fallback **RapidOCR** berbasis ONNX yang tidak memerlukan binary eksternal.
  OCR default berjalan 0,5 frame/detik dengan maksimal 60 frame (`OCR_FPS`, `OCR_MAX_FRAMES`).
- **Kontrol:** ASR dapat dimatikan lewat `PUBLIC_ASR`, OCR lewat `PUBLIC_OCR`.
  Bila ASR/OCR tidak tersedia atau dimatikan, analisis tetap berjalan memakai caption dan menampilkan catatan keterbatasan.
- **Pembersihan:** media dihapus setelah diproses.

### 4.2 Ringkasan, Klaim, dan Bukti

- **Sumber konteks:** caption, transkrip, dan teks layar.
- **Ringkasan:** caption dan transkrip diprioritaskan; teks OCR tetap disimpan sebagai bukti dan menjadi sumber ringkasan bila transkrip tidak tersedia.
- **Sifat ringkasan:** ekstraktif, yaitu kalimat dipilih dari sumber, bukan dibuat ulang oleh model generatif.
- **Klaim:** sistem menandai hingga 10 klaim, entitas, kata kunci, dan indikator persuasi.
- **Indikator persuasi:** emosional, urgensi, absolut, kambing hitam, seruan aksi, dan sumber.
- **Bukti:** setiap butir menyertakan sumber dan timestamp agar dapat dicek.

### 4.3 Konfirmasi Manusia

- Analis melihat pratinjau postingan, ringkasan, klaim, transkrip, teks OCR, dan caption.
- Ringkasan dapat diedit sebelum analisis komentar dijalankan.
- Langkah ini penting agar kesalahan ASR/OCR tidak langsung memengaruhi penilaian.

### 4.4 Analisis Komentar

- **Normalisasi:** bahasa gaul dan singkatan dipetakan ke bentuk baku.
- **Kemiripan:** teks dipecah menjadi shingle tiga kata, lalu dibandingkan memakai Jaccard.
- **Sikap:** komentar dipetakan ke klaim dan diberi label dukung, tolak, tanya, netral, atau campur.
- **Negasi:** pola sederhana seperti “tidak setuju” ikut diperhitungkan.
- **Batasan:** label memakai leksikon, bukan model terlatih, sehingga sarkasme masih bisa salah.

### 4.5 Deteksi Koordinasi Waktu-Lokal

- **Edge:** dua akun hanya dihubungkan bila teksnya mirip **dan** waktu komentarnya berdekatan.
- **Clique:** kelompok harus berupa clique, yaitu minimal tiga akun yang semuanya saling terhubung, bukan komponen transitif.
- **Filter:** komentar pendek seperti “sepakat” atau “setuju” tidak dijadikan bukti karena terlalu generik.
- **Uji permutasi:** jumlah pasangan mirip dibandingkan dengan baseline waktu acak.
- **Nilai p:** ditampilkan sebagai bahan pertimbangan, bukan bukti final.

### 4.6 Skor Risiko yang Dapat Dijelaskan

- **Sinyal:** frekuensi posting, keseragaman jeda, usia akun, rasio mengikuti/pengikut, pengulangan teks sendiri, dan keanggotaan clique.
- **Skor:** sinyal dijumlahkan, dibandingkan dengan ambang 2,5, lalu dipetakan ke risiko rendah, sedang, atau tinggi.
- **Clique:** akun hanya berisiko tinggi bila ada clique; teks mirip tanpa clique hanya menambah poin kecil.
- **Penjelasan:** setiap akun menampilkan rincian poin dan alasannya.
- **Catatan:** satu akun komentator sering hanya muncul sekali, sehingga sinyal frekuensi dan jeda tidak banyak berbicara.
  Pada mode ini skor terutama ditentukan clique dan kemiripan teks, sedangkan usia/pengikut hanya dipakai bila datanya tersedia.

### 4.7 Dossier dan Tampilan

- **Dossier JSON:** berisi provenance, konteks, sinyal komentar, clique, dan daftar batasan.
- **Tampilan:** contoh komentar, tautan asli, rentang waktu, nilai p, dan grafik akun/clique.
- **Prinsip:** semua angka adalah indikasi untuk ditinjau manusia.

## 5. Fitur Utama Dashboard

- **Input satu tautan publik** TikTok, Instagram, atau Facebook, dengan progres job yang diperbarui lewat polling.
- **Konteks lebih dulu:** pratinjau media, durasi, confidence, status transkrip/OCR, ringkasan yang dapat diedit, klaim, dan indikator persuasi.
- **Bukti konteks:** caption, transkrip dengan timestamp, dan teks OCR dengan timestamp.
- **Analisis komentar:** jumlah komentar teks, akun komentator, persentase kemiripan, rentang waktu, sikap, dan klaim yang paling banyak diamplifikasi.
- **Clique waktu-lokal:** ukuran kelompok, rentang waktu, jumlah edge, nilai p, anggota, dan contoh komentar.
- **Akun berisiko:** tabel akun, rincian poin per sinyal, alasan, dan grafik akun/clique sederhana.
- **Dossier bukti JSON:** dapat diunduh untuk dokumentasi atau peninjauan lanjutan.
- **Mode cepat:** endpoint caption-only untuk analisis tanpa mengunduh media, dengan keterbatasan yang dinyatakan.
- **Satu perintah:** `python start.py` menyiapkan virtualenv, dependensi, `.env`, lalu menjalankan dashboard di `http://127.0.0.1:8787`.

## 6. Arsitektur dan Teknologi

### 6.1 Alur Sistem

```text
Browser (HTML/CSS/JS)
   │
   ▼
FastAPI (app.py)
   ├── sentinel/sources/public.py   → metadata + komentar publik
   ├── sentinel/context/builder.py  → caption + ASR + OCR + ringkasan
   │   ├── sentinel/context/media.py       → unduh media, audio, frame
   │   ├── sentinel/context/transcribe.py  → faster-whisper lokal
   │   └── sentinel/context/ocr.py         → Tesseract / RapidOCR
   └── sentinel/analysis/engine.py  → fitur akun + skor risiko
       ├── sentinel/analysis/coordination.py → clique waktu-lokal
       ├── sentinel/analysis/narrative.py    → sikap + amplifikasi klaim
       └── sentinel/analysis/evidence.py     → dossier bukti
```

### 6.2 Tumpukan Teknologi

| **Lapisan** | **Implementasi saat ini** | **Rencana pengembangan** |
| :--- | :--- | :--- |
| Pengumpulan data | Adapter publik TikTok, Instagram, Facebook | API resmi/berlisensi, platform tambahan |
| Konteks video | Caption, `faster-whisper` lokal, OCR lokal, ffmpeg | Peningkatan kualitas ASR/OCR dan deteksi adegan |
| Pemrosesan teks | Normalisasi slang, shingle tiga kata, Jaccard | IndoBERT/sentence-transformers |
| Deteksi koordinasi | Clique waktu-lokal, filter komentar generik, uji permutasi | Graf berbobot, HDBSCAN, GNN |
| Skor risiko | Model linear heuristik + sigmoid | Model terlatih dan kalibrasi |
| Penjelasan | Rincian poin per sinyal, dossier bukti | SHAP untuk model non-linear |
| Backend | FastAPI + Uvicorn, job di memori | PostgreSQL, antrean job, autentikasi |
| Frontend | HTML/CSS/JavaScript, polling job, canvas | React, SSE/WebSocket, visualisasi lebih kaya |
| Penyebaran | `start.py` lokal, virtualenv | Docker/VPS, orkestrasi dan pemantauan |

### 6.3 API Utama

| **Endpoint** | **Fungsi** |
| :--- | :--- |
| `POST /api/context` | Membuat job konteks dari `{url, media}` |
| `GET /api/job/{id}` | Memantau status, progres, dan hasil konteks |
| `POST /api/analyze` | Menganalisis komentar dari job yang sudah selesai |
| `POST /api/post` | Mode cepat caption-only tanpa unduh media |
| `GET /api/health` | Status sumber publik, ASR, OCR, dan ffmpeg |

### 6.4 Penyimpanan, Cache, dan Runtime

- **Job:** disimpan di memori dan kedaluwarsa setelah 2 jam.
- **Cache konteks:** disimpan di `.cache/context` selama 7 hari agar pengujian ulang tidak mengulang ASR/OCR; konteks yang gagal ASR tidak di-cache.
- **Media:** disimpan sementara di `.cache/media` dan dihapus setelah diproses.
- **Model Whisper:** diunduh sekali dan disimpan di `.cache/whisper`.
- **Database:** belum digunakan pada prototipe ini.
- **Runtime:** Python 3.9 atau lebih baru.
- **Dependensi inti:** FastAPI, Uvicorn, HTTPX.
- **Dependensi opsional:** `yt-dlp`, `curl_cffi`, `instaloader`, `facebook-scraper`, `faster-whisper`, `av==16.1.0`, `imageio-ffmpeg`, `rapidocr`, `onnxruntime`, `pytesseract`, dan Pillow.

## 7. Sumber Data dan Keterbatasan Platform

Sumber data prototipe hanya konten yang tampil publik.
Tidak ada API key berbayar.
Sesi Instagram bersifat opsional dan hanya dipakai untuk membaca konten/komentar, bukan untuk mengubah apa pun.
Deteksi bot secara langsung dibatasi karena metadata akun sering tidak tersedia; fokus utama sistem adalah pola koordinasi yang dapat diaudit.

| **Platform** | **Pustaka/metode** | **Yang diambil** | **Keterbatasan** |
| :--- | :--- | :--- | :--- |
| TikTok | `yt-dlp` + `curl_cffi` untuk endpoint komentar web | Metadata, caption, media, komentar publik | Rate limit, tantangan TLS, komentar bisa tidak lengkap |
| Instagram | `instaloader` | Postingan, media, komentar | Akses anonim sering ditolak; sesi opsional hanya untuk komentar |
| Facebook | `facebook-scraper` | Postingan publik dan komentar | Struktur halaman berubah, grup tertutup tidak didukung |

- **Batas komentar:** default 200 per postingan (`PUBLIC_MAX_COMMENTS`).
- **Profil akun:** usia, jumlah pengikut, atau jumlah mengikuti sering tidak tersedia; sistem memberi catatan dan tidak memaksakan sinyal tersebut.
- **Belum termasuk:** Bluesky, Mastodon, YouTube, X, dan webhook Meta masih berupa rencana, bukan fitur yang sudah ada.

## 8. Keunggulan dan Pembeda

1. **Konteks sebelum komentar.** Caption, transkrip, dan teks layar dipakai lebih dulu, sehingga komentar tidak dinilai dalam ruang kosong.
2. **Clique waktu-lokal, bukan komponen transitif.** Ini mencegah kasus lama ketika komentar yang tersebar berbulan-bulan tergabung menjadi satu kelompok raksasa.
3. **Kontrol false positive berlapis.** Komentar pendek/generik disaring, kelompok minimal tiga akun, semua anggota harus saling terhubung, ada batas rentang waktu, dan ada uji permutasi.
4. **Dapat diaudit.** Setiap skor memiliki rincian poin, alasan, contoh komentar, timestamp, dan dossier JSON.
5. **Bukan vonis.** Output berupa indikasi risiko; keputusan akhir tetap pada analis manusia.
6. **Lokal, gratis, dan terbuka.** ASR/OCR berjalan lokal, tidak memerlukan API berbayar, dan dapat dijalankan dengan satu perintah.
7. **Human-in-the-loop.** Ringkasan konteks dapat diperiksa dan diedit sebelum analisis komentar dijalankan.

## 9. Metodologi dan Validasi

### 9.1 Metode Saat Ini

- **Normalisasi teks:** pemetaan singkatan dan bahasa gaul, penghapusan URL/mention, shingle tiga kata.
- **Kemiripan teks:** Jaccard, ambang 0,6 untuk edge koordinasi dan 0,7 untuk indikator komentar mirip di ringkasan.
- **Koordinasi:** jendela pasangan 24 jam, rentang clique maksimal 6 jam, minimal 3 akun, uji permutasi 120 kali.
- **Skor risiko:** penjumlahan poin heuristik, ambang 2,5, sigmoid, batas tinggi ≥0,70 dan sedang ≥0,40.
- **Sikap komentar:** leksikon dukung/tolak/tanya/netral/campur dengan penanganan negasi sederhana.
- **Confidence konteks:** 0,30 untuk caption saja, 0,72 dengan ASR, 0,88 dengan ASR + OCR, maksimal 0,95.
  Nilai ini adalah keyakinan internal, bukan akurasi.

### 9.2 Pengujian yang Sudah Dilakukan

- `tests/test_public.py` menguji deteksi platform, normalisasi metadata/komentar TikTok, ringkasan/explain, ekstraksi klaim konteks, stance, OCR, Instagram, Facebook, dispatch, dan alur API.
- Uji koordinasi mencakup clique waktu-lokal, rantai transitif yang tidak boleh menjadi clique, komentar pendek yang harus diabaikan, dan uji permutasi.
- Uji end-to-end pada postingan TikTok publik: konteks dengan ASR + OCR berhasil, confidence 0,88, dan dossier terbentuk.
  Kasus kontrol pada tautan lain tidak menghasilkan clique.
- Pada beberapa tautan uji, sistem menghasilkan **0 clique** setelah filter komentar generik dan clique waktu-lokal.
  Ini bukan bukti bahwa tidak ada koordinasi; artinya tidak ada clique yang lolos kriteria pada sampel komentar yang tersedia.
- Studi kasus internal: komentar yang tersebar lintas waktu pernah terbaca sebagai satu kelompok besar akibat rantai transitif.
  Setelah diganti clique waktu-lokal, kelompok tersebut tidak lolos.
  Perubahan ini adalah contoh kontrol false positive, bukan bukti bahwa tidak ada koordinasi.

### 9.3 Evaluasi Berikutnya

- Pelabelan manual data nyata berbahasa Indonesia, termasuk contoh negatif dan kasus sarkasme.
- Pengukuran precision, recall, dan F1 untuk clique serta false positive rate.
- Kalibrasi skor risiko dan analisis kesalahan per platform.
- Uji ketahanan terhadap komentar parsial, tautan yang dihapus, dan perubahan struktur platform.

## 10. Etika, Privasi, dan Keamanan

### 10.1 Prinsip Penggunaan

- Hanya memakai data publik atau data yang memang dapat diakses tanpa melanggar privasi.
- Penggunaan harus mengikuti ketentuan layanan platform dan UU PDP.
- Tidak ada fitur doxing, pembukaan data privat, atau penyerangan akun.
- Output adalah indikasi untuk riset/kajian, bukan tuduhan.
- Sistem tidak boleh dipakai untuk mengotomatiskan penghukuman, pelaporan massal, atau penargetan individu.

### 10.2 Data dan Penyimpanan

- Media diunduh ke folder sementara dan dihapus setelah ASR/OCR.
- Cache konteks berisi teks/ringkasan selama 7 hari dan dapat dihapus manual dari `.cache/context`.
- Job berisi komentar mentah hanya di memori dan kedaluwarsa setelah 2 jam.
- Data tidak disebarkan oleh sistem.
- Sesi Instagram bersifat opsional, disimpan lokal, dan sebaiknya bukan akun utama.

### 10.3 Keamanan dan Keterbukaan

- Dashboard secara default hanya mendengarkan di `127.0.0.1`.
- Tidak ada login pengguna pada prototipe.
- Tidak ada API key berbayar.
- Keterbatasan ASR/OCR, heuristik stance, dan ketiadaan bukti pembayaran/intent dinyatakan terbuka di dashboard dan dossier.

## 11. Rencana Pelaksanaan

| **Tahap** | **Kegiatan** | **Keadaan saat ini** |
| :--- | :--- | :--- |
| 1. Fondasi | Sumber publik, normalisasi teks, engine skor, dashboard dasar | Selesai pada prototipe |
| 2. Konteks | Caption, ASR lokal, OCR lokal, ringkasan ekstraktif, klaim, bukti | Selesai pada prototipe |
| 3. Koordinasi | Clique waktu-lokal, filter komentar generik, uji permutasi | Selesai pada prototipe |
| 4. Narasi dan bukti | Stance, amplifikasi klaim, dossier JSON, UI dua langkah | Selesai pada prototipe |
| 5. Validasi | Pelabelan data nyata, precision/recall, kalibrasi, analisis error | Berikutnya |
| 6. Produksi | Autentikasi, database, antrean job, Docker, API resmi | Rencana lanjutan |

Jadwal rinci akan disesuaikan dengan durasi hackathon dan jumlah anggota tim.

## 12. Dampak yang Diharapkan

- Analis dapat memahami konteks video lebih cepat sebelum menilai komentar.
- Pola koordinasi yang lolos filter waktu dan clique lebih mudah dibedakan dari kemiripan teks biasa.
- Keputusan dapat dipertanggungjawabkan karena setiap sinyal memiliki alasan dan bukti.
- Masyarakat memperoleh gambaran bahwa skor risiko bukan vonis, sehingga literasi media ikut meningkat.
- Sistem dapat menjadi dasar pengembangan alat peringatan dini yang lebih besar tanpa mengorbankan transparansi.

## 13. Risiko dan Mitigasi

| **Risiko** | **Mitigasi** |
| :--- | :--- |
| Platform membatasi atau mengubah akses | Adapter terpisah, pesan error yang jelas, fallback metadata, dan pengujian berkala |
| Komentar yang diambil tidak lengkap | Menampilkan jumlah sampel dan batas `PUBLIC_MAX_COMMENTS`; tidak menyimpulkan di luar sampel |
| Data profil akun tidak tersedia | Sinyal usia/pengikut tidak dipaksakan; catatan ditampilkan pada penjelasan akun |
| False positive pada akun asli | Clique minimal 3 akun, filter komentar generik, batas waktu, uji permutasi, dan peninjauan manusia |
| ASR/OCR salah | Ringkasan dapat diedit, bukti timestamp ditampilkan, confidence dan catatan keterbatasan disertakan |
| Keterbatasan resource CPU | Model `small` int8, batas durasi/media/frame, dan opsi mematikan ASR/OCR |
| Cache berisi teks konteks | TTL 7 hari, lokasi lokal, dapat dihapus manual; media mentah tidak disimpan |
| Bias leksikon dan sarkasme | Label diberi confidence dan contoh; validasi berlabel direncanakan |
| Perubahan dependensi pihak ketiga | Pin versi kritis seperti `av==16.1.0` dan uji integrasi |

## 14. Penutup

SENTINEL bukan pendeteksi bot yang memvonis secara otomatis.
Ia adalah sistem peringatan dini yang membantu manusia memahami konteks sebuah postingan, memeriksa pola koordinasi komentar, dan menelusuri bukti di balik setiap sinyal.
Dengan pendekatan konteks terlebih dahulu, clique waktu-lokal, dan dossier yang dapat diaudit, SENTINEL berupaya mengurangi salah tuduh sekaligus memperkuat ketahanan informasi di ruang digital.

## 15. Rujukan

- Meta, Inauthentic Behavior: https://transparency.meta.com/policies/community-standards/inauthentic-behavior/
- Giglietto et al., Coordinated Link Sharing Behavior: https://dl.acm.org/doi/fullHtml/10.1145/3400806.3400817
- Magelinski, Ng, Carley, Synchronized Action Framework: https://arxiv.org/abs/2105.07454v2
- Temporal Nuances of Coordination Networks: https://arxiv.org/html/2107.02588v1
- Rauchfleisch & Kaiser, Botometer false positives: https://pmc.ncbi.nlm.nih.gov/articles/PMC7580919/
- Berkeley Protocol on Digital Open Source Investigations: https://humanrights.berkeley.edu/wp-content/uploads/2024/02/Berkeley-Protocol.pdf
- CSIS Indonesia, Cybertroops: https://www.csis.or.id/publication/cybertroops-and-public-opinion-manipulation-through-social-media-in-indonesia-cybertroops-and-public-opinion-manipulation-through-social-media-in-indonesia
