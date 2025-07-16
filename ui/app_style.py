

class AppStyle:
    IS_DEFAULT_THEME = False
    LIGHT_THEME = "light"
    DARK_THEME = "dark"
    BG_COLOR = "#053E10"  # Default dark green background
    FG_COLOR = "white"    # Default white foreground

    @staticmethod
    def get_theme_name():
        return AppStyle.DARK_THEME if AppStyle.IS_DEFAULT_THEME else AppStyle.LIGHT_THEME