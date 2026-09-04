# BonviCall — bir betlik xulosa

**Sana:** 2026-09-04 · Talablar bosqichi yakuni
**Batafsil:** `docs/REQUIREMENTS.md` · risklar `docs/RISKS.md` · qabul qilingan
qarorlar `docs/ASSUMPTIONS.md`

---

## Nima quriladi

**BonviCall — Bonvi'ning o'z qo'ng'iroq platformasi.** MoyZvonki o'rnini bosadi:
qo'ng'iroqlar ham, yozuvlar ham bizda qoladi, oylik to'lov to'xtaydi.

Uch qismdan iborat, uchalasi ham noldan:

| Qism | Vazifasi |
|---|---|
| **Android ilova** | Xodim telefonida ishlaydi. Qo'ng'iroqni aniqlaydi, yozib oladi, telefonda navbatga qo'yadi va internet paydo bo'lishi bilan serverga uzatadi |
| **Server** | Qo'ng'iroqlarni qabul qiladi, audioni saqlaydi, qurilmalar holatini kuzatadi |
| **Veb panel** | Admin va rahbar uchun: qo'ng'iroqlar ro'yxati, tinglash, xodimlar, qurilmalar sog'ligi |

**Ishlash sxemasi:** qo'ng'iroq oddiy SIM orqali ketadi — mijoz xodimning o'sha
tanish raqamiga qo'ng'iroq qilaveradi, hech narsa o'zgarmaydi. Yozuv telefonda
paydo bo'ladi, keyin serverga ko'chadi. Internet yo'q bo'lsa — navbatda turadi
va keyin yuboriladi.

**Kimni yozib olamiz:** faqat **bazaga kiritilgan ish raqami** bo'yicha. Telefon
xodimniki bo'lgani uchun uning shaxsiy SIM'idagi qo'ng'iroqlari **yozilmaydi va
serverga yuborilmaydi**. Bu ham to'g'ri, ham xodimlar ishonchi uchun zarur.

**Reliz 1 bitta jumlada:** Bonvi telefonida qilingan yoki qabul qilingan
qo'ng'iroq veb panelda ko'rinadi — yo'nalishi, raqami, vaqti, davomiyligi va
(telefon imkon bergan joyda) tinglanadigan yozuvi bilan — **bir marta**, bir
necha daqiqa ichida, va telefon o'chgan, qayta yoqilgan yoki internetsiz bo'lgan
bo'lsa ham.

---

## Nima qurilmaydi (ataylab)

Bular reliz 1 ga **kirmaydi** — keyinroq, alohida qaror bilan:

- **ATS (PBX) emas** — SIP, operator shartnomasi, IVR, navbat yo'q. Agar
  telefonlarda yozib olish ishlamay qolsa, bu variant qaytadan ko'riladi
- **iPhone qo'llab-quvvatlanmaydi** — iOS'da bunday imkoniyat umuman yo'q.
  Agar savdo xodimlaringiz orasida iPhone ishlatadigani bo'lsa, u qamrovga
  tushmaydi
- **Analitika yo'q** — ASR, LLM baholash, reyting BonviZvonki'da qoladi
- **BonviZvonki bilan hozircha bog'lanmaydi** — reliz 1 mustaqil ishlaydi,
  ulanish reliz 2 da (pastda batafsil)
- **CRM emas** — AmoCRM integratsiyasi va SMS yuborish kiritilmaydi
- **WhatsApp / Telegram qo'ng'iroqlari yozilmaydi** — texnik imkoni yo'q.
  Buni bilib turish kerak: paneldagi son real faollikdan kam bo'lishi mumkin

---

## Sizdan nima kerak — bugundan

Bular bizga bog'liq emas, kutish vaqti o'zi ketadi. Kechiktirilgan kuni har biri
muddatga ta'sir qiladi:

