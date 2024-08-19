import gettext
import os

from utils.utils import get_default_user_language

_locale = get_default_user_language()

class I18N:
    localedir = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), 'locale')
    locale = _locale
    translate = gettext.translation('base', localedir, languages=[_locale])

    @staticmethod
    def install_locale(locale, verbose=True):
        I18N.locale = locale
        I18N.translate = gettext.translation('base', I18N.localedir, languages=[locale], fallback=True)
        I18N.translate.install()
        if verbose:
            print("Switched locale to: " + locale)

    @staticmethod
    def _(s):
        # return gettext.gettext(s)
        try:
            return I18N.translate.gettext(s)
        except KeyError:
            return s

    '''
    NOTE when gathering the translation strings, set _() == to gettext.gettext() instead of the above, and run:

        ```python C:\Python310\Tools\i18n\pygettext.py -d base -o locale\base.pot .```

    in the base directory. The POT output file can be used as source for the PO files in each locale.
    Run personal script C:\Scripts\i18n_manager.py to generate new PO files and look for invalid translations.

    Bonus command:
        ```git diff simple_image_compare\locale\de\LC_MESSAGES\base.po simple_image_compare\locale\de\LC_MESSAGES\base1.po | rg -v "^.*#" | rg -C 3 "^(-|\+)"```

    Then for each locale once the PO files are set up as desired, run below in the deepest locale directory to produce the MO file from the PO file:
        ```python C:\Python310\Tools\i18n\msgfmt.py -o base.mo base```
    '''
