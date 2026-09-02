# FSD-USER — Sistem Akses Gedung dengan Pengenalan Wajah

> Dokumen spesifikasi fungsional versi bahasa awam.
> Status: DRAF v0.1 — fase perencanaan (belum ada yang dibangun).
> Versi teknis untuk tim: `FSD-AI.md` dan `TSD.md`.

## 1. Apa yang Sedang Kita Bangun?

Sebuah sistem yang membuka pintu gedung/kantor secara otomatis untuk orang yang **sudah terdaftar**, cukup dengan menunjukkan wajah ke kamera di pintu masuk. Orang yang tidak terdaftar tidak akan dibukakan pintu, dan setiap upaya masuk tercatat rapi.

Cara kerjanya seperti satpam digital yang sangat teliti:

1. **Pendaftaran (enrollment)** — wajah karyawan direkam sekali di awal.
2. **Belajar (training)** — komputer "belajar" mengenali wajah-wajah yang terdaftar.
3. **Penjagaan (inference)** — kamera di pintu mengenali wajah dalam waktu kurang dari sekejap dan memutuskan buka/tidak.

## 2. Bagaimana Proses Pendaftarannya?

- Admin membuat sesi pendaftaran untuk seorang karyawan.
- Karyawan menyetujui dulu (persetujuan/consent dicatat) karena data wajah adalah data pribadi yang sensitif.
- Karyawan difoto dari depan dulu (foto ini juga dipakai sistem sebagai "posisi kepala normal" orang tersebut — lihat di bawah).
- Lalu karyawan **menggerakkan KEPALA** (badan tetap menghadap kamera, tidak berputar): mulai mendongak ke arah "jam 12", lalu bergerak searah jarum jam melalui posisi kepala lain (menoleh, menunduk, dst.) sampai kembali ke posisi "jam 12". Wajah tetap terlihat kamera sepanjang proses. Tujuannya agar sistem mengenal wajah dari berbagai sudut kepala, bukan hanya dari depan.
- **Setiap kali kepala tepat berada di satu posisi jam, aplikasi otomatis memotret beberapa jepretan untuk posisi itu** — karyawan tidak perlu menekan tombol apa pun. Tidak ada video yang direkam.
- Karena setiap posisi dipotret sendiri-sendiri, **urutannya bebas** dan **satu posisi bisa diulang sendiri** tanpa harus mengulang semuanya dari awal.
- Aplikasi memandu selama proses: "wajah kurang terang", "gerakkan lebih pelan", indikator posisi jam mana yang sudah tertangkap, dan seterusnya.
- Sistem menyesuaikan diri dengan **posisi kepala normal** tiap orang. Kalau kepala seseorang secara alami sedikit menunduk atau mendongak saat santai, sistem memperhitungkannya — supaya posisi bagian bawah (jam 4–8) tidak jadi mustahil dicapai.
- Jika hasilnya kurang bagus (buram, gelap, ada posisi yang belum lengkap), sistem meminta pengulangan — cukup posisi yang bermasalah saja.
- **Semua foto langsung dikirim ke penyimpanan cloud yang aman (AWS S3)** — tidak ada yang disimpan di komputer lokal. Ini aturan mutlak.

## 3. Bagaimana Sistem Belajar?

- Setelah ada pendaftaran baru, sistem memproses hasil capture: memilih jepretan wajah terbaik dari tiap sudut kepala, lalu mengubahnya menjadi "sidik wajah" digital (angka-angka unik, bukan foto).
- Secara berkala model dilatih ulang (fine-tuning) agar makin akurat.
- Model baru hanya dipakai kalau terbukti **lebih jarang gagal mengenali orang terdaftar** dibanding model lama, dan tetap cepat. Ada persetujuan manusia sebelum model baru "naik produksi".

