"""Namuna bilimlar bazasi (test rejimi uchun). Ustoz ko'rib chiqib, o'z qoidalari bilan almashtirishi kerak."""

SRC = "Namuna material — ustoz tasdiqlashi kerak"

DOCS = [
    ("qoida", "qarz", "Qarz ustiga shart qilingan har qanday qo'shimcha — ribo",
     "Qarz (qard) berishda qaytarishda asl summadan ortiq to'lash shart qilinsa — u ribo hisoblanadi: foiz, "
     "«xizmat haqi» nomi ostidagi ustama, kunlik/oylik foiz, qarz evaziga sovg'a yoki imtiyoz va h.k.\n\n"
     "Ruxsat etiladi: qarz aynan o'sha miqdorda qaytariladi; hujjat tayyorlashning haqiqiy xarajati alohida "
     "va qarz miqdoriga bog'lanmagan holda olinishi mumkin. Qarzdor o'z ixtiyori bilan, shartsiz ortiqcha "
     "qaytarsa — joiz.\n\nTo'g'ri band namunasi: «Qarz oluvchi qarz summasini ___ sanagacha to'liq "
     "qaytaradi. Qarz summasiga hech qanday foiz yoki qo'shimcha to'lov hisoblanmaydi.»"),
    ("qoida", "umumiy", "Kechikish uchun kreditor foydasiga jarima — joiz emas",
     "To'lov kechiktirilganda sotuvchi yoki kreditor foydasiga har kunlik foiz yoki pul jarimasi olish ribo "
     "hisoblanadi: bu qarzga vaqt evaziga qo'shimcha demakdir.\n\nRuxsat etilgan yo'l: qarzdor kechiktirsa, "
     "oldindan kelishilgan summani xayriyaga berish majburiyatini oladi; bu pul markaz yoki sotuvchi "
     "daromadiga kirmaydi, alohida hisobda saqlanib xayriyaga sarflanadi. Undirish bilan bog'liq haqiqiy "
     "xarajatlar (masalan, sud xarajati) alohida qoplanishi mumkin.\n\nTo'g'ri band namunasi: «Xaridor to'lovni "
     "kechiktirsa, kechiktirilgan har bir kun uchun to'lanmagan summaning ___% miqdorida mablag'ni "
     "xayriyaga yo'naltirish majburiyatini oladi. Bu mablag' Sotuvchining daromadi hisoblanmaydi.»"),
    ("qoida", "murobaha", "Murobaha: sotuvchi tovarga avval egalik qilishi shart",
     "Murobahada sotuvchi tovarni xaridorga sotishdan oldin uni o'z mulkiga olishi (haqiqiy yoki hukmiy "
     "qabz) va shu davrdagi xavfni (tovar yo'qolishi, buzilishi) o'z zimmasiga olishi shart. Sotuvchida hali "
     "bo'lmagan tovarni sotish shartnomasi tuzish joiz emas — bunda faqat va'da (va'd) berilishi mumkin.\n\n"
     "Tannarx va ustama xaridorga oshkor qilinadi. Shartnomadagi narx qat'iy: keyin muddat uzaygani yoki "
     "kechikish uchun narx oshirilmaydi."),
    ("namuna", "murobaha", "Murobaha shartnomasi: to'g'ri bandlar namunasi",
     "1. «Sotuvchi Tovarni ___ sanada o'z mulkiga olgan va u Sotuvchining omborida/hisobida turibdi.»\n"
     "2. «Tovarning tannarxi ___ so'm, Sotuvchining ustamasi ___ so'm, sotish narxi ___ so'm. Narx shartnoma "
     "amal qilgan butun muddat davomida o'zgarmaydi.»\n"
     "3. «Xaridor narxni ___ oy davomida jadval bo'yicha bo'lib to'laydi. Muddatidan oldin to'lansa, Sotuvchi "
     "o'z ixtiyori bilan chegirma berishi mumkin (shart emas).»\n"
     "4. Kechikish uchun — xayriya majburiyati bandi (alohida qoidaga qarang)."),
    ("qoida", "savdo", "G'arar: tovar, narx va muddat aniq bo'lishi kerak",
     "Shartnomada sotilayotgan narsa (tavsifi, miqdori, sifati), narxi va to'lov/yetkazib berish muddati aniq "
     "bo'lishi shart. «Narx keyinchalik bozor holatiga qarab aniqlanadi», «miqdor yetkazib beruvchining "
     "imkoniyatiga qarab» kabi aniq mexanizmi bo'lmagan bandlar — jiddiy noaniqlik (g'arar) hisoblanadi.\n\n"
     "Aniq formula (masalan, birja kotirovkasi ___ sanadagi narxi bo'yicha) yozilsa, noaniqlik bartaraf bo'ladi."),
    ("qoida", "savdo", "Bir bitimda ikki narx — tanlov ochiq qolmasligi kerak",
     "«Naqd to'lansa 100 mln, bo'lib to'lansa 120 mln» deb, qaysi biri tanlangani aniqlanmay shartnoma "
     "tuzilsa — bir bitimda ikki bitim bo'ladi va joiz emas. Muzokarada ikki variant aytilishi mumkin, "
     "lekin shartnomada faqat tomonlar tanlagan bitta narx va bitta to'lov tartibi yozilishi kerak."),
    ("qoida", "ijara", "Ijara: mulk egasining majburiyatlari va ijara haqi",
     "Ijaraga beruvchi mulkning egasi sifatida asosiy (strukturaviy) ta'mir va mulkni yo'qotish xavfini o'z "
     "zimmasiga oladi; bularni ijarachiga yuklash sharti joiz emas. Kundalik foydalanish xarajatlari "
     "ijarachida bo'lishi mumkin.\n\nIjara haqi va muddati aniq bo'lishi kerak. Mulkdan foydalanish imkoni "
     "bo'lmagan davr uchun ijara haqi olinmaydi. Kechikish uchun jarima — faqat xayriya majburiyati shaklida."),
    ("qoida", "mushoraka", "Mushoraka: foyda nisbatda, zarar kapitalga mutanosib",
     "Sheriklikda foyda oldindan kelishilgan nisbatda (masalan 60/40) taqsimlanadi. Sheriklardan biriga "
     "belgilangan summa yoki kapitalning ma'lum foizini kafolatlash (masalan, «har oy 5 mln foyda "
     "kafolatlanadi») joiz emas. Zarar har bir sherikning kapitaldagi ulushiga mutanosib ko'tariladi.\n\n"
     "To'g'ri band namunasi: «Sof foyda Tomonlar o'rtasida ___% / ___% nisbatda taqsimlanadi. Zarar "
     "Tomonlarning kapitaldagi ulushlariga mutanosib ravishda ko'tariladi.»"),
    ("qoida", "mudoraba", "Mudoraba: kapitalni va foydani kafolatlash mumkin emas",
     "Mudorabada kapital egasi pulni, mudorib mehnatini qo'yadi. Foyda nisbat bo'yicha taqsimlanadi. Mudorib "
     "kapitalni yoki ma'lum foydani kafolatlay olmaydi — zarar (mudoribning beparvoligi yoki shartni buzishidan "
     "tashqari) kapital egasiga tushadi. «Investorga oyiga 3% kafolatlangan daromad» sharti mudorabani "
     "foizli qarzga aylantiradi."),
    ("qoida", "qarz", "Garovdan kreditor foydalanishi — qarz evaziga manfaat",
     "Qarz uchun garovga qo'yilgan mulkdan (masalan, avtomobil, uy) kreditorning bepul foydalanishi qarz "
     "evaziga olingan manfaat bo'lib, ribo hukmida. Garov faqat qarzni ta'minlash uchun saqlanadi; undan "
     "foydalanish bozor narxidagi alohida ijara shartnomasi bilan bo'lishi mumkin."),
    ("misol", "umumiy", "Keys: penya olgan do'kondor — foyda emas, ribo",
     "Bir do'kondor qurilish mollarini nasiyaga sotib, shartnomaga «kechikkan har kun uchun 0,5% penya» deb "
     "yozgan. Xaridor 40 kun kechikdi va 100 mln so'mlik qarzga 20 mln so'm penya yig'ildi. Do'kondor buni "
     "«yaxshi daromad» deb hisobladi. Aslida bu 20 mln — hech qanday tovar yoki mehnat evaziga emas, faqat "
     "vaqt evaziga olingan qo'shimcha, ya'ni qarz ustiga ribo. Keyingi shartnomada do'kondor bandni "
     "o'zgartirdi: kechikkan xaridor kelishilgan summani xayriyaga beradi, do'kondor esa undirish uchun "
     "qilgan haqiqiy xarajatini (masalan, sud xarajati) alohida talab qiladi.\n\n"
     "Saboq: kechikish uchun olinadigan har qanday pul sotuvchining daromadi bo'lsa — ribo; intizom uchun "
     "xayriya majburiyati yoziladi."),
    ("ustoz", "umumiy", "Ustoz fikri: «foiz» so'zini emas, mazmunni tekshiring",
     "Shartnomada «foiz» so'zi ishlatilgani o'zi muammo emas — masalan, «foydaning 30 foizi» ulush "
     "ma'nosida. Tekshirilishi kerak: qo'shimcha to'lov vaqtga (muddat, kechikish) bog'langanmi yoki haqiqiy "
     "savdo/sheriklik natijasigami. Vaqtga bog'langan qo'shimcha — ribo belgisi."),
    ("ustoz", "salam", "Ustoz fikri: oldindan to'lov bilan buyurtma (salam/istisno')",
     "Oldindan to'lab, keyin tovar olish salam bo'lsa — narx shartnoma vaqtida to'liq to'lanishi, tovar "
     "turi, sifati, miqdori va topshirish sanasi aniq yozilishi shart. Ishlab chiqariladigan buyum (mebel, "
     "uskuna) uchun istisno' — to'lov bosqichma-bosqich bo'lishi mumkin, texnik tavsif batafsil bo'lsin."),
]


def seed(db, KnowledgeDoc, user_id=None):
    for kind, topic, title, body in DOCS:
        db.session.add(KnowledgeDoc(kind=kind, topic=topic, title=title, body=body, source=SRC, created_by=user_id))
