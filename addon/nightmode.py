from anki import version as anki_version

def _parse_version_tuple(version_str: str):
    try:
        parts = version_str.split(".")
        # Pad or trim to 3 parts, coerce to int where possible
        ints = []
        for p in parts[:3]:
            try:
                ints.append(int(p))
            except Exception:
                ints.append(0)
        while len(ints) < 3:
            ints.append(0)
        return tuple(ints)
    except Exception:
        return (0, 0, 0)

old_anki = _parse_version_tuple(anki_version) < (2, 1, 20)

if not old_anki:
    try:
        from aqt.theme import theme_manager
    except Exception:
        theme_manager = None


def isnightmode():
    if old_anki:
        return False
    if theme_manager is None:
        return False
    return bool(getattr(theme_manager, "night_mode", False))