Ukuran keberhasilan (sesuai prioritas):
1. **Recall** — jangan sampai orang yang berhak malah ditolak. Ini prioritas utama.
2. **F1** — keseimbangan keseluruhan.
3. **Precision** — jangan sampai orang asing dianggap terdaftar.
4. **Kecepatan** — keputusan diukur dalam milidetik; target keputusan di bawah ~0,3 detik.

## 4. Apa yang Terjadi di Pintu Masuk?

1. Kamera menangkap wajah orang yang mendekat.
2. Sistem memeriksa itu wajah asli, bukan foto/HP yang disodorkan ke kamera (anti-pemalsuan).
3. Wajah dicocokkan dengan daftar orang terdaftar.
4. Cocok dan statusnya aktif → pintu terbuka. Tidak cocok → pintu tetap tertutup.
5. Semua kejadian (berhasil, ditolak, dicurigai palsu) tercatat dan bisa dipantau petugas keamanan secara langsung dari dashboard.

Jika sistem sedang gangguan, pintu **tidak** membuka otomatis (lebih aman gagal-tertutup); petugas membuka secara manual.

## 5. Siapa Memakai Apa?

| Peran | Yang bisa dilakukan |
|---|---|
| Admin | Mendaftarkan/menghapus orang, mengatur hak akses, melihat semua laporan |
| Petugas keamanan | Memantau kejadian akses secara langsung, penanganan manual |
| Karyawan terdaftar | Masuk gedung dengan wajah |
| Manajemen | Melihat laporan ringkas |

## 6. Bagaimana dengan Privasi?

- Data wajah adalah **data pribadi sensitif** (sesuai UU Perlindungan Data Pribadi). Karena itu:
  - Wajib ada persetujuan tertulis sebelum direkam.
  - Foto/video disimpan terenkripsi di cloud, aksesnya sangat dibatasi, dan **dihapus otomatis** setelah tidak diperlukan (usulan: 90 hari setelah pendaftaran berhasil).
  - Kalau karyawan keluar/menarik persetujuan, seluruh datanya (foto, video, sidik wajah) dihapus dan dia tidak bisa dikenali lagi.
  - Semua tindakan admin (mendaftarkan, menghapus, mengubah aturan) tercatat dan tidak bisa diubah-ubah.
- Sistem TIDAK menganalisis emosi, ras, atau hal lain di luar keperluan membuka pintu.

## 7. Hal yang Perlu Dikonfirmasi (asumsi kami)

1. Pendaftaran dilakukan **di kantor, didampingi admin** (bukan mandiri dari rumah). Benar?
2. ~~"Berputar 360°" artinya orangnya yang berputar badan/kepala satu putaran penuh di depan kamera.~~ **DIKOREKSI (2026-08-30):** yang bergerak adalah **orientasi KEPALA saja** (menengok/menunduk/mendongak mengikuti pola arah jam), badan tetap menghadap kamera dan wajah tetap terlihat kamera sepanjang waktu — bukan badan berputar dan bukan sampai membelakangi kamera.
3. Skala awal: sampai ± 5.000 orang terdaftar dan ± 20 pintu, satu lokasi. Benar?
4. Perangkat pintu: kamera + kunci elektrik yang bisa diperintah sistem — merek/model belum ditentukan?
5. Masa simpan foto/video mentah 90 hari setelah pendaftaran berhasil — setuju?
6. Anti-pemalsuan tahap awal berbasis perangkat lunak saja (belum pakai kamera inframerah/3D) — cukup?
7. Target: hampir tidak pernah menolak orang terdaftar (≥ 98%), dengan orang asing salah diterima maksimal 1 dari 1.000 percobaan — setuju dengan keseimbangan ini?

## 8. Yang BELUM Termasuk di Tahap Pertama

- Aplikasi mobile khusus; integrasi kartu akses/PIN sebagai cadangan; banyak gedung sekaligus; CCTV/perekaman video pengawasan; analisis apa pun selain "kenal atau tidak".
