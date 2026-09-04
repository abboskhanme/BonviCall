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
ALERT_TEXT: dict[str, tuple[str, str]] = {
    "credential_replay": (
        "Qo'ng'iroq boshqa qurilmada qayd etilgan",
        "Bir xil qo'ng'iroq ikki xil raqamdan yuborildi. Qurilma ma'lumotlari "
        "tekshirilishi kerak.",
    ),
    "attribution_out_of_range": (
        "Qo'ng'iroq biriktirish muddatidan tashqarida",
        "Qo'ng'iroq vaqti hech qaysi raqam biriktiruviga to'g'ri kelmadi. "
        "Biriktirish tarixini tekshiring.",
    ),
    "installation_rebound": (
        "Raqam boshqa telefonga ko'chirildi",
        "Ish raqami yangi qurilmaga bog'landi. Agar bu kutilmagan bo'lsa, xodim "
        "bilan bog'laning.",
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
    """``(title_uz, body_uz)`` for an alert kind, or a safe generic pair."""
    return ALERT_TEXT.get(kind, (kind.replace("_", " ").capitalize(), DEFAULT_MESSAGE))


__all__ = [
    "ALERT_TEXT",
    "DEFAULT_MESSAGE",
    "DEVICE_PROTOCOL_CODES",
    "INSTALL_PAGE",
    "MESSAGES",
    "alert_text",
    "message_for",
]
