"""Uzbek user-facing messages, keyed by error code (CONVENTIONS.md §14, N39).

This is one of exactly three files in the product where Uzbek text is legal
inside source (the others are ``panel/src/shared/i18n/uz.json`` and
``android/.../values/strings.xml``). Comments and identifiers here are still
English, like everywhere else.

A code with no entry falls back to :data:`DEFAULT_MESSAGE`; a test asserts that
every user-facing code declared in ``core/errors.py`` has a real entry, so the
fallback is a safety net rather than a habit.

Codes marked "device protocol" stay English on purpose: SPEC §4.0 says the
message is Uzbek *wherever an end user reads it*, and nobody reads a chunk
offset mismatch — it is consumed by the upload client and logged.
"""

from __future__ import annotations

from src.core.errors import ErrorCode

DEFAULT_MESSAGE = "Xatolik yuz berdi. Administratorga murojaat qiling."

#: Codes whose message is read only by a machine (the Android upload queue).
DEVICE_PROTOCOL_CODES = frozenset(
    {
        ErrorCode.HEADER_MISSING,
        ErrorCode.CHUNK_OFFSET_MISMATCH,
        ErrorCode.CHUNK_CHECKSUM_MISMATCH,
        ErrorCode.CHECKSUM_MISMATCH,
        ErrorCode.RANGE_NOT_SATISFIABLE,
    }
)

