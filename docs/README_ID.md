[EN](../README.md) | [FA](README_FA.md) | [RU](README_RU.md) | [CN](README_CN.md) | [ID](README_ID.md) | [KO](README_KO.md)

## Brok 🤖 — Pendamping AI desktop & agen pemrograman (mengutamakan bahasa Persia)

<img src="brok.gif" width="140" alt="Brok"/>

Brok adalah robot kecil yang tinggal di desktop Anda (tanpa bingkai, selalu di atas, bisa diseret). Ia berbicara terutama dalam **bahasa Persia** (dan bahasa lain) serta dapat bekerja sebagai **agen pemrograman dengan kontrol izin** di proyek Anda. Berbasis [myCat](https://github.com/yumiaura/myCat) — lihat NOTICE dan LICENSE.txt.

- Avatar robot dengan 13 status (diam, mendengarkan, berpikir, mengetik, coding, berbicara, senang, bingung, error, sukses, tidur, notifikasi…)
- Chat dengan **Claude**, **Ollama (lokal)**, atau API kompatibel OpenAI; label LOCAL AI / CLOUD AI selalu terlihat
- **Ruang kerja coding** (klik kanan → Coding Workspace…): file, editor, chat, penampil diff, terminal, masalah, git. Pilih kode lalu: jelaskan / cari bug / optimalkan / tulis tes / konversi ke Flutter
- **Keamanan:** setiap alat punya tingkat risiko; perubahan file menampilkan diff dulu; hapus, commit, push, dan perintah berisiko selalu meminta konfirmasi; perintah berbahaya diblokir; ada batas langkah, waktu, token, dan panggilan alat
- Antarmuka Persia dan RTL, mode belajar, debugger AI, laporan kesehatan proyek, memori yang Anda kendalikan (`/remember`, `/memory`, `/forget`), mode lokal-saja, hotkey global (default Ctrl+Space), lampiran gambar/tangkapan layar

### Instalasi (Python ≥ 3.10)
```bash
pip install .
brok                              # desktop
export ANTHROPIC_API_KEY=...      # Claude (optional) / Ollama: ollama pull llama3.1
brok-agent doctor
brok-agent --project . ask "..."
```
Detail: docs/configuration.md · docs/security.md · docs/coding-agent.md

> Status jujur: inti aplikasi diuji otomatis (Python 3.8 dan 3.12, Linux, tanpa layar). Belum diverifikasi penulis: panggilan nyata ke Claude/OpenAI/GitHub dengan kunci asli, build Windows/macOS, pengenalan suara dari mikrofon.
