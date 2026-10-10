# Assoodiq — Halol hisob

Assoodiq'ning kurslari, klublari va kundalik moliyasini Google Sheets o'rniga yuritish uchun
dastur. Islom moliyasi qoidalari (zakot, tozalash, qarz daftari, aqd turlari) tizimning
ichiga qurilgan.

![Bosh sahifa](docs/screens/desk-light-home.jpg)

## Nima qila oladi

| Bo'lim | Vazifasi |
|---|---|
| **Bosh sahifa** | Umumiy balans, oy kirim/chiqim/sof foyda (o'tgan oyga nisbatan), 12 oylik grafik, hisoblar, zakot holati, undiriladigan summalar, diqqat talab qiladigan ishlar |
| **Kassa** | Hamma pul harakati bitta daftarda: kirim, chiqim, hisoblar orasidagi o'tkazma. Oy, tur, hisob va matn bo'yicha filtr. «Saqlash va yana» bilan ketma-ket kiritish |
| **Kurs va klublar** | Har bir potok/klub/tadbir bo'yicha: a'zolar soni, kutilgan va yig'ilgan summa, xarajat, sof foyda, rentabellik, 1 a'zoni jalb qilish narxi |
| **A'zolar** | O'quvchi va klub a'zolari, kim qancha to'lagan va qancha qarz. Klub obunasini bir tugma bilan uzaytirish, muddati tugayotganlar ro'yxati |
| **Zakot** | Naqd, undiriladigan haqlar, tovar zaxirasi va qarzlar daftardan avtomatik yig'iladi. Nisob oltin (85 g) yoki kumush (595 g) bo'yicha. Havl sanasi hijriy taqvimda, hisob-kitoblar tarixi saqlanadi |
| **Halollik va sadaqa** | Shubhali yoki nohalol tushumlar «tozalash fondi»ga ajratiladi va foydaga qo'shilmaydi. Sof foydadan sadaqa rejasi. Daromadning aqd turlari bo'yicha taqsimoti |
| **Qarz daftari** | Baqara 282 asosida: berilgan va olingan qarzlar, muddat, guvoh, qisman qaytarish. Qarzga foiz qo'shilmaydi, qarz foyda-zararga kirmaydi |
| **Hisobotlar** | Yillik foyda-zarar jadvali (guruh × oy), Excel'ga eksport, dasturlar iqtisodiyoti |
| **Sozlamalar** | Dollar kursi, oltin/kumush narxi, hisoblar, kategoriyalar, xodimlar va ularning 6 xonali kirish kodlari |

**Rollar:** *rahbar* hamma bo'limni ko'radi va xodim qo'sha oladi. *Buxgalter* xodimlar
boshqaruvidan tashqari hamma narsani ko'radi. *Menejer* faqat dasturlar, a'zolar va kirim
bilan ishlaydi: chiqim yoza olmaydi va yozuvni o'chira olmaydi.

## Ishga tushirish

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py --demo        # bo'sh baza + 12 oylik namuna ma'lumot
python app.py                # http://localhost:5070
```

Haqiqiy ish uchun namunasiz boshlang: `python seed.py`. Bu buyruq faqat hisoblar,
kategoriyalar va xodimlarni yaratadi.

**Boshlang'ich kirish kodlari** (birinchi kirishdan keyin Sozlamalar → Xodimlar orqali
almashtiring):

| Rol | Kod |
|---|---|
| Rahbar | `100100` |
| Buxgalter | `200200` |
| Menejer | `300300` |

**Testlar:** `python -m pytest -q`

**Bulutga joylash** (Railway yoki VPS): `Procfile` tayyor. `DATABASE_URL` (PostgreSQL) va
`SECRET_KEY` muhit o'zgaruvchilarini bering, `.env.example` faylida namunasi bor.

## Tuzilishi

```
app.py              Flask ilova, filtrlar (pul formati, hijriy sana), rollar bo'yicha kirish
config.py           Sozlama (SQLite yoki DATABASE_URL)
seed.py             Boshlang'ich kategoriyalar va namuna ma'lumot
core/
  models.py         Ma'lumotlar modeli (Transaction — yagona daftar)
  finance.py        Barcha hisob-kitob: balans, foyda-zarar, dastur iqtisodiyoti, zakot, fondlar
  hijri.py          Hijriy taqvim (jadval usuli) va havl sanasi
views/              Bo'limlar: kassa, dastur, qarz, islomiy, hisobot, sozlama, auth
templates/          Jinja shablonlari; partials/ui.html — umumiy bo'laklar (ikonka, grafik, oynalar)
static/             CSS (yorug'/qorong'i mavzu tokenlari), JS, logotip va naqsh
tests/              pytest
```

**Asosiy tamoyil:** har bir pul harakati bitta `Transaction` daftariga yoziladi. Balans,
foyda-zarar, kurs foydasi, qarz qoldig'i, zakot va tozalash fondi shu daftardan hisoblanadi,
hech bir raqam ikki joyda qo'lda yozilmaydi. Dollardagi yozuv o'sha kungi kurs bo'yicha
so'mdagi qiymati bilan saqlanadi, shuning uchun kurs o'zgarsa ham o'tgan oylar hisoboti
o'zgarmaydi.

## Shariat bo'yicha qabul qilingan qoidalar (tasdiqlash kerak)

Quyidagi qoidalar Hanafiy mazhabidagi tijorat zakoti uslubiga asoslangan. Ishga
tushirishdan oldin Assoodiq'ning shariat maslahatchisi bilan ko'rib chiqing:

1. Zakot = (naqd + undiriladigan haqlar + tovar zaxirasi + boshqa tijorat aktivlari − muddati kelgan qarzlar) × 2,5%. Bu qiymat nisobdan kam bo'lmasa va havl to'lgan bo'lsa hisoblanadi.
2. O'quvchilarning to'lanmagan kurs pullari «kuchli qarz» (dayn qaviy) sifatida undiriladigan haqlarga qo'shiladi. Zakot sahifasida qo'lda o'zgartirish mumkin.
3. Tozalash fondidagi pul egasiniki hisoblanmaydi va zakot hisobida naqd puldan ayiriladi.
4. Nisob boshlang'ich holatda oltin (85 g) bo'yicha, Sozlamalarda kumushga o'tkazish mumkin.
5. Hijriy sana jadval usulida hisoblanadi va rasmiy e'londan 1–2 kun farq qilishi mumkin.

## Keyingi bosqichlar

- **Google Sheets'dan import.** Jadval tuzilishi ma'lum bo'lgach, eski yozuvlarni bir martada
  ko'chirish va o'tish davrida sinxron ishlash.
- **Telegram bot.** Chiqimni tez kiritish, kunlik hisobot, qarzdorlarga va obunasi tugayotganlarga eslatma.
- **Sheriklik hisobi.** Mushoraka va mudoraba asosida ta'sischilar o'rtasida foydani taqsimlash
  (sheriklar soni va nisbatlari aniqlangach).
- **To'lov tizimlari.** Payme/Click to'lovlarini avtomatik qabul qilish.
- **Brend.** Logotip va ranglar hozircha vaqtinchalik (sakkiz qirrali yulduz, zumrad va oltin).
  Assoodiq'ning rasmiy brendbuki bilan almashtiriladi.

## Ko'rinishlar

| | |
|---|---|
| ![Kirish](docs/screens/desk-light-login.jpg) | ![Zakot](docs/screens/desk-light-zakot.jpg) |
| ![Dasturlar](docs/screens/desk-light-dasturlar.jpg) | ![Halollik](docs/screens/desk-light-halollik.jpg) |
| ![Kirim oynasi](docs/screens/desk-modal-kirim.jpg) | ![Qorong'i mavzu](docs/screens/desk-dark-home.jpg) |
| ![Mobil](docs/screens/mob-light-home.jpg) | ![Mobil oyna](docs/screens/mob-modal-kirim.jpg) |