MESSAGES: dict[str, str] = {
    # --- Generic ---------------------------------------------------------
    ErrorCode.APP_ERROR: "Xatolik yuz berdi.",
    ErrorCode.BAD_REQUEST: "So'rov noto'g'ri shakllantirilgan.",
    ErrorCode.VALIDATION_ERROR: "Kiritilgan ma'lumotlar noto'g'ri.",
    ErrorCode.INTERNAL_ERROR: (
        "Serverda kutilmagan xatolik yuz berdi. Administratorga xabar bering."
    ),
    ErrorCode.NOT_FOUND: "Topilmadi.",
    ErrorCode.METHOD_NOT_ALLOWED: "Bu manzil uchun bunday amal mavjud emas.",
    ErrorCode.CONFLICT: "Bu amalni bajarib bo'lmadi: ma'lumotlar bir-biriga zid.",
    ErrorCode.PAYLOAD_TOO_LARGE: "Yuborilgan ma'lumot hajmi juda katta.",
    ErrorCode.RATE_LIMITED: "Juda ko'p urinish bo'ldi. Biroz kutib, qaytadan urinib ko'ring.",
    # --- Auth and access --------------------------------------------------
    ErrorCode.UNAUTHORIZED: "Sessiya tugagan. Iltimos, qaytadan kiring.",
    ErrorCode.FORBIDDEN: "Bu amal uchun sizda ruxsat yo'q.",
    ErrorCode.INSTALLATION_MISMATCH: (
        "Bu token boshqa qurilmaga tegishli. Administratorga murojaat qiling."
    ),
    ErrorCode.INSTALLATION_REVOKED: (
        "Bu qurilma ro'yxatdan chiqarilgan. Administratorga murojaat qiling."
    ),
    ErrorCode.REFRESH_REUSED: "Sessiya xavfsizlik uchun bekor qilindi. Qaytadan kiring.",
    ErrorCode.VERIFICATION_REQUIRED: "Avval ish raqamingizni tasdiqlang.",
    ErrorCode.APP_VERSION_UNSUPPORTED: (
        "Ilovaning bu versiyasi eskirgan. Yangi versiyasini o'rnating."
    ),
    # --- Users and roles --------------------------------------------------
    ErrorCode.SALES_USER_REQUIRES_AGENT: (
        "Sotuvchi hisobi uchun xodim tanlanishi shart."
    ),
    ErrorCode.CANNOT_MODIFY_SELF: "O'z hisobingizni o'zingiz o'zgartira olmaysiz.",
    ErrorCode.LAST_ADMIN: "Tizimda kamida bitta faol administrator qolishi kerak.",
    # --- Identity: numbers, agents, assignments ---------------------------
    ErrorCode.NUMBER_ALREADY_ASSIGNED: (
        "Bu raqam allaqachon boshqa xodimga biriktirilgan."
    ),
    ErrorCode.ASSIGNMENT_OVERLAP: (
        "Biriktirish muddatlari bir-birining ustiga tushmasligi kerak."
    ),
    ErrorCode.AGENT_HAS_OPEN_ASSIGNMENT: (
        "Xodimda ochiq raqam biriktiruvi bor. Avval uni yoping."
    ),
    # --- Enrolment --------------------------------------------------------
    ErrorCode.ENROLMENT_CODE_NOT_FOUND: (
        "Bunday kod topilmadi. Kodni tekshirib, qaytadan kiriting."
    ),
    ErrorCode.ENROLMENT_CODE_USED: (
        "Bu kod allaqachon ishlatilgan. Administratordan yangi kod so'rang."
    ),
    ErrorCode.ENROLMENT_CODE_EXPIRED: (
        "Ushbu kod muddati tugagan. Administratordan yangi kod so'rang."
    ),
    ErrorCode.ENROLMENT_CODE_REVOKED: (
        "Bu kod bekor qilingan. Administratordan yangi kod so'rang."
    ),
    ErrorCode.INSTALLATION_ALREADY_ACTIVE: (
        "Bu raqam boshqa telefonga ulangan. Ilovani shu telefonga ko'chirish uchun "
        "tasdiqlashni davom ettiring."
    ),
    ErrorCode.MSISDN_UNAVAILABLE: (
        "SIM karta raqamni ko'rsatmadi. Tasdiqlashning ikkinchi usuliga o'tamiz."
    ),
    ErrorCode.NUMBER_MISMATCH: (
        "Qo'ng'iroq boshqa raqamdan keldi. Ish raqamingiz turgan SIM kartani tanlang."
    ),
    ErrorCode.CALLBACK_RECEIVER_DOWN: (
        "Tasdiqlash xizmati hozir ishlamayapti. Administratorga murojaat qiling."
    ),
    # --- Calls ------------------------------------------------------------
    ErrorCode.CALL_NOT_FOUND: "Qo'ng'iroq topilmadi.",
    ErrorCode.CALL_IDENTITY_CONFLICT: (
        "Bu qo'ng'iroq boshqa qurilmada qayd etilgan. Administratorga xabar berildi."
    ),
    ErrorCode.DELETE_NOT_ALLOWED: "Qo'ng'iroqni va uning yozuvini o'chirib bo'lmaydi.",
    # --- Audio ------------------------------------------------------------
    ErrorCode.AUDIO_NOT_ATTRIBUTABLE: (
        "Yozuv birorta ish qo'ng'irog'iga mos kelmadi, shuning uchun saqlanmadi."
    ),
    ErrorCode.AUDIO_EXPIRED: "Yozuvni saqlash muddati tugagan va u o'chirilgan.",
    ErrorCode.AUDIO_NOT_FOUND: "Bu qo'ng'iroq uchun ovoz yozuvi yo'q.",
    ErrorCode.UPLOAD_EXPIRED: "Yuklash seansi muddati tugagan.",
    # --- Settings ---------------------------------------------------------
    ErrorCode.RETENTION_CONFIRMATION_REQUIRED: (
        "Saqlash muddatini qisqartirish alohida tasdiqlanishi kerak."
    ),
    # --- Device protocol (English on purpose, see the module docstring) ----
    ErrorCode.HEADER_MISSING: "A required request header is missing.",
    ErrorCode.CHUNK_OFFSET_MISMATCH: "Chunk offset does not match the session state.",
    ErrorCode.CHUNK_CHECKSUM_MISMATCH: "Chunk checksum does not match the payload.",
    ErrorCode.CHECKSUM_MISMATCH: "Whole-file checksum does not match the upload.",
    ErrorCode.RANGE_NOT_SATISFIABLE: "The requested byte range is outside the file.",
}


