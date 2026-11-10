"""Translation, dictionary and OCR back-ends."""

import json
import re
import time
import urllib.parse
import urllib.request

from PIL import Image

from languages import LANGUAGES, LATIN_SCRIPT, normalize, ocr_tag, same_language

CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def http_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


GOOGLE_PAUSE = 10 * 60      # after Google refuses (429, network), leave it alone this long
google_paused_until = 0.0


def translate(text, source, target, hl, guess=None):
    """Google first. When Google is unavailable (it rate-limits the free endpoint with HTTP 429), don't keep
    knocking: pause it for GOOGLE_PAUSE and translate with other free services meanwhile (`fallback`)."""
    global google_paused_until
    if time.time() >= google_paused_until:
        try:
            return google(text, source, target, hl)
        except Exception:
            google_paused_until = time.time() + GOOGLE_PAUSE
    return fallback(text, source, target, guess)


def fallback(text, source, target, guess=None):
    """Same shape as google(), from Youdao (English <-> Chinese words) or MyMemory (any pair, a free public API).
    No dictionary senses or romanization from here; Youdao still adds IPA and senses for English words later."""
    src = source if source != "auto" else ("zh-CN" if CJK_RE.search(text) else (guess or "en"))
    if {normalize(src), normalize(target)} == {"en", "zh-CN"} and len(text.split()) <= 3:
        main = youdao_meaning(text)
        if main:
            return {"main": main, "senses": [], "src_roman": "", "tgt_roman": "", "detected": src}
    pair = urllib.parse.quote(f"{src}|{target}")
    data = http_json(f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair={pair}")
    main = (data.get("responseData") or {}).get("translatedText") or ""
    if not main or data.get("quotaFinished"):
        raise RuntimeError("no translation service available")
    return {"main": main, "senses": [], "src_roman": "", "tgt_roman": "", "detected": src}


def youdao_meaning(text):
    """A short Chinese meaning from Youdao for an English word (or an English one for a Chinese word)."""
    try:
        data = http_json("https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(text), timeout=5)
    except Exception:
        return ""
    try:
        if CJK_RE.search(text):   # Chinese -> English: the first English word Youdao offers
            return data["ce"]["word"][0]["trs"][0]["tr"][0]["l"]["i"][0]["#text"]
        entry = data["ec"]["word"]
        entry = entry[0] if isinstance(entry, list) else entry
        line = entry["trs"][0]["tr"][0]["l"]["i"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    line = re.sub(r"^[a-z]+\.\s*", "", line)        # drop "adj. "
    return re.split(r"[；;，,]", line)[0].strip()


def google(text, source, target, hl):
    """Free Google Translate endpoint: translation, dictionary senses, romanization."""
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx"
           f"&sl={source}&tl={target}&hl={hl}&dt=t&dt=bd&dt=rm&q={urllib.parse.quote(text)}")
    data = http_json(url)
    main = "".join(seg[0] for seg in data[0] if seg and seg[0])
    src_roman = tgt_roman = ""
    for seg in data[0]:
        if seg and seg[0] is None and len(seg) > 3:
            tgt_roman, src_roman = seg[2] or "", seg[3] or ""
    senses = []
    if len(data) > 1 and data[1]:
        for entry in data[1][:4]:
            senses.append(f"{entry[0]}\u00a0 {'; '.join(entry[1][:5])}")
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else source
    return {"main": main, "senses": senses, "src_roman": src_roman,
            "tgt_roman": tgt_roman, "detected": detected}


def youdao(word):
    """Youdao EN->ZH dictionary: ({"US": ipa, "UK": ipa}, [sense lines]); empty when unknown."""
    try:
        data = http_json("https://dict.youdao.com/jsonapi?q=" + urllib.parse.quote(word), timeout=5)
        entry = data["ec"]["word"]
        entry = entry[0] if isinstance(entry, list) else entry
    except Exception:
        return {}, []
    pron = {}
    if entry.get("usphone"):
        pron["US"] = f"/{entry['usphone']}/"
    if entry.get("ukphone"):
        pron["UK"] = pron["Australia"] = f"/{entry['ukphone']}/"
    senses = []
    for tr in entry.get("trs", [])[:4]:
        try:
            line = tr["tr"][0]["l"]["i"][0]
        except (KeyError, IndexError, TypeError):
            continue
        if line.startswith("【名】"):  # proper-name entries are noise
            continue
        line = re.sub(r"^([a-z]+\.) ", "\\1\u00a0", line)  # keep part of speech on the same line
        senses.append(line if len(line) <= 70 else line[:70] + "…")
    return pron, senses


def romanization(roman, text):
    """Show romanization only when it adds something (pinyin, romaji, Cyrillic transliteration…)."""
    return {"*": roman} if roman and roman.lower() != text.lower() else {}


def look_up(text, learn, native):
    """Translate `text` for someone learning `learn` whose own language is `native`.

    Returns {trans, senses, pron, speak, speak_lang}. `pron` maps a voice variant
    (or "*") to a pronunciation guide. Selecting text in your own language gives
    you the word in the language you are learning, and that is what gets spoken.
    """
    first = translate(text, "auto", native, native, guess=learn)
    detected = normalize(first["detected"])

    if same_language(detected, native) and not same_language(native, learn):
        result = translate(text, detected, learn, native)
        trans = result["main"]
        # "Bonjour" may be detected as English; if translating it into French gives it back
        # unchanged, it was French all along, so fall through to the normal path.
        if trans.strip().lower() != text.strip().lower():
            pron, senses = {}, result["senses"]
            if learn == "en" and native == "zh-CN" and len(trans.split()) <= 3:
                pron, _ = youdao(trans)
            if not pron:
                pron = romanization(result["tgt_roman"], trans)
            return {"trans": trans, "senses": senses, "pron": pron, "speak": trans, "speak_lang": learn}
        detected = learn

    # Single Latin-script words are often mis-detected ("hidalgo" -> English),
    # so trust the language the user is learning unless the script clearly differs.
    source = detected
    if source is None or (source in LATIN_SCRIPT and learn in LATIN_SCRIPT):
        source = learn
    result = first if source == first["detected"] else translate(text, source, native, native)

    pron, senses = {}, result["senses"]
    if source == "en":
        if native == "zh-CN" and len(text.split()) <= 3:
            pron, yd_senses = youdao(text)
            senses = yd_senses or senses
        if not pron and result["src_roman"]:
            pron = {"*": f"/{result['src_roman']}/"}
    else:
        pron = romanization(result["src_roman"], text)
    return {"trans": result["main"], "senses": senses, "pron": pron,
            "speak": text, "speak_lang": source if source in LANGUAGES else learn}


def ocr_languages():
    from winrt.windows.media.ocr import OcrEngine
    return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]


def ocr_tag_for(learn):
    """Best installed Windows OCR language for `learn`, falling back to English."""
    wanted = ocr_tag(learn)
    try:
        installed = ocr_languages()
    except Exception:
        return "en-US"
    for tag in installed:
        if tag.lower() == wanted.lower():
            return tag
    prefix = wanted.split("-")[0].lower()
    for tag in installed:
        if tag.lower().startswith(prefix):
            return tag
    return next((t for t in installed if t.lower().startswith("en")), installed[0] if installed else "en-US")


def ocr_image(img, learn):
    import winocr
    img = img.convert("RGB")
    if img.height < 80:  # tiny snips OCR much better when upscaled
        scale = max(2, 80 // max(img.height, 1))
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    text = winocr.recognize_pil_sync(img, ocr_tag_for(learn)).get("text", "")
    text = " ".join(text.split())
    # Windows OCR puts spaces between CJK characters
    return re.sub(r"(?<=[\u3040-\u9fff\uac00-\ud7af]) (?=[\u3040-\u9fff\uac00-\ud7af])", "", text)