| # | Nima kerak | Nega shoshilinch |
|---|---|---|
| **1** | **Telefonlar ro'yxati** — har bir xodim uchun: model, Android versiyasi, SIM kimniki, va telefonida **o'rnatilgan qo'ng'iroq yozuvchisi bor-yo'qligi**. Alohida: **sinovda qaysi telefonlar ishlatilgan** | Eng shoshilinch band. Quyidagi 2-riskda tushuntirilgan sabab bo'yicha bu endi ma'muriy ro'yxat emas — audio umuman bo'ladimi-yo'qmi, shu ro'yxat hal qiladi |
| **2** | **Yurist xulosasi** — ovoz yozuvi biometrik ma'lumot hisoblanadimi (ZRU-547) va u qayerda saqlanishi kerak | Javob serverni qayerga qo'yishimizni belgilaydi. Serverni sotib olgandan keyin ko'chirish qimmat |
| **3** | **Mijozga ogohlantirish matni** — shartnomaga bir qatorli band va savdo xodimi aytadigan tayyor jumla | Xodimlar masalasi hal (majburiy o'rnatiladi), lekin **liniyaning narigi tomonidagi odam sizning xodimingiz emas**. Buni dastur hal qila olmaydi |
| **4** | **Server va disk** — kamida 250 GB (yiliga ~200 GB audio) | Kod tayyor bo'lgach kutib o'tirmaslik uchun |
| **5** | **Mobil internetni kim to'laydi** — audio xodimning shaxsiy tarifidan ketadimi? | Oyiga ~1 GB. Kichik masala, lekin xodimlar munosabatiga katta ta'sir qiladi |

---

## Risklar — eng muhim uchtasi

To'liq ro'yxat `docs/RISKS.md` da (18 ta risk, har birida chorasi bilan).

**1. O'rnatish va ruxsat olish — eng katta amaliy muammo.**
Sinovda aynan shu qiyinchilik chiqqan: telefonni developer rejimiga o'tkazish
va Play Protect'ni o'chirish kerak bo'lgan. Telefon xodimniki bo'lgani uchun bu
har bir xodimning **shaxsiy** telefoniga kirib, Google'ning himoya funksiyasini
o'chirishni anglatadi. Buni masofadan qilib bo'lmaydi.
→ *Chora:* o'zbek tilida bosqichma-bosqich sozlash oqimi, har qadamda "haqiqatan
ham berildimi" tekshiruvi, va panelda qaysi telefonda qaysi ruxsat yo'qligi
ko'rinib turishi.

**2. Yozib olish telefon modeliga bog'liq — va 1-risk bilan bir ildizdan
chiqqan bo'lishi mumkin.**
Yaxshi xabar: **sinovda ikkala ovoz ham yozilgan** — loyihaning eng qo'rqinchli
savoli amalda hal bo'lgan.

Lekin CallSentry kodini o'qib chiqib, kuchli taxmin paydo bo'ldi: ikkala ovoz
ilovaning o'zi yozgani emas, **telefonning o'z qo'ng'iroq yozuvchisi** yozgan
faylni ilova o'qib olgan bo'lishi mumkin. Agar shunday bo'lsa:

- audio faqat **ichida yozuvchisi bor va u yoqilgan** telefonlarda bo'ladi —
  ya'ni xodim qaysi telefon sotib olganiga bog'liq, bu esa sizning ixtiyoringizda
  emas;
- o'sha faylni o'qish uchun ishlatilgan usul, ehtimol, developer rejimi va Play
  Protect'ni o'chirish talab qilgan ham o'sha — ya'ni **1 va 2-risk bitta narsa**;
- va bu usulning muddati bor: Google yangi Android'larda eski ilovalarni
  o'rnatishni bosqichma-bosqich taqiqlab boradi.

→ *Chora:* birinchi ish — kodni o'qib, aynan qaysi mexanizm ishlaganini aniqlash
(bir kunlik ish). Keyin har bir modelda 10 tadan haqiqiy qo'ng'iroq sinaladi va
"qaysi model qancha foizda yozadi" jadvali chiqariladi. Yozib bo'lmagan holatda
ham **qo'ng'iroqning o'zi baribir qayd etiladi**, sababi ko'rsatilgan holda.

⚠️ Bitta nozik jihat: agar taxmin to'g'ri bo'lsa, xodim o'z telefonining
yozuvchisini **hamma qo'ng'iroqlar uchun** yoqishi kerak bo'ladi — shaxsiylari
uchun ham. Ularning shaxsiy suhbatlari bizning serverga tushmasligi dasturda
qat'iy chegara sifatida yozildi: faqat bazadagi ish raqamiga tegishli, vaqti mos
keladigan fayl olinadi, boshqasi umuman yuborilmaydi.

**3. MoyZvonki'dan erta voz kechish.**
BonviZvonki qo'ng'iroqlarni faqat MoyZvonki'dan oladi. Agar shartnoma BonviCall
isbotlanmasdan bekor qilinsa, ikkala oqim ham bir vaqtda uziladi.
→ *Chora:* **kamida bir oy ikkalasi parallel ishlaydi**, sonlar solishtiriladi,
shundan keyingina bekor qilinadi. Bu loyihadagi eng qimmat xatoni eng arzon
choraga — sabrga — almashtiradi.

---

## BonviZvonki bilan ulanish — qaror qabul qilindi

Siz "keyinchalik ulaymiz" dedingiz. Shunga ko'ra reja:

**Reliz 1 — mustaqil.** Umumiy baza yo'q, jonli API yo'q. BonviCall o'zicha
ishlaydi va o'zicha ko'rsatiladi. Lekin **ma'lumotni tashqariga berish
imkoniyati hoziroq quriladi** — endi bu "ehtimol kerak bo'lar" emas, balki
bajarilishi shart bo'lgan shartnoma.

**Reliz 2 — ulash.** BonviZvonki'ga ikkinchi manba qo'shiladi va u BonviCall'dan
o'qiy boshlaydi. **Bir oy davomida ikkala manba parallel ishlaydi**, qo'ng'iroq
sonlari yonma-yon solishtiriladi — va shundan keyingina MoyZvonki bekor
qilinadi.

Ikkita narsani hozirdan hisobga olamiz, chunki keyin tuzatish qimmat:

1. **Raqam formati BonviZvonki bilan bir xil bo'ladi** — oxirgi 9 raqam bo'yicha
   moslashtirish. Bu xatoni bu jamoa bir marta to'lagan, ikkinchi marta emas.
2. **Audioga kirish yo'li oldindan o'ylanadi** — BonviZvonki audioni o'zida
   saqlamaydi, oqim bilan oladi. Demak unga xizmatlararo himoyalangan endpoint
   kerak bo'ladi; 200 GB ni ikki joyda saqlamaymiz.

⚠️ **Bitta ogohlantirish tartib haqida.** BonviZvonki tomonidagi ulanish ishi
*o'sha* loyihada bajariladi. Agar u rejaga kiritilmasa, "MoyZvonki'ni bekor
qilaylik" bosimi dalildan oldin keladi — va aynan shu loyihaning eng qimmat
xatosi shu.

## Muddat va narx

**25–35 ish kuni** — reja raqami **30 kun** (~6 hafta). Claude MAX bilan 24/7
ishlash hisobga olingan.

Taqqoslash uchun: oddiy rejimda (kuniga 8 soat, odatiy agent ishlatish) bu
**83 ish kuni** bo'lardi. Ya'ni 10 barobar tezlik kodda haqiqatan ham beriladi —
lekin butun loyihaga **2,8 barobar** bo'lib tushadi. Sababi pastda.

### Nima tezlashmaydi

Ishning **40 % i kod emas**, va u hech qanday tezlikda qisqarmaydi:

| Ish | Nega qisqarmaydi |
|---|---|
| Har bir telefon modelida 10 tadan haqiqiy qo'ng'iroq (M0) | Haqiqiy qo'ng'iroq haqiqiy vaqt oladi |
| Uch xodim bilan o'rnatishni sinash | Ular ish vaqtida, uyg'oq va yordamsiz bo'lishi kerak |
| 7 kunlik qabul sinovi | 7 kun — bu 7 kun |
| Yurist xulosasi | Yurist qancha vaqtda javob bersa, shuncha |
| Server xaridi | Yetkazib beruvchiga bog'liq |

### Shuning uchun bitta muhim xulosa

**Tezlik oshgani sari to'siq bizdan sizga o'tadi.**

83 kunlik rejada yurist xulosasi va server xaridi (birgalikda ~30 ish kuni) ish
bilan parallel ketardi va sezilmasdi. **30 kunlik rejada ular sig'maydi — ular
muddatning o'zi bo'lib qoladi.**

Shuning uchun eng muhim qadam kod yozish emas: **so'rovlarni bugun yuborish** —
telefonlar ro'yxati, yuristga murojaat, uch xodimni band qilish, qabul sinovi
uchun telefonlar, SMS gateway. Serverni esa kutmasdan vaqtinchalik hostga
qo'yamiz.

**Eng past chegara — taxminan 20 ish kuni.** Kod cheksiz tez yozilganda ham
o'lchash, sinash va 7 kunlik qabul sinovi ketma-ket bajariladi.

### Narx

**Ishlab chiqish:** 30 kun × sizning kun stavkangiz. Ustiga Claude MAX obunasi —
6–8 hafta uchun taxminan **$200–400**.

| Kun stavkasi | 25 kun | **30 kun** | 35 kun |
|---|---:|---:|---:|
| $150 | $3 750 | **$4 500** | $5 250 |
| $200 | $5 000 | **$6 000** | $7 000 |
| $300 | $7 500 | **$9 000** | $10 500 |
| $400 | $10 000 | **$12 000** | $14 000 |

**Doimiy xarajat — oyiga $35–70** (~0,4–0,9 mln so'm):

| | |
|---|---|
| Server (4 vCPU / 8 GB / 320 GB) | $25–40 |
| Zaxira nusxa | $5–15 |
| Qabul qiluvchi SIM | ~10–20 ming so'm |

Ilgari bu $45–140 edi — yurist talabi olib tashlangach, serverni istalgan joyga
qo'yish mumkin bo'ldi va narx tushdi. 15 xodim uchun **oyiga $2,5–5/xodim**, va
qo'ng'iroq soniga qarab o'smaydi — faqat saqlangan audio hajmiga qarab.

**Bir martalik, bahodan tashqari:**

| | |
|---|---|
| Yozib ololmaydigan telefon o'rniga yangisi | **$0 – $1 000+** — nechta ekani ro'yxat kelgach ma'lum. Bahodagi eng katta noaniq band |
| Qayta qo'ng'iroq qabul qiluvchi (W12) | **$50–150** — ofis SIM'i + GSM shlyuz, yoki doim ulangan bitta Android telefon |
| ~~Yurist to'lovi~~ | **$0** — olib tashlandi |
| ~~SMS gateway~~ | **$0** — olib tashlandi |

**Keyingi xizmat ko'rsatish:** choragiga 2–4 kun (yiliga 8–16 kun). Android har
versiyada qoidalarni qattiqlashtiradi — bu bir martalik emas, doimiy band.

### Qoplanish muddati — bitta raqam yetishmayapti

```
qoplanish (oy) = ishlab chiqish narxi / (MoyZvonki oylik to'lovi − $35..70)
```

**MoyZvonki'ga oyiga qancha to'layotganingiz bizda yo'q** — BonviZvonki
hujjatlarida ham yozilmagan. Bu loyiha umuman arziydimi degan savolga javob
beradigan yagona raqam. Telefonlar ro'yxati bilan birga so'rayman.

---

## Keyingi qadam

Talablar tayyor. Navbatdagi bosqich — **texnologiya tanlash** (`plan-stack`):
server va panel qaysi stack'da yoziladi, audio qayerda saqlanadi. Android tomoni
Kotlin bo'lishi deyarli aniq — boshqa variant kerakli imkoniyatlarni bermaydi.
Undan keyin arxitektura (`plan-architect`) va baholash (`plan-estimate`).