#: Alert wording, keyed by ``core.enums.AlertKind`` value: ``(title, body)``.
#: The alert rows carry ``title_uz`` and ``body_uz`` (SPEC §3.8), and the text
#: has to be composed somewhere — it is composed here, because this is the one
#: ``.py`` allowed to contain Uzbek (§14). A service names the kind; it never
#: writes the sentence.
#: ``(title_uz, body_uz)`` for every ``AlertKind``. **All 27, no fallback in
#: practice** — ``test_every_alert_kind_has_uzbek_text`` fails on a new kind
#: with no entry.
#:
#: Two rules the wording follows, and they are the point of the table:
#:
#: 1. **The title says what happened, the body says what to do.** "Qurilma
#:    aloqada emas" is a noun; an admin reading it at 19:00 needs "telefon
#:    o'chirilgan yoki internetsiz bo'lishi mumkin — xodim bilan bog'laning".
#:    A body identical for 27 kinds is a shrug with a timestamp.
#: 2. **It is the same text the panel shows.** The panel derived its own
#:    wording from ``kind`` while these fields read "Device offline" and the
#:    generic error body, so it had to. Now the server carries it and the
#:    device API, e-mail and any future notification path get the same
#:    sentence — one place, which is the rule everywhere else in this file.
#: Used only if a kind has no entry, which the test says cannot happen.
UNKNOWN_ALERT_TITLE = "Tekshirilishi kerak bo'lgan hodisa"

