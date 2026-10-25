"""Supported languages: display names, Edge TTS voices and Windows OCR tags."""

# code -> name (English), name (native), voices {variant: edge-tts voice}, Windows OCR tag
LANGUAGES = {
    "en": ("English", "English",
           {"US": "en-US-AriaNeural", "UK": "en-GB-SoniaNeural", "Australia": "en-AU-NatashaNeural"},
           "en-US"),
    "zh-CN": ("Chinese (Simplified)", "简体中文", {"Mainland": "zh-CN-XiaoxiaoNeural"}, "zh-Hans-CN"),
    "zh-TW": ("Chinese (Traditional)", "繁體中文",
              {"Taiwan": "zh-TW-HsiaoChenNeural", "Hong Kong": "zh-HK-HiuMaanNeural"}, "zh-Hant-TW"),
    "ja": ("Japanese", "日本語", {"Japan": "ja-JP-NanamiNeural"}, "ja-JP"),
    "ko": ("Korean", "한국어", {"Korea": "ko-KR-SunHiNeural"}, "ko-KR"),
    "fr": ("French", "Français", {"France": "fr-FR-DeniseNeural", "Canada": "fr-CA-SylvieNeural"}, "fr-FR"),
    "de": ("German", "Deutsch", {"Germany": "de-DE-KatjaNeural"}, "de-DE"),
    "es": ("Spanish", "Español", {"Spain": "es-ES-ElviraNeural", "Mexico": "es-MX-DaliaNeural"}, "es-ES"),
    "it": ("Italian", "Italiano", {"Italy": "it-IT-ElsaNeural"}, "it-IT"),
    "pt": ("Portuguese", "Português", {"Brazil": "pt-BR-FranciscaNeural", "Portugal": "pt-PT-RaquelNeural"},
           "pt-BR"),
    "ru": ("Russian", "Русский", {"Russia": "ru-RU-SvetlanaNeural"}, "ru-RU"),
    "vi": ("Vietnamese", "Tiếng Việt", {"Vietnam": "vi-VN-HoaiMyNeural"}, "vi-VN"),
}

# Languages written in Latin script; single words in these are easy to mis-detect
LATIN_SCRIPT = {"en", "fr", "de", "es", "it", "pt", "vi"}


def normalize(code):
    """Map a Google language code (e.g. 'zh-CN', 'pt', 'en-US') onto a key of LANGUAGES."""
    if not code:
        return None
    if code in LANGUAGES:
        return code
    if code.lower().startswith("zh"):
        return "zh-TW" if code.lower() in ("zh-tw", "zh-hk", "zh-hant") else "zh-CN"
    base = code.split("-")[0].lower()
    return base if base in LANGUAGES else None


def same_language(a, b):
    a, b = normalize(a), normalize(b)
    return a is not None and a == b


def label(code):
    name, native, _, _ = LANGUAGES[code]
    return name if name == native else f"{name} · {native}"


def voices(code):
    return LANGUAGES[code][2]


def voice_for(code, variant=None):
    options = voices(code)
    return options.get(variant) or next(iter(options.values()))


def ocr_tag(code):
    return LANGUAGES[code][3]
