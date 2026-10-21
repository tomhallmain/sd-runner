import gettext
import os

from lib.logging_setup import get_logger
from lib.utils import Utils

logger = get_logger("translations")

_LOCALEDIR = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "locale")


def _language_code(locale) -> str:
    """The language portion of a locale, such as ``de`` from ``de_DE.UTF-8``."""
    if locale is None:
        return ""
    text = str(locale).strip().lower()
    for separator in ("_", "-", "."):
        if separator in text:
            text = text.split(separator, 1)[0]
            break
    return text


def supported_locales() -> set[str]:
    """Language codes that have a catalog directory."""
    found = set()
    try:
        names = os.listdir(_LOCALEDIR)
    except OSError:
        return {"en"}
    for name in names:
        if os.path.isdir(os.path.join(_LOCALEDIR, name, "LC_MESSAGES")):
            found.add(name)
    found.add("en")
    return found


def resolve_locale(locale) -> str:
    """The catalog to load.

    An empty preference uses the system language. A language with no catalog
    uses English.
    """
    code = _language_code(locale)
    if not code:
        code = _language_code(Utils.get_default_user_language())
    if code in supported_locales():
        return code
    return "en"


_locale = resolve_locale(None)

class I18N:
    localedir = _LOCALEDIR
    locale = _locale
    # fallback: a system language without a catalog must not stop the import.
    translate = gettext.translation('base', localedir, languages=[_locale], fallback=True)

    @staticmethod
    def install_locale(locale, verbose=True):
        locale = resolve_locale(locale)
        I18N.locale = locale
        I18N.translate = gettext.translation('base', I18N.localedir, languages=[locale], fallback=True)
        I18N.translate.install()
        if verbose:
            logger.info("Switched locale to: " + locale)

    @staticmethod
    def _(s):
        # return gettext.gettext(s)
        try:
            return I18N.translate.gettext(s)
        except KeyError:
            return s

    @staticmethod
    def day_of_the_week(day_index=0):
        if day_index == 0:
            return I18N._('Monday')
        elif day_index == 1:
            return I18N._('Tuesday')
        elif day_index == 2:
            return I18N._('Wednesday')
        elif day_index == 3:
            return I18N._('Thursday')
        elif day_index == 4:
            return I18N._('Friday')
        elif day_index == 5:
            return I18N._('Saturday')
        else:
            return I18N._('Sunday')

    @staticmethod
    def time_ago(seconds: float) -> tuple[int, str]:
        """Convert seconds into a human-readable time difference.
        
        Returns:
            tuple[int, str]: A tuple containing:
                - The number of time units
                - The translated time unit (e.g. "hours", "minutes", etc.)
        """
        if seconds < 60:
            return int(seconds), I18N._("seconds")
        elif seconds < 3600:
            return int(seconds / 60), I18N._("minutes")
        elif seconds < 86400:
            return int(seconds / 3600), I18N._("hours")
        elif seconds < 604800:
            return int(seconds / 86400), I18N._("days")
        elif seconds < 2592000:
            return int(seconds / 604800), I18N._("weeks")
        elif seconds < 31536000:
            return int(seconds / 2592000), I18N._("months")
        else:
            return int(seconds / 31536000), I18N._("years")

    '''
    NOTE when gathering the translation strings, set _() == to gettext.gettext() instead of the above, and run:

        ```python C:\\Python310\\Tools\\i18n\pygettext.py -d base -o locale\\base.pot .```

    in the base directory. The POT output file can be used as source for the PO files in each locale.
    Run personal script C:\\Scripts\\i18n_manager.py to generate new PO files and look for invalid translations.

    Bonus command:
        ```git diff simple_image_compare\\locale\\de\\LC_MESSAGES\\base.po simple_image_compare\\locale\\de\\LC_MESSAGES\\base1.po | rg -v "^.*#" | rg -C 3 "^(-|\+)"```

    Then for each locale once the PO files are set up as desired, run below in the deepest locale directory to produce the MO file from the PO file:
        ```python C:\\Python310\\Tools\\i18n\\msgfmt.py -o base.mo base```
    '''