ALERT_TEXT: dict[str, tuple[str, str]] = {
    "capture_disabled": (
        "Yozib olish o'chirilgan",
        "Xodim ilovada yozib olishni o'chirgan. Uning telefonini oching va qaytadan yoqing.",
    ),
    "permission_lost_microphone": (
        "Mikrofon ruxsati yo'qolgan",
        "Mikrofon ruxsati olib qo'yilgan. Xodimdan ilova sozlamalarida ruxsatni "
        "qaytarishni so'rang.",
    ),
    "permission_lost_phone_state": (
        "Qo'ng'iroq holati ruxsati yo'qolgan",
        "Qo'ng'iroq holati ruxsati olib qo'yilgan — ilova endi qo'ng'iroqni "
        "sezmaydi. Ruxsatni qaytaring.",
    ),
    "permission_lost_call_log": (
        "Qo'ng'iroqlar jurnali ruxsati yo'qolgan",
        "Jurnal ruxsati olib qo'yilgan — qo'ng'iroq davomiyligi aniqlanmaydi. "
        "Ruxsatni qaytaring.",
    ),
    "battery_optimisation_reenabled": (
        "Batareya cheklovi qayta yoqilgan",
        "Telefon batareyani tejash uchun ilovani to'xtatmoqda. Sozlamalardan "
        "ilovani cheklovdan chiqaring — bu eng ko'p uchraydigan sabab.",
    ),
    "app_force_stopped": (
        "Ilova majburan to'xtatilgan",
        "Ilova qo'lda to'xtatilgan va o'zi qayta ishga tushmaydi. Xodimdan "
        "ilovani ochishni so'rang.",
    ),
    "install_disappeared": (
        "Ilova telefondan yo'qolgan",
        "Ilova o'chirilgan yoki telefon almashtirilgan. Xodimga yangi kod "
        "berib, qaytadan o'rnating.",
    ),
    "recording_route_lost": (
        "Yozib olish usuli ishlamay qoldi",
        "Bu telefonda yozib olish yo'li ishlamay qoldi. Qurilma kartasidagi "
        "ruxsatlar jadvalini tekshiring.",
    ),
    "service_not_running": (
        "Fondagi xizmat ishlamayapti",
        "Fondagi xizmat to'xtagan. Telefonni qayta ishga tushiring va ilovani oching.",
    ),
    "device_offline": (
        "Qurilma aloqada emas",
        "Telefon uzoq vaqt aloqaga chiqmadi. O'chirilgan yoki internetsiz "
        "bo'lishi mumkin — xodim bilan bog'laning.",
    ),
    "device_silent": (
        "Qurilmadan qo'ng'iroq kelmayapti",
        "Telefon aloqada, lekin ish vaqtida qo'ng'iroq yubormayapti. Xodim "
        "boshqa telefondan qo'ng'iroq qilayotgan bo'lishi mumkin.",
    ),
    "fleet_silent": (
        "Butun park jim qoldi",
        "Hech bir qurilmadan ma'lumot kelmayapti. Bu server yoki tarmoq "
        "muammosi — administratorga darhol xabar bering.",
    ),
    "capture_rate_regression": (
        "Yozib olish darajasi pasaydi",
        "Bu model uchun yozib olish darajasi belgilangan darajadan pastga "
        "tushdi. Yozuvsiz qo'ng'iroqlar hisobotini oching.",
    ),
    "queue_full": (
        "Telefondagi navbat to'lgan",
        "Telefondagi navbat bo'shamayapti. Qurilmani Wi-Fi ga ulang va ilovani oching.",
    ),
    "storage_low": (
        "Telefonda joy qolmadi",
        "Telefon xotirasi to'lgani uchun yangi yozuvlar saqlanmayapti. Xodimdan "
        "joy bo'shatishni so'rang.",
    ),
    "poisoned_record": (
        "Yuborib bo'lmaydigan yozuv",
        "Bitta yozuvni yuborib bo'lmadi va u to'xtatildi. Yozuv o'chirilmaydi — "
        "administrator tekshirishi kerak.",
    ),
    "auth_expired": (
        "Qurilma sessiyasi tugagan",
        "Qurilma sessiyasi tugagan va yangilana olmadi. Xodimdan ilovani ochishni so'rang.",
    ),
    "credential_replay": (
        "Token qayta ishlatilgan",
        "Bir token ikki marta ishlatildi. Bu jiddiy — qurilmani ro'yxatdan "
        "chiqarib, qaytadan ulang.",
    ),
    "installation_rebound": (
        "Raqam boshqa telefonga ulandi",
        "Ish raqami boshqa telefonga ulandi. Bu rejalashtirilgan bo'lmasa, darhol tekshiring.",
    ),
    "callback_receiver_down": (
        "Tasdiqlash xizmati ishlamayapti",
        "Tasdiqlash xizmati javob bermayapti — hozir hech kimni ro'yxatga olib "
        "bo'lmaydi. Administratorga xabar bering.",
    ),
    "enrolment_stalled": (
        "Ro'yxatga olish to'xtab qoldi",
        "Xodim ro'yxatga olishni boshlagan, lekin tugatmagan. Xodim kartasini "
        "oching va qaysi bosqichda to'xtaganini ko'ring.",
    ),
    "attribution_out_of_range": (
        "Qo'ng'iroq biriktirish muddatidan tashqarida",
        "Qo'ng'iroq raqam biriktirilmagan davrda qilingan. Biriktirish sanalarini tekshiring.",
    ),
    "attribution_discarded_spike": (
        "Ko'p qo'ng'iroq biriktirilmadi",
        "Ko'p qo'ng'iroq hech kimga biriktirilmadi. Raqam biriktiruvlari "
        "to'g'ri kiritilganini tekshiring.",
    ),
    "retention_job_failed": (
        "Saqlash muddati vazifasi bajarilmadi",
        "Eski yozuvlarni o'chirish vazifasi bajarilmadi. Server jurnalini tekshirish kerak.",
    ),
    "backup_failed": (
        "Zaxira nusxa olinmadi",
        "Zaxira nusxa olinmadi. Administrator serverni tekshirishi kerak.",
    ),
    "storage_capacity_low": (
        "Serverda joy kamaymoqda",
        "Serverda joy tugab qolmoqda. Saqlash muddatini yoki disk hajmini ko'rib chiqing.",
    ),
    "min_version_refusals": (
        "Eski ilova versiyalari rad etilmoqda",
        "Eski ilovali telefonlar rad etilmoqda. Ularga yangi versiyani o'rnating.",
    ),
}

#: The install landing page (UC-02, SPEC §8.1). One column, no JavaScript, and
#: the first Uzbek a salesperson reads about the product.
INSTALL_PAGE: dict[str, str] = {
    "greeting": "Salom, {agent}.",
    "records_intro": "Bu ilova quyidagi raqamdagi <b>ish qo'ng'iroqlaringizni</b> yozib boradi:",
    "what_it_does": "Ilova nima qiladi",
    "boundary_registered": "Faqat shu raqamdagi qo'ng'iroqlar qayd etiladi.",
    "boundary_second_sim": "Ikkinchi SIM kartaga umuman tegilmaydi.",
    "boundary_private": (
        "Telefon kitobi, SMS, rasm va joylashuv <b>hech qachon</b> yuborilmaydi."
    ),
    "boundary_data": (
        "Yozuvlar Wi-Fi orqali yuboriladi; mobil internet sarfi kam va uni "
        "kompaniya qoplaydi."
    ),
    "step_download": "1-qadam — yuklab olish",
    "download_button": "Ilovani yuklab olish",
    "apk_not_ready_short": "Ilova hozircha tayyor emas. Administratordan so'rang.",
    "hint_android_13": (
        "Yuklab olgach, brauzer \"Bu fayl qurilmangizga zarar yetkazishi mumkin\" deb "
        "ogohlantiradi — bu kutilgan holat. \"Baribir yuklab olish\" ni tanlang."
    ),
    "hint_android_8": (
        "Yuklab olgach, \"Noma'lum ilovalarni o'rnatish\" ruxsatini brauzer uchun "
        "yoqishingiz so'raladi. Yoqing va orqaga qayting."
    ),
    "other_version_prefix": "Boshqa Android versiyasi: ",
    "step_play_protect": "2-qadam — Play Protect ogohlantirishi",
    "play_protect_body": (
        "\"Xavfli ilova bloklandi\" deb chiqishi mumkin. Bu kutilgan holat: ilova "
        "Google Play orqali tarqatilmaydi. \"Batafsil\" → \"Baribir o'rnatish\" ni "
        "tanlang."
    ),
    "step_code": "3-qadam — ilovani oching va kodni kiriting",
    "deep_link": "Ilovani kod bilan ochish",
    "stuck": (
        "Ishlamayapti? Administratorga murojaat qiling — u sizga yordam berish "
        "uchun ulanadi."
    ),
    "page_title": "BonviCall — o'rnatish",
    "unavailable_title": "Havola ishlamaydi",
    "unavailable_body": "Bu o'rnatish havolasi eskirgan yoki allaqachon ishlatilgan.",
    "unavailable_action": (
        "Administratordan yangi havola so'rang — u bir daqiqada yuboradi."
    ),
    "apk_missing_title": "Ilova hali tayyor emas",
    "apk_missing_body": (
        "Havolangiz to'g'ri, lekin ilovaning tayyor versiyasi hali joylashtirilmagan."
    ),
    "apk_missing_action": "Administratorga xabar bering.",
}


def message_for(code: str) -> str:
    """The message a client shows for ``code``."""
    return MESSAGES.get(code, DEFAULT_MESSAGE)


def alert_text(kind: str) -> tuple[str, str]:
    """``(title_uz, body_uz)`` for an alert kind.

    The fallback should be unreachable — a test covers every ``AlertKind`` —
    and it is **Uzbek** rather than the enum name, because the old fallback
    rendered ``device_offline`` as the English "Device offline" into a field an
    end user reads (§14). If a kind ever slips through, a vague Uzbek sentence
    is a smaller failure than an English one.
    """
    return ALERT_TEXT.get(kind, (UNKNOWN_ALERT_TITLE, DEFAULT_MESSAGE))


__all__ = [
    "ALERT_TEXT",
    "DEFAULT_MESSAGE",
    "DEVICE_PROTOCOL_CODES",
    "INSTALL_PAGE",
    "MESSAGES",
    "UNKNOWN_ALERT_TITLE",
    "alert_text",
    "message_for",
]
